"""Notifications — data layer (SQL CRUD).

Owns reads + writes for the ``app_notifications.notifications`` table.
This is the low-level persistence layer; higher-level business logic
(create_notification with id-generation + digest_record + default
channel resolution, formatting helpers) lives in
``apps/notifications/store.py``.

Ported from ``data_layer/notifications.py`` for sub-chunk 6c-part-1.
Functionally identical; only difference is routing all queries through
the ``*_in_schema`` helpers from ``app_platform.db`` so the
notifications app's table lands in (and reads from) the
``app_notifications`` schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone


from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)


logger = logging.getLogger(__name__)

SCHEMA = "app_notifications"


# ---------------------------------------------------------------------------
# Memory-digestion hint
# ---------------------------------------------------------------------------

_NOTIF_HINT = (
    "Focus on: the recipient, the message text, and the channel that was "
    "(or will be) used to deliver it. Notifications are how chat answers "
    "'did Skipper tell me about X?'."
)


# ---------------------------------------------------------------------------
# Backfill registry
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES = [
    {
        "entity_type": "notification",
        "list_fn": lambda: get_all_notifications(),
        "context_hint": _NOTIF_HINT,
    },
]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_notification(n: dict):
    """Insert or update a notification.

    On conflict only the ``delivered`` flag is updated — same as the
    source behavior — so re-saving the same id repeatedly never
    overwrites the message/recipient/etc.
    """
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notifications (id, recipient, message, source_type,
                                           source_id, channel, delivered, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    delivered = EXCLUDED.delivered
                """,
                (
                    n["id"],
                    n.get("recipient", ""),
                    n["message"],
                    n.get("source_type", ""),
                    n.get("source_id", ""),
                    n.get("channel", ""),
                    n.get("delivered", True),
                    n.get("created_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
        conn.commit()


def get_notification(notif_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM notifications WHERE id = %s", (notif_id,))
    return _row(row) if row else None


def get_all_notifications(limit: int = 10000) -> list[dict]:
    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
    ]


def get_notifications_for_user(recipient: str, limit: int = 50) -> list[dict]:
    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM notifications WHERE recipient = %s ORDER BY created_at DESC LIMIT %s",
            (recipient, limit),
        )
    ]


def get_undelivered(recipient: str) -> list[dict]:
    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM notifications WHERE recipient = %s AND delivered = FALSE ORDER BY created_at",
            (recipient,),
        )
    ]


def get_all_undelivered(limit: int = 50, max_age_minutes: int = 5) -> list[dict]:
    """Get all undelivered notifications across all recipients, oldest first.

    Only returns notifications created within ``max_age_minutes`` to
    avoid delivering stale backlog. Older undelivered notifications are
    silently marked delivered. The 30s scheduler loop means
    notifications are normally picked up within a minute, so a 5-minute
    window is generous.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    # Mark stale undelivered notifications as delivered (skip them).
    execute_in_schema(
        SCHEMA,
        "UPDATE notifications SET delivered = TRUE WHERE delivered = FALSE AND created_at < %s",
        (cutoff,),
    )

    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM notifications WHERE delivered = FALSE AND created_at >= %s ORDER BY created_at ASC LIMIT %s",
            (cutoff, limit),
        )
    ]


def mark_delivered(notif_id: str) -> bool:
    return execute_in_schema(
        SCHEMA,
        "UPDATE notifications SET delivered = TRUE WHERE id = %s",
        (notif_id,),
    ) > 0


def delete_notification(notif_id: str) -> bool:
    return execute_in_schema(
        SCHEMA,
        "DELETE FROM notifications WHERE id = %s",
        (notif_id,),
    ) > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pushover per-user opt-in
# ---------------------------------------------------------------------------
# The shared Pushover application token is an app-config secret
# (app:notifications / pushover_app_token). Each user opts in here with their
# own Pushover user key, stored encrypted in app_notifications.pushover_subscriptions.

def app_token() -> str:
    """The shared Pushover application token (admin-set, encrypted)."""
    from app_platform import settings as _settings
    return _settings.get("pushover_app_token", scope="app:notifications", secret=True, default="") or ""


def get_pushover_status(user_id: str) -> dict:
    """UI-safe status for a user — never returns the actual user key."""
    row = fetch_one_in_schema(
        SCHEMA, "SELECT user_key, device, enabled FROM pushover_subscriptions WHERE user_id = %s",
        (user_id.lower().strip(),),
    )
    return {
        "app_token_configured": bool(app_token()),
        "configured": bool(row and row.get("user_key")),
        "enabled": bool(row and row.get("enabled")),
        "device": (row.get("device") if row else "") or "",
    }


def save_pushover_subscription(user_id: str, user_key: str = "", device: str = "",
                               enabled: bool = True) -> None:
    """Upsert a user's Pushover opt-in. A blank user_key keeps the existing one
    (so the UI can toggle enabled / change device without re-entering the key)."""
    from app_platform import secrets as _secrets
    uid = user_id.lower().strip()
    key = (user_key or "").strip()
    enc_key = _secrets.encrypt(key) if key else None  # None → keep existing in COALESCE
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pushover_subscriptions (user_id, user_key, device, enabled, updated_at)
                VALUES (%s, COALESCE(%s, ''), %s, %s, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    user_key = COALESCE(%s, pushover_subscriptions.user_key),
                    device = EXCLUDED.device,
                    enabled = EXCLUDED.enabled,
                    updated_at = now()
                """,
                (uid, enc_key, (device or "").strip(), bool(enabled), enc_key),
            )
        conn.commit()


def delete_pushover_subscription(user_id: str) -> bool:
    return execute_in_schema(
        SCHEMA, "DELETE FROM pushover_subscriptions WHERE user_id = %s",
        (user_id.lower().strip(),),
    ) > 0


def get_pushover_creds(user_id: str) -> dict | None:
    """Resolve send-ready creds for a user, or None if not opted in / disabled /
    no app token. Returns {token, user_key, device} with the key decrypted."""
    token = app_token()
    if not token:
        return None
    row = fetch_one_in_schema(
        SCHEMA, "SELECT user_key, device, enabled FROM pushover_subscriptions WHERE user_id = %s",
        (user_id.lower().strip(),),
    )
    if not row or not row.get("enabled") or not row.get("user_key"):
        return None
    from app_platform import secrets as _secrets
    try:
        user_key = _secrets.decrypt(row["user_key"])
    except _secrets.SecretError:
        return None
    if not user_key:
        return None
    return {"token": token, "user_key": user_key, "device": (row.get("device") or "")}
