"""Auto-Memory Integration
=========================
Lightweight helper that logs m-* memory entries on entity CRUD operations.
Called by goal_store, reminder_store, artifact_store, etc.
"""

import os

from config import logger


def _entity_name(entity_id: str) -> str:
    """The entity's human name (name/title) via the platform's entity registry, or ''.

    Never raises: an unknown prefix, a deleted row or a DB hiccup just means no name."""
    try:
        prefix = (entity_id or "").split("-", 1)[0]
        if not prefix or prefix == entity_id:
            return ""
        from app_platform.entities import get_entity
        row = get_entity(prefix, entity_id) or {}
        for field in ("name", "title"):
            value = row.get(field)
            if value:
                return " ".join(str(value).split())[:120]
    except Exception:
        pass
    return ""


def log_entity_change(
    action: str,
    entity_id: str,
    entity_type: str,
    summary: str,
    by: str = "",
    related_entities: list[str] | None = None,
    tags: list[str] | None = None,
):
    """Create a memory entry for an entity CRUD operation.

    Args:
        action: "created", "updated", "deleted", "status_changed", etc.
        entity_id: The entity's ID (e.g. "g-abc123").
        entity_type: Human label ("goal", "project", "task", "reminder", etc.).
        summary: One-line description of what happened.
        by: Who performed the action.
        related_entities: Other entity IDs involved.
        tags: Extra tags beyond the auto-generated ones.
    """
    try:
        # Late import to avoid circular dependencies
        from memory_store import save_memory

        auto_tags = [entity_type, action, "auto"]
        if tags:
            auto_tags.extend(tags)

        # Name the thing. "[updated] task t-30ec504d: Status: not_started → cancelled" can
        # never be recalled by asking about the task — the words people use are in its
        # title, not its id. The id stays (recall by entity still works), the name goes
        # beside it unless the summary already carries it.
        name = _entity_name(entity_id)
        if name and name not in summary:
            content = f"[{action}] {entity_type} '{name}' ({entity_id}): {summary}"
        else:
            content = f"[{action}] {entity_type} {entity_id}: {summary}"

        # Pick up the chat turn ID injected by chat.py → mcp_client env var
        source_chat_id = os.environ.get("SKIPPERBOT_CHAT_TURN_ID", "")

        save_memory(
            content=content,
            tags=auto_tags,
            about=entity_id,
            saved_by=by or "system",
            related_entities=related_entities or [],
            source_chat_id=source_chat_id,
        )
    except Exception as e:
        # Never let memory logging break the caller
        logger.error("AUTO_MEMORY: Failed to log %s on %s: %s", action, entity_id, e)

    # Record observation in skipper_state for PM-relevant entity types
    # The PM check-in cycles review these to detect changes between scrums
    if entity_type in ("goal", "project", "task") and action in ("created", "updated", "deleted"):
        try:
            from data_layer.skipper_state import create_state
            import json
            create_state(
                domain="pm",
                state_type="observation",
                subject_id=entity_id,
                subject_type=entity_type,
                content=json.dumps({
                    "action": action,
                    "summary": summary[:500],
                    "by": by or "system",
                    "related_entities": related_entities or [],
                }),
                priority="low",
            )
        except Exception as e2:
            logger.debug("AUTO_MEMORY: Failed to record observation for %s: %s", entity_id, e2)
