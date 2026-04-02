"""
Parent-facing summary and activity suggestions at conversation end.

Builds a single LLM prompt to produce a short parent-friendly summary and
2–3 suggested parent–child activities; returns one string for storage in
parent_summary. On parse/LLM errors returns a safe fallback and does not raise.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.models.base_model import GenerationTask

logger = get_logger(__name__)

FALLBACK_SUMMARY = "Summary not available."

_PARENT_SUMMARY_PROMPT_TEMPLATE = """You are helping parents understand what their child did in a conversation with an AI assistant (Boojoo). Based on the transcript below, write:

1. A short, parent-friendly paragraph (2–4 sentences) summarizing what the child and Boojoo talked about, what stood out (mood, topics, interests, or skills), and anything notable.
2. One to two suggested parent–child activities: follow-up play, visits to museums, parks, libraries, or books or topics to explore together, or similar.

Rules:
- Keep the summary brief for short conversations; for long ones you may use more detail but never exceed {max_words} words in total for the entire response.
- Write in a warm, supportive tone. Do not use jargon.
- Output valid JSON only, with exactly these keys: "summary" (string) and "suggested_activities" (array of strings, 2–3 items).
- No other text before or after the JSON.

Transcript (child and Boojoo):
{transcript}
"""


def _strip_markdown_fences(raw: str) -> str:
    """Remove markdown code fences if present."""
    s = raw.strip()
    if s.startswith("```"):
        parts = s.split("```", 2)
        if len(parts) >= 2:
            s = parts[1]
            if s.startswith("json"):
                s = s[4:]
    return s.strip()


def _word_count(text: str) -> int:
    """Approximate word count (split on whitespace)."""
    return len(text.split()) if text else 0


def _truncate_to_max_words(text: str, max_words: int) -> str:
    """Truncate to at most max_words, adding '...' if cut."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " ..."


def build_parent_summary_prompt(
    transcript: str,
    child_age: Optional[float] = None,
    max_words: int = 200,
) -> str:
    """
    Build the LLM prompt for parent summary and activities.

    Args:
        transcript: Formatted conversation transcript (e.g. from format_transcript_bounded).
        child_age: Optional child age for prompt (currently not embedded; reserved for future).
        max_words: Maximum total words for the model's response (summary + activities).

    Returns:
        Prompt string for the model.
    """
    return _PARENT_SUMMARY_PROMPT_TEMPLATE.format(
        max_words=max_words,
        transcript=transcript or "(no conversation)",
    )


def parse_parent_summary_response(
    content: str,
    max_summary_words: int = 200,
) -> str:
    """
    Parse LLM JSON response into a single string for parent_summary storage.

    Expected JSON: {"summary": "...", "suggested_activities": ["...", ...]}.
    Output format: "Summary: ...\\n\\nSuggested activities:\\n1. ...\\n2. ..."

    Args:
        content: Raw model response (may include markdown fences).
        max_summary_words: Cap for combined output length (truncate if needed).

    Returns:
        Single string suitable for parent_summary, or FALLBACK_SUMMARY on parse failure.
    """
    if not content or not content.strip():
        return FALLBACK_SUMMARY
    raw = _strip_markdown_fences(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Parent summary response was not valid JSON: {e}")
        return FALLBACK_SUMMARY
    summary = (data.get("summary") or "").strip()
    activities = data.get("suggested_activities")
    if not isinstance(activities, list):
        activities = []
    activities = [str(a).strip() for a in activities if a]

    lines = []
    if summary:
        lines.append(f"Summary: {summary}")
    if activities:
        lines.append("")
        lines.append("Suggested activities:")
        for i, act in enumerate(activities, 1):
            lines.append(f"{i}. {act}")
    combined = "\n".join(lines).strip()
    if not combined:
        return FALLBACK_SUMMARY
    # Enforce word cap on final string
    if _word_count(combined) > max_summary_words:
        combined = _truncate_to_max_words(combined, max_summary_words)
    return combined


def generate_parent_summary(
    transcript: str,
    model: Any,
    child_age: Optional[float] = None,
    max_summary_words: int = 200,
) -> str:
    """
    Generate parent-facing summary and activities via LLM; return one string for storage.

    Uses model.generate_with_prompt(prompt, GenerationTask.PARENT_SUMMARY).
    On any error (LLM failure, parse failure), returns FALLBACK_SUMMARY and logs; does not raise.

    Args:
        transcript: Formatted conversation transcript.
        model: Model with generate_with_prompt(prompt, task) (e.g. GenerationTask.PARENT_SUMMARY).
        child_age: Optional child age (for future prompt tuning).
        max_summary_words: Max words for the whole response (prompt + output cap).

    Returns:
        Single string (summary + suggested activities) or FALLBACK_SUMMARY.
    """
    try:
        prompt = build_parent_summary_prompt(
            transcript=transcript,
            child_age=child_age,
            max_words=max_summary_words,
        )
        task = GenerationTask.PARENT_SUMMARY
        if hasattr(model, "generate_with_prompt"):
            response = model.generate_with_prompt(prompt, task)
        else:
            response = model.generate_with_prompt(prompt)
        content = (
            getattr(response, "content", response)
            if not isinstance(response, str)
            else response
        )
        if content is None:
            content = ""
        content_str = content if isinstance(content, str) else str(content)
        return parse_parent_summary_response(
            content_str,
            max_summary_words=max_summary_words,
        )
    except Exception as e:
        logger.warning(f"Parent summary generation failed: {e}", exc_info=True)
        return FALLBACK_SUMMARY
