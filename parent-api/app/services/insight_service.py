"""
Builds parent insight payload from jubu_datastore (CapabilityDatastore + CapabilityDefinitionRegistry).
The parent app receives this structure and does not call jubu_datastore directly;
this backend uses jubu_datastore as the only source for insights.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app_backend.app.schemas.insight import (
    ParentInsightPayloadSchema,
    ParentInsightFrameworkSchema,
    ParentInsightItemSchema,
)

# Framework id -> parent-facing display name (per plan)
FRAMEWORK_DISPLAY_NAMES: Dict[str, str] = {
    "casel": "Social Emotional Learning",
    "developmental_milestones": "Developmental Milestones",
}

# Process-level cache so we don't create datastore/registry on every request
_capability_datastore: Any = None
_capability_registry: Any = None


def _humanize_identifier(value: str) -> str:
    """Turn identifiers like 'self_awareness' into 'Self Awareness'."""
    return value.replace("_", " ").strip().title()


def _get_capability_datastore():
    """Return CapabilityDatastore from jubu_datastore if available (cached per process)."""
    global _capability_datastore
    if _capability_datastore is not None:
        return _capability_datastore
    try:
        from jubu_datastore import DatastoreFactory
        if hasattr(DatastoreFactory, "create_capability_datastore"):
            _capability_datastore = DatastoreFactory.create_capability_datastore()
            return _capability_datastore
        from jubu_datastore import CapabilityDatastore
        _capability_datastore = CapabilityDatastore()
        return _capability_datastore
    except Exception:
        return None


def _get_capability_registry(definition_root_path: Optional[Path] = None):
    """Return CapabilityDefinitionRegistry with loaded definitions if available (cached per process)."""
    global _capability_registry
    if _capability_registry is not None:
        return _capability_registry
    try:
        from jubu_datastore.loaders.capability_loader import load_default_registry
        _capability_registry = load_default_registry(definition_root_path)
        return _capability_registry
    except Exception:
        try:
            from jubu_datastore.capability_loader import load_default_registry
            _capability_registry = load_default_registry(definition_root_path)
            return _capability_registry
        except Exception:
            return None


def build_parent_insight_payload(
    child_id: str,
    child_name: str,
    definition_root_path: Optional[Path] = None,
) -> ParentInsightPayloadSchema:
    """
    Build the parent insight payload for one child using jubu_datastore only.

    Uses CapabilityDatastore.get_child_capability_state(child_id) and
    CapabilityDefinitionRegistry.get_item(item_id) for labels.
    When capability datastore or registry is not available, returns a minimal
    payload (empty frameworks, placeholder summary) so the parent app always gets a valid response.
    """
    capability_ds = _get_capability_datastore()
    registry = _get_capability_registry(definition_root_path)

    if capability_ds is None or registry is None:
        return ParentInsightPayloadSchema(
            child_id=child_id,
            child_name=child_name,
            summary_sentence=f"Discoveries will appear here as {child_name} plays and explores.",
            frameworks=[],
            suggested_next_activity=None,
        )

    try:
        state_by_framework: Dict[str, List[Any]] = capability_ds.get_child_capability_state(child_id)
    except Exception:
        state_by_framework = {}

    frameworks: List[ParentInsightFrameworkSchema] = []
    all_demonstrated_labels: List[str] = []
    all_emerging_labels: List[str] = []

    ordered_framework_ids = ["casel", "developmental_milestones"]
    remaining_framework_ids = [
        framework_id
        for framework_id in state_by_framework.keys()
        if framework_id not in ordered_framework_ids
    ]

    for framework_id in ordered_framework_ids + remaining_framework_ids:
        state_list = state_by_framework.get(framework_id, [])
        display_name = FRAMEWORK_DISPLAY_NAMES.get(
            framework_id, framework_id.replace("_", " ").title()
        )
        items: List[ParentInsightItemSchema] = []
        for state in state_list or []:
            item_id = getattr(state, "item_id", None)
            current_status = getattr(state, "current_status", "not_observed")
            mastery_score = float(getattr(state, "mastery_score", 0.0) or 0.0)
            subsection_id = getattr(state, "subdomain", None) or getattr(state, "domain", None) or framework_id
            if not item_id:
                continue
            definition = registry.get_item(item_id) if registry else None
            parent_friendly_label = (
                getattr(definition, "parent_friendly_label", None) or item_id
            )
            subsection_display_name = _humanize_identifier(str(subsection_id))
            items.append(
                ParentInsightItemSchema(
                    item_id=item_id,
                    subsection_id=str(subsection_id),
                    subsection_display_name=subsection_display_name,
                    parent_friendly_label=parent_friendly_label,
                    status=current_status,
                    mastery_score=mastery_score,
                    evidence_snippet=None,
                )
            )
            if current_status == "demonstrated":
                all_demonstrated_labels.append(parent_friendly_label)
            elif current_status == "emerging":
                all_emerging_labels.append(parent_friendly_label)

        frameworks.append(
            ParentInsightFrameworkSchema(
                framework_id=framework_id,
                framework_display_name=display_name,
                items=items,
            )
        )

    # Build a short summary sentence from labels (child-level, not "today")
    if all_demonstrated_labels or all_emerging_labels:
        demonstrated = ", ".join(all_demonstrated_labels[:3]) if all_demonstrated_labels else None
        emerging = ", ".join(all_emerging_labels[:2]) if all_emerging_labels else None
        if demonstrated and emerging:
            summary_sentence = f"{child_name} has shown {demonstrated}, and is exploring {emerging}."
        elif demonstrated:
            summary_sentence = f"{child_name} has shown {demonstrated}."
        else:
            summary_sentence = f"{child_name} is exploring {emerging}."
    else:
        summary_sentence = f"{child_name}'s discoveries will appear here as they play and explore."

    return ParentInsightPayloadSchema(
        child_id=child_id,
        child_name=child_name,
        summary_sentence=summary_sentence,
        frameworks=frameworks,
        suggested_next_activity=None,
    )
