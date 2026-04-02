#!/usr/bin/env python3
"""
LiveKit Bot API Server

HTTP API for managing LiveKit bot conversations, including initialization
and status endpoints.
"""

import logging
import os
import uuid
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse, urlunparse

import redis.asyncio as redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from livekit.api import AccessToken, VideoGrants
from pydantic import BaseModel

from api_server.jubu_adapter import JubuAdapter

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="LiveKit Conversation API")

# --- Singleton Adapter and Redis Client ---
adapter: Optional[JubuAdapter] = None
redis_client: Optional[redis.Redis] = None


@app.on_event("startup")
async def startup_event():
    global adapter, redis_client
    logging.getLogger("grpc").setLevel(logging.WARNING)
    logging.getLogger("google.auth.transport.requests").setLevel(logging.WARNING)
    logger.info("Application startup: Initializing JubuAdapter and Redis client...")
    adapter = JubuAdapter()
    redis_client = await redis.from_url(os.getenv("REDIS_URL", "redis://localhost"))
    logger.info("Application startup: JubuAdapter and Redis client initialized.")


@app.on_event("shutdown")
async def shutdown_event():
    if redis_client:
        await redis_client.aclose()
    logger.info("Application shutdown: Redis client closed.")


class ConversationInitRequest(BaseModel):
    # Backend generates room_name (removed from request)
    user_id: Optional[str] = None  # Optional user ID for traceability
    conversation_id: Optional[str] = None
    interaction_type: Optional[str] = "chitchat"
    model: Optional[str] = "gemini-2.0-flash"
    stt_provider: Optional[str] = "google"
    tts_provider: Optional[str] = "elevenlabs"
    tts_voice: Optional[str] = None
    streaming_tts: Optional[bool] = True
    speculation_enabled: Optional[bool] = True  # Enable speculative LLM processing
    # Child profile
    child_id: Optional[str] = None
    child_profile_path: Optional[str] = None


class ConversationStatusResponse(BaseModel):
    conversation_id: str
    room_name: str
    is_active: bool
    streaming_tts: bool  # Standardized to 'streaming_tts'
    speculation_enabled: bool
    stt_provider: str
    tts_provider: str


def generate_livekit_token(
    room_name: str,
    participant_identity: str,
    api_key: str,
    api_secret: str,
    ttl_hours: int = 2,  # Shorter TTL for security (affects initial connect only)
) -> str:
    """
    Generate a LiveKit JWT token for a participant to join a room.

    Note: Token expiry only affects the initial connection. Once connected,
    reconnects don't re-check the original expiry.
    """
    token = AccessToken(api_key, api_secret)
    token.with_identity(participant_identity)
    token.with_name(participant_identity)
    token.with_grants(
        VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        )
    )
    # Set token expiration (timedelta object)
    token.with_ttl(timedelta(hours=ttl_hours))
    return token.to_jwt()


def generate_room_name(conversation_id: str) -> str:
    """Generate a collision-free room name based on conversation ID."""
    return f"conv_{conversation_id}"


def generate_participant_identity(user_id: Optional[str], conversation_id: str) -> str:
    """
    Generate a unique participant identity.

    Format: user_<userId>_<shortId> or user_<uuid> if no user_id provided.
    """
    if user_id:
        # Use user_id + short conversation ID for traceability
        short_id = conversation_id[:8]
        return f"user_{user_id}_{short_id}"
    else:
        # Fallback: use conversation ID
        return f"user_{conversation_id[:16]}"


