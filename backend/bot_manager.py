#!/usr/bin/env python3
"""
Bot Manager Service

Automatically spawns LiveKit bots for new conversations.
Monitors Redis for conversation initialization events and starts bot processes.
"""

import asyncio
import logging
import os
import signal
import subprocess
from typing import Dict

import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class BotManager:
    """Manages bot processes for LiveKit rooms."""

    def __init__(self):
        self.redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost"))
        self.active_bots: Dict[str, subprocess.Popen] = {}  # room_name -> process
        self.shutdown = False

        # LiveKit configuration
        self.livekit_url = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880")
        self.livekit_api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
        self.livekit_api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
        self.bot_identity = os.getenv("BOT_IDENTITY", "buju-ai")

    async def start(self):
        """Start the bot manager service."""
        logger.info("Bot Manager starting...")
        logger.info(f"LiveKit URL: {self.livekit_url}")
        logger.info(f"Bot identity: {self.bot_identity}")

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Subscribe to conversation events
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("conversation_events")
        logger.info("Subscribed to conversation_events channel")

        print("[BOT_MANAGER_READY]", flush=True)

        try:
            async for message in pubsub.listen():
                if self.shutdown:
                    break

                if message["type"] == "message":
                    await self._handle_conversation_event(message["data"])
        except asyncio.CancelledError:
            logger.info("Bot manager cancelled")
        finally:
            await self.cleanup()

    async def _handle_conversation_event(self, data: bytes):
        """Handle conversation initialization events."""
        try:
            import json

            event = json.loads(data)

            if event.get("event") == "conversation_initialized":
                room_name = event.get("room_name")
                conversation_id = event.get("conversation_id")

                if not room_name:
                    logger.warning(
                        "Received conversation_initialized without room_name"
                    )
                    return

                logger.info(
                    f"New conversation initialized: {conversation_id} in room {room_name}"
                )
                await self.start_bot_for_room(room_name)

            elif event.get("event") == "conversation_ended":
                room_name = event.get("room_name")
                if room_name:
                    logger.info(f"Conversation ended for room {room_name}")
                    await self.stop_bot_for_room(room_name)

        except Exception as e:
            logger.error(f"Error handling conversation event: {e}", exc_info=True)

    async def start_bot_for_room(self, room_name: str):
        """Start a bot process for the specified room."""
        if room_name in self.active_bots:
            logger.info(f"Bot already active for room {room_name}")
            return

        try:
            # Fetch STT provider from Redis config (if available)
            stt_provider = "google"  # Default
            try:
                conversation_id = await self.redis_client.get(
                    f"room:{room_name}:conversation_id"
                )
                if conversation_id:
                    conversation_id = conversation_id.decode()
                    config = await self.redis_client.hgetall(
                        f"conversation:{conversation_id}"
                    )
                    if config and b"stt_provider" in config:
                        stt_provider = config[b"stt_provider"].decode()
            except Exception as e:
                logger.warning(
                    f"Failed to fetch STT provider from Redis: {e}, using default"
                )

            # Prepare environment for bot process
            env = os.environ.copy()
            env.update(
                {
                    "LIVEKIT_URL": self.livekit_url,
                    "LIVEKIT_API_KEY": self.livekit_api_key,
                    "LIVEKIT_API_SECRET": self.livekit_api_secret,
                    "LIVEKIT_ROOM": room_name,
                    "LIVEKIT_IDENTITY": self.bot_identity,
                    "STT_PROVIDER": stt_provider,
                }
            )
            # Always remove old logs before starting a new bot log session
            bot_log_path = ".bots.log"
            try:
                if os.path.exists(bot_log_path):
                    os.remove(bot_log_path)
            except Exception as e:
                logger.warning(f"Could not delete old log file {bot_log_path}: {e}")

            bot_log = open(bot_log_path, "a")
            bot_log.write(f"\n{'='*60}\n")
            bot_log.write(
                f"=== Bot started for room {room_name} (PID: will be assigned) ===\n"
            )
            bot_log.write(f"{'='*60}\n")
            bot_log.flush()

            process = subprocess.Popen(
                ["python", "livekit_bot.py"],
                env=env,
                stdout=bot_log,
                stderr=bot_log,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            # Store the log file handle so we can close it later
            process._bot_log_file = bot_log

            self.active_bots[room_name] = process
            logger.info(f"Started bot for room {room_name} (PID: {process.pid})")
            logger.info(f"  All bot logs: tail -f {bot_log_path} | grep '{room_name}'")

            # Monitor bot process
            asyncio.create_task(self._monitor_bot(room_name, process))

        except Exception as e:
            logger.error(
                f"Failed to start bot for room {room_name}: {e}", exc_info=True
            )

    async def _monitor_bot(self, room_name: str, process: subprocess.Popen):
        """Monitor a bot process and restart if it crashes."""
        try:
            # Wait for process to complete (or crash)
            returncode = await asyncio.get_event_loop().run_in_executor(
                None, process.wait
            )

            # Process ended
            if room_name in self.active_bots:
                del self.active_bots[room_name]

            if returncode != 0 and not self.shutdown:
                logger.warning(
                    f"Bot for room {room_name} crashed with code {returncode}"
                )
                # Could implement auto-restart here if desired
            else:
                logger.info(f"Bot for room {room_name} exited cleanly")

            # Close log file
            if hasattr(process, "_bot_log_file"):
                try:
                    process._bot_log_file.close()
                except:
                    pass

        except Exception as e:
            logger.error(
                f"Error monitoring bot for room {room_name}: {e}", exc_info=True
            )

    async def stop_bot_for_room(self, room_name: str):
        """Stop the bot process for the specified room."""
        if room_name not in self.active_bots:
            logger.info(f"No active bot for room {room_name}")
            return

        process = self.active_bots.pop(room_name, None)
        if process is None:
            logger.info(f"No active bot for room {room_name}")
            return

        try:
            if process.poll() is not None:
                logger.info(
                    f"Bot for room {room_name} already exited (PID: {process.pid})"
                )
                # Close log file if it's still open
                if hasattr(process, "_bot_log_file"):
                    try:
                        process._bot_log_file.close()
                    except:
                        pass
                return

            logger.info(f"Stopping bot for room {room_name} (PID: {process.pid})")

            # Send SIGINT for graceful shutdown
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(process.pid), signal.SIGINT)
                else:
                    process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                logger.info(
                    f"Bot process for room {room_name} not found when sending SIGINT (PID: {process.pid})"
                )

            # Wait for graceful shutdown (max 5 seconds)
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, process.wait),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Bot for room {room_name} didn't stop gracefully, killing"
                )
                process.kill()

            logger.info(f"Bot stopped for room {room_name}")

            # Close log file
            if hasattr(process, "_bot_log_file"):
                try:
                    process._bot_log_file.close()
                except:
                    pass

        except Exception as e:
            # Re-register the process so subsequent attempts can retry cleanly
            self.active_bots[room_name] = process
            logger.error(f"Error stopping bot for room {room_name}: {e}", exc_info=True)

    async def stop(self):
        """Stop the bot manager and all active bots."""
        logger.info("Bot manager stopping...")
        self.shutdown = True

        # Stop all active bots
        for room_name in list(self.active_bots.keys()):
            await self.stop_bot_for_room(room_name)

    async def cleanup(self):
        """Clean up resources."""
        await self.redis_client.aclose()
        logger.info("Bot manager stopped")


if __name__ == "__main__":
    manager = BotManager()
    try:
        asyncio.run(manager.start())
    except KeyboardInterrupt:
        logger.info("Bot manager interrupted")
