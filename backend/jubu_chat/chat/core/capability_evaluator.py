"""
Capability evaluation service for KidsChat.

Evaluates a conversation transcript against capability items (e.g. CASEL,
developmental milestones) via a simple per-item LLM rubric. Produces
CapabilityObservationResult list; persistence is a separate function.

This module is independent of ConversationManager and can be used from
tests or offline scripts (e.g. transcript + child_age from file).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.common.constants import MAX_CAPABILITY_ITEMS_TO_EVALUATE

logger = get_logger(__name__)

# Allowed observation statuses (ternary scoring)
VALID_OBSERVATION_STATUSES = frozenset({"not_observed", "emerging", "demonstrated"})

# Default safe status when parsing fails
DEFAULT_STATUS = "not_observed"
DEFAULT_CONFIDENCE = 0.0

# Internal cap so transcript is never unbounded when limits are omitted
INTERNAL_MAX_TURNS = 100


def _item_attr(item: Any, name: str, default: Any = None) -> Any:
    """Get attribute from an item that may be a dict (from get_all_items_definitions) or an object."""
    if item is None:
        return default
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


@dataclass
class CapabilityObservationResult:
    """Result of evaluating one capability item. Handoff format from evaluator to datastore."""

    item_id: str
    item_version: int
    framework: str
    domain: str
    subdomain: str
    observation_status: str  # not_observed | emerging | demonstrated
    confidence: Optional[float]
    evidence_text: Optional[str]
    evaluator_type: str
    evaluator_version: Optional[str]
    raw_score_json: Optional[dict[str, Any]]


def format_transcript_bounded(
    turns: List[Any],
    *,
    max_turns: Optional[int] = None,
    max_chars: Optional[int] = None,
    child_key: str = "child_message",
    assistant_key: str = "system_message",
    assistant_label: str = "Assistant",
) -> str:
    """
    Format conversation turns into a transcript string with explicit limits.

    Uses full transcript if it fits within max_chars; otherwise uses a bounded
    recent-turn window (last max_turns or truncate to max_chars). If neither
    max_turns nor max_chars is provided, applies INTERNAL_MAX_TURNS so the
    transcript is never unbounded.

    Args:
        turns: List of turn-like objects (dicts with child_key and assistant_key,
               or objects with .child_message and .system_message).
        max_turns: If set, use at most this many recent turns when over max_chars.
        max_chars: If set, truncate transcript to this length (count after formatting).
        child_key: Dict key or attribute name for child message.
        assistant_key: Dict key or attribute name for assistant message.
        assistant_label: Label for assistant in output (e.g. "Assistant" or "Boojoo").

    Returns:
        Formatted transcript: "Child: ...\\nAssistant: ...\\n"
    """
    if not turns:
        return "(no turns)"

    # Internal cap so we never return arbitrarily large transcripts
    effective_max_turns = (
        max_turns if max_turns is not None and max_turns > 0 else INTERNAL_MAX_TURNS
    )

    def _get_msg(turn: Any, key: str) -> str:
        if isinstance(turn, dict):
            return (turn.get(key) or "").strip()
        return (getattr(turn, key, None) or "").strip()

    # Apply turn bound first (last N turns)
    use_turns = (
        turns[-effective_max_turns:] if len(turns) > effective_max_turns else turns
    )

    lines: List[str] = []
    for turn in use_turns:
        child_msg = _get_msg(turn, child_key)
        sys_msg = _get_msg(turn, assistant_key)
        if child_msg and child_msg != "[message redacted for safety]":
            lines.append(f"Child: {child_msg}")
        elif child_msg == "[message redacted for safety]":
            lines.append("Child: [redacted]")
        if sys_msg:
            lines.append(f"{assistant_label}: {sys_msg}")
    full_text = "\n".join(lines) or "(no turns yet)"

    if max_chars is not None and len(full_text) > max_chars:
        full_text = full_text[: max_chars - 3] + "..."

    return full_text


def parse_observation_response(raw: str) -> dict[str, Any]:
    """
    Parse and normalize LLM response for one capability item.

    - Extracts JSON robustly (tolerates markdown code fences, leading/trailing text).
    - Validates observation_status against not_observed | emerging | demonstrated.
    - Clamps confidence to [0, 1].
    - On any failure, returns a safe default dict (not_observed, confidence 0).

    Returns:
        Dict with keys: observation_status, confidence, evidence_text, reasoning (optional).
    """
    out = {
        "observation_status": DEFAULT_STATUS,
        "confidence": DEFAULT_CONFIDENCE,
        "evidence_text": None,
        "reasoning": None,
    }
    if raw is not None and not isinstance(raw, str):
        raw = str(raw)
    raw = (raw or "").strip()
    if not raw:
        return out

    # Strip markdown code fences
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
    # Find first complete JSON object (matching braces); only parse if we got a balanced substring
    start = raw.find("{")
    extracted = False
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    raw = raw[start : i + 1]
                    extracted = True
                    break

    if start < 0 or not extracted:
        # No JSON object or unbalanced braces; don't try to parse
        return out

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Capability observation JSON parse failed: {e}")
        return out

    if not isinstance(data, dict):
        return out

    status = data.get("observation_status")
    if isinstance(status, str) and status.strip().lower() in VALID_OBSERVATION_STATUSES:
        out["observation_status"] = status.strip().lower()
    else:
        out["observation_status"] = DEFAULT_STATUS

    conf = data.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            out["confidence"] = max(0.0, min(1.0, c))
        except (TypeError, ValueError):
            out["confidence"] = DEFAULT_CONFIDENCE
    else:
        out["confidence"] = None

    if data.get("evidence_text") is not None:
        out["evidence_text"] = str(data["evidence_text"]).strip() or None
    if data.get("reasoning") is not None:
        out["reasoning"] = str(data["reasoning"]).strip() or None

    return out


# Prompt template for one item (v1: deterministic, one item -> one score)
_ITEM_EVALUATION_PROMPT = """\
You are evaluating a child's conversation with an AI companion against a single capability item.