@app.post("/initialize_conversation")
async def initialize_conversation_endpoint(params: ConversationInitRequest):
    """
    Initialize a new conversation and return LiveKit connection details.

    Backend generates:
    - conversation_id (UUID)
    - room_name (conv_<uuid>)
    - participant_identity (user_<userId>_<shortId> or user_<uuid>)
    - access_token (JWT with 2-hour TTL)

    Returns: ws_url, room_name, identity, token for frontend to connect.
    """
    global adapter, redis_client
    if adapter is None or redis_client is None:
        raise HTTPException(
            status_code=503, detail="Server is starting up, please try again."
        )

    # Backend generates conversation_id and room_name
    conversation_id = params.conversation_id or str(uuid.uuid4())
    room_name = generate_room_name(conversation_id)
    participant_identity = generate_participant_identity(
        params.user_id, conversation_id
    )

    logger.info(
        f"Initializing conversation {conversation_id} for room {room_name} (identity: {participant_identity})"
    )

    # Default providers
    stt_provider = params.stt_provider or "google"
    tts_provider = params.tts_provider or "elevenlabs"

    # Get LiveKit credentials
    livekit_url = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880")

    parsed_url = urlparse(livekit_url)
    hostname = parsed_url.hostname or ""

    # Auto-detect LAN IP for device testing if using localhost-style hosts
    if hostname in {"127.0.0.1", "localhost", "0.0.0.0"}:
        try:
            import subprocess

            # Get LAN IP automatically
            proc = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, timeout=5
            )
            for line in proc.stdout.split("\n"):
                if (
                    "inet " in line
                    and "127.0.0.1" not in line
                    and "inet 169.254" not in line
                ):
                    lan_ip = line.split()[1]
                    # Prefer common LAN ranges
                    if lan_ip.startswith(("192.168.", "172.20.", "10.")):
                        port = parsed_url.port or 7880
                        netloc = f"{lan_ip}:{port}"
                        auto_url = urlunparse(parsed_url._replace(netloc=netloc))
                        logger.info(
                            "Auto-detected LAN IP: %s, using %s for device compatibility (was %s)",
                            lan_ip,
                            auto_url,
                            livekit_url,
                        )
                        livekit_url = auto_url
                        break
        except Exception as e:
            logger.warning(
                f"Could not auto-detect LAN IP: {e}, using configured URL: {livekit_url}"
            )

    livekit_api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")

    # Demo mode (Option 2): when client does not send child_id, use DEMO_CHILD_ID from env
    effective_child_id = params.child_id
    effective_user_id = params.user_id

    if os.getenv("DEMO_MODE") == "1":
        demo_child = os.getenv("DEMO_CHILD_ID")
        demo_parent = os.getenv("DEMO_PARENT_ID")
        if demo_child:
            effective_child_id = demo_child.strip('"').strip("'")
        if demo_parent:
            effective_user_id = demo_parent.strip('"').strip("'")
        logger.info(
            "DEMO_MODE=1: Enforcing DEMO IDs (child_id=%s, user_id=%s)",
            effective_child_id,
            effective_user_id,
        )
    elif not effective_child_id and os.getenv("DEMO_CHILD_ID"):
        effective_child_id = os.getenv("DEMO_CHILD_ID").strip('"').strip("'")
        logger.info(
            "Demo mode fallback: using DEMO_CHILD_ID for conversation (child_id=%s)",
            effective_child_id,
        )

    try:
        result = adapter.initialize_conversation(
            conversation_id=conversation_id,
            interaction_type=params.interaction_type,
            model=params.model,
            child_id=effective_child_id,
            child_profile_path=params.child_profile_path,
            stt_provider=stt_provider,
            tts_provider=tts_provider,
            tts_voice=params.tts_voice,
            streaming_tts=bool(params.streaming_tts),
        )

        # Generate client token for LiveKit (2-hour TTL for security)
        client_token = generate_livekit_token(
            room_name=room_name,
            participant_identity=participant_identity,
            api_key=livekit_api_key,
            api_secret=livekit_api_secret,
            ttl_hours=2,  # Short TTL for security
        )

        # Store conversation config in Redis for thinker to access
        await redis_client.hset(
            f"conversation:{conversation_id}",
            mapping={
                "conversation_id": conversation_id,
                "room_name": room_name,
                "user_id": effective_user_id or "",
                "participant_identity": participant_identity,
                "streaming_tts": str(bool(params.streaming_tts)),
                "speculation_enabled": str(bool(params.speculation_enabled)),
                "stt_provider": stt_provider,
                "tts_provider": tts_provider,
                "interaction_type": params.interaction_type or "chitchat",
            },
        )
        # Also map room_name to conversation_id for easy lookup by the thinker
        await redis_client.set(f"room:{room_name}:conversation_id", conversation_id)
        logger.info(
            f"Stored conversation config in Redis for room {room_name} (conv_id: {conversation_id})"
        )

        # Publish event to bot manager to spawn bot for this room
        import json

        await redis_client.publish(
            "conversation_events",
            json.dumps(
                {
                    "event": "conversation_initialized",
                    "conversation_id": conversation_id,
                    "room_name": room_name,
                }
            ),
        )
        logger.info(f"Published conversation_initialized event for room {room_name}")

    except Exception as e:
        logger.exception(f"Failed to initialize conversation {conversation_id}")
        raise HTTPException(
            status_code=500, detail=f"Error initializing conversation: {e}"
        )

    logger.info(
        f"Successfully initialized conversation {conversation_id} with token for client"
    )

    # Return LiveKit connection details (matches best practice)
    return JSONResponse(
        content={
            # LiveKit connection details (what frontend needs)
            "ws_url": livekit_url,
            "room_name": room_name,
            "identity": participant_identity,
            "token": client_token,
            # Conversation metadata
            "conversation_id": conversation_id,
            "user_id": params.user_id,
            # Initial system response (for display)
            "system_response": result["system_response"],
            "audio_data": result.get("audio_data"),
            # Configuration (for debugging/display)
            "interaction_type": result["interaction_type"],
            "child_id": result.get("child_id"),
            "streaming_tts": bool(params.streaming_tts),
            "speculation_enabled": bool(params.speculation_enabled),
            "stt_provider": stt_provider,
            "tts_provider": tts_provider,
        }
    )


