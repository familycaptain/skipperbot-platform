"""Notification Store
====================
First-class notification records (n-* IDs).
A notification is created whenever the system delivers something to a user —
from a reminder firing, a job completing, or a system event.

Backed by Postgres via data_layer.notifications.
"""

import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE
from auto_memory import log_entity_change
from app_platform.memory import digest_record
import data_layer.notifications as _dl_notif

_NOTIFICATION_HINT = (
    "Focus on: recipient, the message delivered, source type (reminder/job/system/agent), "
    "delivery channel (discord/pushover/chat), and whether delivery succeeded."
)

CENTRAL_TZ = ZoneInfo(TIMEZONE)


def _now_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


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
    logger.info("NOTIFICATION: Created %s for %s via %s", notif["id"], recipient, channel or "unknown")

    log_entity_change("created", notif["id"], "notification",
                      f"To {recipient}: {message[:80]}",
                      related_entities=[source_id] if source_id else [])
    digest_record(app_id="notifications", entity_type="notification", action="created",
                  entity_id=notif["id"], record=notif,
                  by=recipient, context_hint=_NOTIFICATION_HINT)
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
    if recipient:
        all_notifs = _dl_notif.get_notifications_for_user(recipient.lower().strip(), limit=limit)
    else:
        from data_layer.db import fetch_all
        all_notifs = [_notif_row(r) for r in fetch_all(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT %s", (limit,))]

    if source_type:
        st = source_type.strip().lower()
        all_notifs = [n for n in all_notifs if n.get("source_type", "").lower() == st]
    if source_id:
        sid = source_id.strip()
        all_notifs = [n for n in all_notifs if n.get("source_id") == sid]

    return all_notifs[:limit]


def _notif_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "recipient": row.get("recipient") or "",
        "message": row["message"],
        "source_type": row.get("source_type") or "",
        "source_id": row.get("source_id") or "",
        "channel": row.get("channel") or "",
        "delivered": row.get("delivered", True),
        "created_at": row["created_at"].isoformat() if hasattr(row.get("created_at", ""), 'isoformat') else row.get("created_at", ""),
    }


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
        lines.append(f"  [{n['id']}] {ts} → {n['recipient']}: {n['message']}{source}{channel}{status}")
    return "\n".join(lines)