Item: {title}

Definition:
{description}

Observable signals:
{observable_signals}

Positive evidence (counts as support):
{positive_evidence}

Negative evidence (does not count; avoid scoring as demonstrated if these apply):
{negative_evidence}

Transcript (Child and Assistant only):
---
{transcript}
---

Instructions:
- Score ONLY based on evidence present in the transcript. Do not infer or assume.
- evidence_text MUST be a direct quote or near-quote from the transcript, not a vague summary.
- If there is no relevant evidence, use observation_status "not_observed" and leave evidence_text empty or cite "No relevant evidence in transcript".

Return ONLY a JSON object (no markdown, no explanation):
{{
  "observation_status": "not_observed" | "emerging" | "demonstrated",
  "confidence": 0.0 to 1.0,
  "evidence_text": "<quote or near-quote from transcript, or empty string>",
  "reasoning": "<one short sentence if needed>"
}}
"""

# Prompt for step 1: which capability items are relevant to this transcript?
_RELEVANCE_SELECTION_PROMPT = """\
You are given a conversation transcript (Child and Assistant) and a list of capability items (e.g. developmental or SEL milestones). Your task is to select which items are RELEVANT to evaluate for this conversation—i.e. the conversation content could reasonably provide evidence for or against that item.

Transcript:
---
{transcript}
---

Capability items (id, title, short description):
---
{items_text}
---

