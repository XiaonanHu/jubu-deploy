"""
Seed zero-valued child_capability_state rows for a child (e.g. on new profile init).

Used when a new child profile is created so the child has all capability items
in the DB with zero values. Idempotent: safe to call multiple times.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from infrastructure.logging import get_logger

logger = get_logger(__name__)


def _item_attr(item: Any, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _get_all_items(registry: Any) -> list[Any]:
    if hasattr(registry, "get_all_items_definitions") and callable(
        registry.get_all_items_definitions
    ):
        return list(registry.get_all_items_definitions())
    if hasattr(registry, "get_all_items") and callable(registry.get_all_items):
        return list(registry.get_all_items())
    raise RuntimeError(
        "Registry does not expose get_all_items_definitions() or get_all_items()."
    )


def seed_child_capability_state_on_init(
    child_id: str,
    connection_string: Optional[str] = None,
) -> None:
    """
    Seed all capability items for a child with zero-valued state (reset then insert).

    Intended to be called when a new child profile is created. Resets any existing
    capability state for this child, then inserts one row per registry item with
    not_observed / 0 values. Does not raise; logs and returns on failure.
    """
    if not child_id or not str(child_id).strip():
        return
    try:
        from jubu_chat.chat.datastores import CapabilityDatastore, load_default_registry
        from jubu_datastore.models.capability_schema import ChildCapabilityStateModel
    except ImportError as e:
        logger.debug("Capability state seeding skipped (import): %s", e)
        return

    try:
        registry = load_default_registry()
        items = _get_all_items(registry)
    except Exception as e:
        logger.warning("Capability state seeding skipped (registry): %s", e)
        return

    try:
        datastore = CapabilityDatastore(connection_string=connection_string)
    except Exception as e:
        logger.warning("Capability state seeding skipped (datastore): %s", e)
        return

    try:
        # Reset: delete existing state for this child
        with datastore.session_scope() as session:
            deleted = (
                session.query(ChildCapabilityStateModel)
                .filter(ChildCapabilityStateModel.child_id == child_id)
                .delete(synchronize_session=False)
            )
        deleted_n = int(deleted or 0)
        if deleted_n:
            logger.debug(
                "Capability state: deleted %d existing rows for child_id=%s",
                deleted_n,
                child_id,
            )

        # Seed: insert one row per item with zero values
        inserted = 0
        with datastore.session_scope() as session:
            for item in items:
                item_id = _item_attr(item, "id", "") or _item_attr(item, "item_id", "")
                item_id = str(item_id).strip() if item_id else ""
                if not item_id:
                    continue
                session.add(
                    ChildCapabilityStateModel(
                        id=str(uuid.uuid4()),
                        child_id=child_id,
                        item_id=item_id,
                        item_version=int(_item_attr(item, "version", 1) or 1),
                        framework=str(_item_attr(item, "framework", "") or ""),
                        domain=str(_item_attr(item, "domain", "") or ""),
                        subdomain=str(_item_attr(item, "subdomain", "") or ""),
                        current_status="not_observed",
                        confidence=0.0,
                        mastery_score=0.0,
                        evidence_count=0,
                        first_observed_at=None,
                        last_observed_at=None,
                        last_session_id=None,
                    )
                )
                inserted += 1

        logger.info(
            "Capability state: seeded %d items for new child_id=%s",
            inserted,
            child_id,
        )
    except Exception as e:
        logger.warning(
            "Capability state seeding failed for child_id=%s: %s",
            child_id,
            e,
            exc_info=True,
        )