@app.get("/conversation/{conversation_id}/status")
async def get_conversation_status(conversation_id: str):
    global adapter, redis_client  # Declare global to ensure access
    if adapter is None or redis_client is None:
        raise HTTPException(
            status_code=503, detail="Server is starting up, please try again."
        )

    # Check if conversation exists in adapter's memory (optional, Redis is source of truth)
    if not adapter.is_conversation_active(conversation_id):
        # Try to load from Redis if not in memory
        config = await redis_client.hgetall(f"conversation:{conversation_id}")
        if not config:
            raise HTTPException(
                status_code=404, detail="Conversation not found or inactive."
            )

    # Retrieve config from Redis
    config = await redis_client.hgetall(f"conversation:{conversation_id}")
    if not config:
        raise HTTPException(
            status_code=404, detail="Conversation config not found in Redis."
        )

    return ConversationStatusResponse(
        conversation_id=config.get(
            b"conversation_id", b""
        ).decode(),  # Return the correct ID from Redis
        room_name=config.get(b"room_name", b"").decode(),
        is_active=True,  # Assuming if config exists, it's active
        streaming_tts=config.get(b"streaming_tts", b"false").decode().lower() == "true",
        speculation_enabled=config.get(b"speculation_enabled", b"true").decode().lower()
        == "true",
        stt_provider=config.get(b"stt_provider", b"").decode(),
        tts_provider=config.get(b"tts_provider", b"").decode(),
    )


@app.delete("/conversation/{conversation_id}")
async def cleanup_conversation(conversation_id: str):
    """End a conversation and run capability evaluation.

    Call this when the frontend/user explicitly ends the session (e.g. "End
    conversation" button). This runs end_conversation() and thus capability
    evaluation when enabled. If the user leaves the room without calling this
    (e.g. closes app), the bot publishes participant_disconnected and the
    thinker performs the same cleanup."""
    global adapter, redis_client  # Declare global to ensure access
    if adapter is None or redis_client is None:
        raise HTTPException(
            status_code=503, detail="Server is starting up, please try again."
        )

    # Get room_name before deleting
    config = await redis_client.hgetall(f"conversation:{conversation_id}")
    room_name = None
    if config and b"room_name" in config:
        room_name = config[b"room_name"].decode()

    if adapter.is_conversation_active(conversation_id):
        adapter.cleanup_conversation_resources(conversation_id)
        logger.info(f"Cleaned up conversation {conversation_id} resources.")

    # Remove from Redis
    if room_name:
        await redis_client.delete(f"room:{room_name}:conversation_id")

        # Notify bot manager to stop bot
        import json

        await redis_client.publish(
            "conversation_events",
            json.dumps(
                {
                    "event": "conversation_ended",
                    "conversation_id": conversation_id,
                    "room_name": room_name,
                }
            ),
        )
        logger.info(f"Published conversation_ended event for room {room_name}")

    await redis_client.delete(f"conversation:{conversation_id}")
    logger.info(f"Removed conversation {conversation_id} from Redis.")

    return {"message": f"Conversation {conversation_id} cleaned up."}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