Instructions:
- Include only item IDs for which the transcript might contain observable evidence (topics, behaviors, or skills mentioned or demonstrated).
- Exclude items that are clearly unrelated to the conversation.
- Return ONLY a JSON array of relevant item IDs, e.g. ["id1", "id2"]. No markdown, no explanation.
"""


def _parse_relevant_item_ids(raw: Any) -> List[str]:
    """Parse LLM response into a list of capability item IDs (step 1 of 2-step evaluation)."""
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()
    if not raw:
        return []

    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
    start = raw.find("[")
    if start < 0:
        # LLM might return a single quoted ID, e.g. "item.1"
        try:
            data = json.loads(raw)
            if isinstance(data, str) and data.strip():
                return [data.strip()]
        except json.JSONDecodeError:
            pass
        return []
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "[":
            depth += 1
        elif raw[i] == "]":
            depth -= 1
            if depth == 0:
                raw = raw[start : i + 1]
                break
    try:
        data = json.loads(raw)
        if isinstance(data, str) and data.strip():
            return [data.strip()]
        if not isinstance(data, list):
            return []
        # Flatten in case LLM returns nested arrays, e.g. [["id1"], "id2"]
        ids: List[str] = []
        for x in data:
            if isinstance(x, list):
                ids.extend(str(y).strip() for y in x if y)
            elif x:
                ids.append(str(x).strip())
        return ids
    except json.JSONDecodeError as e:
        logger.warning(f"Relevance selection JSON parse failed: {e}")
        return []


# Max transcript chars in relevance prompt to avoid blowing context (defense in depth)
_RELEVANCE_PROMPT_MAX_TRANSCRIPT_CHARS = 12000


def build_relevance_selection_prompt(transcript: str, items: List[Any]) -> str:
    """Build prompt for selecting which capability items are relevant to the transcript."""
    lines = []
    for item in items:
        iid = _item_attr(item, "id") or _item_attr(item, "item_id", "") or ""
        title = _item_attr(item, "title", "") or ""
        desc = _item_attr(item, "description", "") or ""
        if isinstance(desc, list):
            desc = " ".join(str(x) for x in desc)
        desc = (str(desc).strip() or "")[:300]
        lines.append(f"- id: {iid}, title: {title}, description: {desc}")
    items_text = "\n".join(lines) if lines else "(no items)"
    transcript_str = transcript or "(no transcript)"
    if len(transcript_str) > _RELEVANCE_PROMPT_MAX_TRANSCRIPT_CHARS:
        transcript_str = (
            transcript_str[: _RELEVANCE_PROMPT_MAX_TRANSCRIPT_CHARS - 3] + "..."
        )
    return _RELEVANCE_SELECTION_PROMPT.format(
        transcript=transcript_str,
        items_text=items_text,
    )


def select_relevant_items_for_transcript(
    transcript: str,
    items: List[Any],
    model: Any,
    task_enum: Any = None,
) -> List[Any]:
    """
    Step 1 of agentic 2-step evaluation: use the LLM to select which capability
    items are relevant to this transcript. Returns the subset of items that
    should be scored in step 2 (score_item_with_llm).

    If the LLM call fails or returns no IDs, returns all items (fallback to
    score everything).
    """
    from jubu_chat.chat.models.base_model import GenerationTask

    if not items:
        return []
    task = task_enum if task_enum is not None else GenerationTask.CAPABILITY_EVALUATE
    prompt = build_relevance_selection_prompt(transcript, items)
    id_to_item = {}
    for i in items:
        iid = _item_attr(i, "id") or _item_attr(i, "item_id", "")
        if iid:
            id_to_item[str(iid).strip()] = i
    try:
        if hasattr(model, "generate_with_prompt"):
            response = model.generate_with_prompt(prompt, task)
        else:
            response = model.generate_with_prompt(prompt)
        content = (
            getattr(response, "content", response)
            if not isinstance(response, str)
            else response
        )
        # Coerce to str so parser never sees non-string (e.g. dict from API)
        content_for_parse = (
            content
            if isinstance(content, str)
            else (str(content) if content is not None else "")
        )
        relevant_ids = _parse_relevant_item_ids(content_for_parse)
    except Exception as e:
        logger.warning(f"Relevance selection LLM call failed: {e}; scoring all items")
        return list(items)
    if not relevant_ids:
        logger.info("Relevance selection returned no IDs; scoring all items")
        return list(items)
    selected = [id_to_item[rid] for rid in relevant_ids if rid in id_to_item]
    missing = set(relevant_ids) - set(id_to_item.keys())
    if missing:
        logger.debug("Relevance selection referenced unknown IDs: %s", missing)
    return selected if selected else list(items)


def build_item_evaluation_prompt(
    item: Any,
    transcript: str,
) -> str:
    """
    Build the evaluation prompt for one capability item.

    Args:
        item: Capability item definition (must have title, description,
              observable_signals, positive_evidence_patterns, negative_evidence_patterns).
        transcript: Bounded transcript text.

    Returns:
        Prompt string for the LLM.
    """

    def _attr(obj: Any, name: str, default: str = "") -> str:
        v = _item_attr(obj, name, None)
        if v is None:
            return default
        if isinstance(v, list):
            return "\n".join(f"- {x}" for x in v) if v else default
        return str(v).strip() or default

    return _ITEM_EVALUATION_PROMPT.format(
        title=_attr(item, "title"),
        description=_attr(item, "description"),
        observable_signals=_attr(item, "observable_signals"),
        positive_evidence=_attr(item, "positive_evidence_patterns"),
        negative_evidence=_attr(item, "negative_evidence_patterns"),
        transcript=transcript or "(no transcript)",
    )


def _applies_to_age(item: Any, age: float) -> bool:
    """
    Return True if the item applies to the given age (age in years).

    Item can be an object with age_ranges (list of {min_age, max_age}) or a dict
    with "age_ranges". Used when the backend does age filtering over
    get_all_items_definitions() results; jubu_datastore does not implement
    get_items_for_age.
    """
    ranges = None
    if isinstance(item, dict):
        ranges = item.get("age_ranges")
    else:
        ranges = getattr(item, "age_ranges", None)
    if not ranges:
        return True  # no age_ranges => treat as applicable to all ages
    for ar in ranges:
        if isinstance(ar, dict):
            lo, hi = ar.get("min_age"), ar.get("max_age")
        else:
            lo, hi = getattr(ar, "min_age", None), getattr(ar, "max_age", None)
        if lo is not None and hi is not None and lo <= age <= hi:
            return True
    return False


def _get_all_items_from_registry(registry: Any) -> List[Any]:
    """
    Get all capability item definitions from the registry (no age filtering).

    Tries, in order: get_all_items_definitions(), get_all_items(), then
    get_packs() + pack.items / active_items(). jubu_datastore is expected to
    provide get_all_items_definitions() or get_all_items(); the backend does
    age filtering in select_applicable_items.
    """
    if hasattr(registry, "get_all_items_definitions") and callable(
        registry.get_all_items_definitions
    ):
        return list(registry.get_all_items_definitions())
    if hasattr(registry, "get_all_items") and callable(registry.get_all_items):
        return list(registry.get_all_items())
    # Fallback: packs with items
    packs = getattr(registry, "packs", None)
    if (
        packs is None
        and hasattr(registry, "get_packs")
        and callable(registry.get_packs)
    ):
        packs = registry.get_packs()
    items: List[Any] = []
    for pack in packs or []:
        if hasattr(pack, "items"):
            items.extend(pack.items)
        elif hasattr(pack, "active_items"):
            items.extend(pack.active_items())
    return items


def select_applicable_items(
    child_age: float,
    registry: Any,
    max_items: int = MAX_CAPABILITY_ITEMS_TO_EVALUATE,
) -> List[Any]:
    """
    Return capability items applicable to the given child age, capped at max_items.

    Prefer registry.get_all_items_definitions() or get_all_items() (backend does
    age filtering). If not present, uses registry.get_items_for_age(age), then
    registry.packs + items_for_age(age) for backward compatibility.
    """
    items: List[Any] = []
    if hasattr(registry, "get_items_for_age") and callable(registry.get_items_for_age):
        items = list(registry.get_items_for_age(child_age))
    elif hasattr(registry, "get_all_items_definitions") or hasattr(
        registry, "get_all_items"
    ):
        all_items = _get_all_items_from_registry(registry)
        framework_counts: dict[str, int] = {}
        all_item_ids: List[str] = []
        for item in all_items:
            framework = _item_attr(item, "framework", "") or "unknown"
            framework_counts[framework] = framework_counts.get(framework, 0) + 1
            item_id = _item_attr(item, "id", "") or _item_attr(item, "item_id", "")
            if item_id:
                all_item_ids.append(str(item_id).strip())
        logger.info(
            f"Capability evaluation: registry returned {len(all_items)} total items before age filtering (framework counts: {framework_counts})"
        )
        if all_item_ids:
            logger.debug(
                f"Capability evaluation: registry item ids before age filtering: {all_item_ids}"
            )
        items = [i for i in all_items if _applies_to_age(i, child_age)]
    else:
        packs = getattr(registry, "packs", None)
        if (
            packs is None
            and hasattr(registry, "get_packs")
            and callable(registry.get_packs)
        ):
            packs = registry.get_packs()
        for pack in packs or []:
            if hasattr(pack, "items_for_age"):
                items.extend(pack.items_for_age(child_age))
            elif hasattr(pack, "items") and hasattr(pack, "active_items"):
                active = pack.active_items()
                for i in active:
                    if hasattr(i, "applies_to_age") and i.applies_to_age(child_age):
                        items.append(i)
    # Deduplicate by item id (first occurrence wins)
    seen: set[str] = set()
    unique: List[Any] = []
    for i in items:
        iid = _item_attr(i, "id") or _item_attr(i, "item_id", "")
        if iid:
            sid = str(iid).strip()
            if sid not in seen:
                seen.add(sid)
                unique.append(i)
    if len(unique) > max_items:
        unique_framework_counts: dict[str, int] = {}
        for item in unique:
            framework = _item_attr(item, "framework", "") or "unknown"
            unique_framework_counts[framework] = (
                unique_framework_counts.get(framework, 0) + 1
            )
        logger.info(
            f"Capability evaluation: {len(unique)} unique age-applicable items before cap; "
            f"returning max_items={max_items} (framework counts: {unique_framework_counts})"
        )
        dropped_ids = [
            str(_item_attr(item, "id", "") or _item_attr(item, "item_id", "")).strip()
            for item in unique[max_items:]
        ]
        if any(dropped_ids):
            logger.debug(
                f"Capability evaluation: age-applicable items dropped by cap: {dropped_ids}"
            )
    return unique[:max_items]


def score_item_with_llm(
    item: Any,
    transcript: str,
    model: Any,
    task_enum: Any = None,
) -> dict[str, Any]:
    """
    Score one capability item using the LLM. Uses parser to normalize response.

    On parse failure, returns a safe default (not_observed, confidence 0) so
    the session evaluation does not crash.
    """
    from jubu_chat.chat.models.base_model import GenerationTask

    task = task_enum if task_enum is not None else GenerationTask.CAPABILITY_EVALUATE
    prompt = build_item_evaluation_prompt(item, transcript)
    try:
        if hasattr(model, "generate_with_prompt"):
            response = model.generate_with_prompt(prompt, task)
        else:
            response = model.generate_with_prompt(prompt)
        content = (
            getattr(response, "content", response)
            if not isinstance(response, str)
            else response
        )
    except Exception as e:
        logger.warning(f"LLM call failed for item {_item_attr(item, 'id', '?')}: {e}")
        return {
            "observation_status": DEFAULT_STATUS,
            "confidence": DEFAULT_CONFIDENCE,
            "evidence_text": None,
            "reasoning": str(e),
        }
    content_str = (
        content
        if isinstance(content, str)
        else (str(content) if content is not None else "")
    )
    parsed = parse_observation_response(content_str)
    return parsed


def evaluate_session_capabilities(
    *,
    child_id: str,
    session_id: str,
    child_age: float,
    transcript: str,
    registry: Any,
    model: Any,
    evaluator_type: str = "llm_rubric",
    evaluator_version: Optional[str] = None,
    max_items: int = MAX_CAPABILITY_ITEMS_TO_EVALUATE,
    task_enum: Any = None,
) -> List[CapabilityObservationResult]:
    """
    Evaluate a session transcript against applicable capability items.

    Uses a 2-step agentic flow:
    1. Select applicable items by age (select_applicable_items), then have the
       LLM select which of those are relevant to this transcript
       (select_relevant_items_for_transcript).
    2. Score only those relevant items with score_item_with_llm.

    Returns a list of CapabilityObservationResult (one per scored item). Does not
    persist; call persist_capability_results separately when persistence is desired.
    """
    from jubu_chat.chat.models.base_model import GenerationTask

    task = task_enum if task_enum is not None else GenerationTask.CAPABILITY_EVALUATE
    items = select_applicable_items(child_age, registry, max_items=max_items)
    if not items:
        logger.info(
            f"No capability items for age {child_age} (registry returned 0 age-applicable items); skipping evaluation. "
            "Check that the capability registry has packs loaded and that item age_ranges include this age.",
        )
        return []

    logger.info(
        f"Capability evaluation: 2-step flow starting with {len(items)} age-applicable items (child_age={child_age:.1f}, session_id={session_id!r})",
    )

    # Step 1: LLM selects which items are relevant to this transcript
    items_to_score = select_relevant_items_for_transcript(
        transcript, items, model, task_enum=task
    )
    logger.info(
        f"Capability evaluation: step 1 selected {len(items_to_score)} items relevant to transcript (from {len(items)} age-applicable)",
    )
    if items_to_score:
        selected_summary = [
            f"{_item_attr(i, 'id', '') or _item_attr(i, 'item_id', '?')} ({_item_attr(i, 'title', '') or '?'})"
            for i in items_to_score
        ]
        logger.info(f"Capability evaluation: step 1 selected items: {selected_summary}")

    results: List[CapabilityObservationResult] = []
    for item in items_to_score:
        item_id = _item_attr(item, "id", "") or _item_attr(item, "item_id", "")
        try:
            item_version = int(_item_attr(item, "version", 1))
        except (TypeError, ValueError):
            item_version = 1
        framework = _item_attr(item, "framework", "") or ""
        domain = _item_attr(item, "domain", "") or ""
        subdomain = _item_attr(item, "subdomain", "") or ""
        try:
            scored = score_item_with_llm(item, transcript, model, task_enum=task)
        except Exception as e:
            logger.warning(f"Item {item_id} evaluation failed: {e}")
            scored = {
                "observation_status": DEFAULT_STATUS,
                "confidence": DEFAULT_CONFIDENCE,
                "evidence_text": None,
                "reasoning": str(e),
            }
        raw_score = dict(scored)
        results.append(
            CapabilityObservationResult(
                item_id=item_id,
                item_version=item_version,
                framework=framework,
                domain=domain,
                subdomain=subdomain,
                observation_status=scored.get("observation_status", DEFAULT_STATUS),
                confidence=scored.get("confidence"),
                evidence_text=scored.get("evidence_text"),
                evaluator_type=evaluator_type,
                evaluator_version=evaluator_version,
                raw_score_json=raw_score,
            )
        )
    # Log step 2 summary (counts by observation_status) and per-item outcomes
    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.observation_status] = (
            status_counts.get(r.observation_status, 0) + 1
        )
    logger.info(
        f"Capability evaluation: step 2 scored {len(results)} items; status counts: {status_counts}",
    )
    for r in results:
        reason = (r.evidence_text or (r.raw_score_json or {}).get("reasoning") or "")[
            :200
        ]
        logger.info(
            f"Capability evaluation: item {r.item_id} -> {r.observation_status}"
            + (f" (confidence={r.confidence})" if r.confidence is not None else ""),
        )
        if reason:
            logger.debug(
                f"Capability evaluation: item {r.item_id} reasoning/evidence: {reason}"
            )
    return results


def persist_capability_results(
    child_id: str,
    session_id: str,
    results: List[CapabilityObservationResult],
    datastore: Any,
    observed_at: Optional[datetime] = None,
) -> None:
    """
    Write capability observation results to the datastore.

    Call this after successful evaluate_session_capabilities when persistence
    is desired (production default). Skip in tests/dry-runs/offline scripts.
    """
    if observed_at is None:
        observed_at = datetime.utcnow()
    failed = 0
    for r in results:
        observation_data = {
            "child_id": child_id,
            "session_id": session_id,
            "item_id": r.item_id,
            "item_version": r.item_version,
            "framework": r.framework,
            "domain": r.domain,
            "subdomain": r.subdomain,
            "observation_status": r.observation_status,
            "evaluator_type": r.evaluator_type,
            "observed_at": observed_at,
            "confidence": r.confidence,
            "evidence_text": r.evidence_text,
            "evaluator_version": r.evaluator_version,
            "raw_score_json": r.raw_score_json,
        }
        try:
            datastore.insert_capability_observation(observation_data)
        except Exception as e:
            failed += 1
            logger.error(f"Failed to persist observation for item {r.item_id}: {e}")
    persisted = len(results) - failed
    if failed:
        logger.warning(
            f"Capability evaluation: persisted {persisted}/{len(results)} observations for session_id={session_id!r} (child_id={child_id!r}); {failed} failed",
        )
    else:
        logger.info(
            f"Capability evaluation: persisted {persisted} observations for session_id={session_id!r} (child_id={child_id!r})",
        )
