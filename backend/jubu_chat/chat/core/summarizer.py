"""
Non-blocking conversation summarizer for Boojoo.

Produces a rolling_summary (≤400 chars) and scene_memory dict from recent
conversation turns.  Runs inside a thread-pool executor so it never blocks
the streaming LLM or TTS paths.

Usage (inside ConversationManager):
    self.executor.submit(run_summarization, self.summary_model, turn_state, recent_turns)
"""

import json
import logging
from typing import List

from jubu_chat.chat.core.turn_state import SceneMemory, TurnState
from jubu_chat.chat.domain.value_objects import ConversationTurn
from jubu_chat.chat.models.base_model import GenerationTask

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT_TEMPLATE = """\
You are summarizing a conversation between a child (age {age_bucket}) and Boojoo, an AI companion.

Previous summary:
{rolling_summary}

Recent conversation turns:
{formatted_turns}

Return ONLY a JSON object (no markdown, no explanation):
{{
  "rolling_summary": "<string, max 400 characters: key events and emotional tone>",
  "scene_memory": {{
    "character_name": "<current character name, or empty string>",
    "setting": "<current setting/location, or empty string>",
    "goal": "<current story/game goal, or empty string>",
    "special_object": "<important object in the scene, or empty string>"
  }}
}}

Rules:
- rolling_summary: capture the arc of the conversation and the child's mood/interests in ≤400 chars
- scene_memory: only fill fields that are active right now; use empty string for anything not in play
- If there is no active story or pretend-play scenario, leave all scene_memory fields empty
"""


def _format_turns(turns: List[ConversationTurn]) -> str:
    lines = []
    for turn in turns:
        if turn.child_message and turn.child_message != "[message redacted for safety]":
            lines.append(f"Child: {turn.child_message}")
        elif turn.child_message == "[message redacted for safety]":
            lines.append("Child: [redacted]")
        if turn.system_message:
            lines.append(f"Boojoo: {turn.system_message}")
    return "\n".join(lines) or "(no turns yet)"


def run_summarization(
    model,
    turn_state: TurnState,
    recent_turns: List[ConversationTurn],
) -> None:
    """
    Run one summarization pass and update turn_state in-place.

    On failure, logs the error and leaves turn_state unchanged.

    Args:
        model: Any model with a generate_with_prompt(prompt, task) method.
        turn_state: The session TurnState to update.
        recent_turns: The last N ConversationTurn objects to summarise.
    """
    try:
        prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(
            age_bucket=turn_state.age_bucket,
            rolling_summary=turn_state.rolling_summary or "No prior summary.",
            formatted_turns=_format_turns(recent_turns),
        )

        response = model.generate_with_prompt(prompt, GenerationTask.FACTS_EXTRACT)

        # Parse the JSON response
        raw = response.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)

        new_summary = str(data.get("rolling_summary", "")).strip()
        # Enforce max 400 chars
        if len(new_summary) > 400:
            new_summary = new_summary[:397] + "..."

        scene_data = data.get("scene_memory", {})
        new_scene = SceneMemory(
            character_name=str(scene_data.get("character_name", "")).strip(),
            setting=str(scene_data.get("setting", "")).strip(),
            goal=str(scene_data.get("goal", "")).strip(),
            special_object=str(scene_data.get("special_object", "")).strip(),
        )

        turn_state.rolling_summary = new_summary
        turn_state.scene_memory = new_scene

        logger.info(
            f"Summarization complete: summary_len={len(new_summary)} scene={new_scene.model_dump()}"
        )

    except json.JSONDecodeError as exc:
        logger.warning(
            f"Summarizer returned non-JSON response; keeping old summary. Error: {exc}"
        )
    except Exception as exc:
        logger.error(f"Summarization failed (will keep old summary): {exc}")
