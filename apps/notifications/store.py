"""Notifications — business logic.

The single public entry point that every other app calls is
``create_notification(...)`` — usually via the
``app_platform.notifications.create_notification`` shim so apps don't
have to import this module directly. It generates the ``n-*`` id, fires
``digest_record``, calls ``log_entity_change`` for the platform's
auto-memory, and inserts the row via ``apps.notifications.data``.

Also exposes formatting + history helpers for the
``get_recent_notifications`` MCP tool and the desktop Notifications app.

Ported from ``notification_store.py`` for sub-chunk 6c-part-2.
Functionally identical; only difference is routing all persistence
through ``apps.notifications.data`` instead of ``data_layer.notifications``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from config import logger
from app_platform.time import get_timezone


class _SkipShadow(Exception):
    """Marker: a consciousness-originated notification is transport, not a new event."""
from auto_memory import log_entity_change
from app_platform.memory import digest_record
from apps.notifications import data as _dl_notif


_NOTIFICATION_HINT = (
    "Focus on: recipient, the message delivered, source type (reminder/job/system/agent), "
    "delivery channel (discord/pushover/chat), and whether delivery succeeded."
)


def _now_iso() -> str:
    return datetime.now(get_timezone()).isoformat()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_notification(
    recipient: str,
    message: str,
    source_type: str = "",
    source_id: str = "",
    channel: str = "",
    delivered: bool = False,
) -> dict:
    """Create a notification record.

    Args:
        recipient: Who this was delivered to (person name).
        message: The notification content.
        source_type: What triggered it ("reminder", "job", "system", "agent").
        source_id: Entity ID of the trigger (e.g. "r-abc123", "j-def456").
        channel: Delivery channel ("discord", "pushover", "chat", "both").
        delivered: Whether delivery succeeded.

    Returns:
        The notification record.
    """
    clean_recipient = recipient.lower().strip()
    if not clean_recipient:
        logger.debug("NOTIFICATION: Skipped — empty recipient")
        return {}
    from data_layer.users import get_user
    if not get_user(clean_recipient):
        logger.debug("NOTIFICATION: Skipped — recipient %r is not a known user", clean_recipient)
        return {}

    notif = {
        "id": f"n-{uuid.uuid4().hex[:8]}",
        "recipient": clean_recipient,
        "message": message,
        "source_type": source_type.strip() if source_type else "",
        "source_id": source_id.strip() if source_id else "",
        "channel": channel.strip() if channel else "",
        "delivered": delivered,
        "created_at": _now_iso(),
    }
    _dl_notif.save_notification(notif)
    logger.info(
        "NOTIFICATION: Created %s for %s via %s",
        notif["id"], recipient, channel or "unknown",
    )

    # Phase-0 SHADOW WRITE (specs/CONSCIOUSNESS.md §13): every proactive message
    # mirrors into the consciousness log HERE — the one sanctioned entry point.
    # delivery.py's chat-history write is deliberately NOT hooked (it would
    # double-log this same message). Pre-attended: the legacy pipeline is still
    # the engaged responder during the shadow period.
    try:
        from app_platform.consciousness import shadow_log_event, domain_for_source_type
        if source_type == "consciousness":
            raise _SkipShadow()  # the cl- row already exists; this notification IS its transport
        shadow_log_event(
            kind="message", who_from="skipper", who_to=clean_recipient,
            domain=domain_for_source_type(notif["source_type"]),
            content=message,
            subject_id=notif["source_id"] or None,
            payload={"notification_id": notif["id"], "source_type": notif["source_type"]},
            pre_attended_by="legacy-pipeline",
        )
    except _SkipShadow:
        pass
    except Exception:
        logger.debug("CONSCIOUSNESS: notification shadow write skipped", exc_info=True)

    log_entity_change(
        "created", notif["id"], "notification",
        f"To {recipient}: {message[:80]}",
        related_entities=[source_id] if source_id else [],
    )
    digest_record(
        app_id="notifications",
        entity_type="notification",
        action="created",
        entity_id=notif["id"],
        record=notif,
        by=recipient,
        context_hint=_NOTIFICATION_HINT,
    )
    return notif


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def get_notifications(
    recipient: Optional[str] = None,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Get recent notifications, optionally filtered.

    Args:
        recipient: Filter by recipient.
        source_type: Filter by source type (e.g. "reminder", "job").
        source_id: Filter by source entity ID.
        limit: Max results (most recent first).

    Returns:
        List of notification records.
    """
    # Filter by source_type/source_id in the QUERY (server-side) BEFORE LIMIT, so a
    # small limit reliably returns the matching row (issue #43 — the old path limited
    # the raw fetch first, then filtered in Python, so limit=1 missed the row).
    if recipient:
        all_notifs = _dl_notif.get_notifications_for_user(
            recipient.lower().strip(), limit=limit,
            source_type=source_type, source_id=source_id,
        )
    else:
        all_notifs = _dl_notif.get_all_notifications(
            limit=limit, source_type=source_type, source_id=source_id,
        )

    return all_notifs[:limit]


def format_notifications(notifs: list[dict]) -> str:
    """Format notifications for display."""
    if not notifs:
        return "No notifications found."

    lines = [f"Notifications ({len(notifs)}):"]
    for n in notifs:
        ts = n.get("created_at", "")[:16]
        source = ""
        if n.get("source_type"):
            source = f" [{n['source_type']}"
            if n.get("source_id"):
                source += f":{n['source_id']}"
            source += "]"
        channel = f" via {n['channel']}" if n.get("channel") else ""
        status = "" if n.get("delivered", True) else " (FAILED)"
        lines.append(
            f"  [{n['id']}] {ts} → {n['recipient']}: {n['message']}{source}{channel}{status}"
        )
    return "\n".join(lines)
