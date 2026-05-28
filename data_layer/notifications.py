"""Notifications — Postgres CRUD
================================
Drop-in replacement for notification_store.py's flat-file persistence.
"""

import logging
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)


def save_notification(n: dict):
    """Insert or update a notification."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO notifications (id, recipient, message, source_type,
                                           source_id, channel, delivered, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    delivered = EXCLUDED.delivered
            """, (
                n["id"], n.get("recipient", ""), n["message"],
                n.get("source_type", ""), n.get("source_id", ""),
                n.get("channel", ""), n.get("delivered", True),
                n.get("created_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()


def get_notification(notif_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM notifications WHERE id = %s", (notif_id,))
    return _row(row) if row else None


def get_all_notifications(limit: int = 10000) -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM notifications ORDER BY created_at DESC LIMIT %s", (limit,)
    )]


def get_notifications_for_user(recipient: str, limit: int = 50) -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM notifications WHERE recipient = %s ORDER BY created_at DESC LIMIT %s",
        (recipient, limit),
    )]


def get_undelivered(recipient: str) -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM notifications WHERE recipient = %s AND delivered = FALSE ORDER BY created_at",
        (recipient,),
    )]


def get_all_undelivered(limit: int = 50, max_age_minutes: int = 5) -> list[dict]:
    """Get all undelivered notifications across all recipients, oldest first.

    Only returns notifications created within max_age_minutes to avoid delivering
    stale backlog. Older undelivered notifications are silently marked delivered.
    The 30s scheduler loop means notifications are normally picked up within a minute,
    so a 5-minute window is generous.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    # Mark stale undelivered notifications as delivered (skip them)
    execute(
        "UPDATE notifications SET delivered = TRUE WHERE delivered = FALSE AND created_at < %s",
        (cutoff,),
    )

    return [_row(r) for r in fetch_all(
        "SELECT * FROM notifications WHERE delivered = FALSE AND created_at >= %s ORDER BY created_at ASC LIMIT %s",
        (cutoff, limit),
    )]


def mark_delivered(notif_id: str) -> bool:
    return execute("UPDATE notifications SET delivered = TRUE WHERE id = %s", (notif_id,)) > 0


def delete_notification(notif_id: str) -> bool:
    return execute("DELETE FROM notifications WHERE id = %s", (notif_id,)) > 0


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "recipient": row.get("recipient") or "",
        "message": row["message"],
        "source_type": row.get("source_type") or "",
        "source_id": row.get("source_id") or "",
        "channel": row.get("channel") or "",
        "delivered": row.get("delivered", True),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
