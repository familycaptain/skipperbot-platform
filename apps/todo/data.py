"""Todo — data layer (SQL CRUD).

Owns reads + writes for the ``app_todo.todo_config`` table (one row per
user). Higher-level operations that need to reach into the underlying
list — ``ensure_default_list`` (creates a list if the user doesn't have
one), ``get_todo_items`` (joins config + list + items) — live in
``apps/todo/store.py``.

Ported from ``data_layer/todo.py`` for sub-chunk 5c-part-1. Functionally
identical; only difference is routing all queries through the
``*_in_schema`` helpers from ``app_platform.db`` so the todo app's
``todo_config`` table lands in (and reads from) the ``app_todo`` schema.

Note: ``digest_record`` is **not** wired here. todo_config is a hidden
per-user settings table, not a user-visible entity, so memory ingestion
would just add noise. The store layer fires events instead.
"""

from __future__ import annotations

import logging

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)


logger = logging.getLogger(__name__)

SCHEMA = "app_todo"


# ---------------------------------------------------------------------------
# Backfill registry — todo has no user-visible entities; nothing to backfill.
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES: list[dict] = []


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------

def get_config(user_id: str) -> dict | None:
    """Get to-do config for a user.  Returns None if not configured yet."""
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM todo_config WHERE user_id = %s", (user_id,)
    )
    if not row:
        return None
    return _config_row(row)


def upsert_config(user_id: str, **kwargs) -> dict:
    """Create or update to-do config.  Only supplied kwargs are updated."""
    allowed = {
        "default_list_id", "backlog_list_id", "nudge_enabled",
        "nudge_day", "nudge_time", "show_on_calendar",
    }
    nullable = {"default_list_id", "backlog_list_id"}
    updates = {
        k: v for k, v in kwargs.items()
        if k in allowed and (v is not None or k in nullable)
    }

    existing = get_config(user_id)
    if existing is None:
        # INSERT
        cols = ["user_id"]
        vals = [user_id]
        for k, v in updates.items():
            cols.append(k)
            vals.append(v)
        placeholders = ", ".join(["%s"] * len(vals))
        col_str = ", ".join(cols)
        with scoped_conn(SCHEMA) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO todo_config ({col_str}) VALUES ({placeholders})",
                    vals,
                )
            conn.commit()
    else:
        # UPDATE
        if not updates:
            return existing
        set_parts = []
        vals = []
        for k, v in updates.items():
            set_parts.append(f"{k} = %s")
            vals.append(v)
        set_parts.append("updated_at = now()")
        vals.append(user_id)
        with scoped_conn(SCHEMA) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE todo_config SET {', '.join(set_parts)} WHERE user_id = %s",
                    vals,
                )
            conn.commit()

    return get_config(user_id)


def get_all_configs() -> list[dict]:
    """Get all to-do configs (for nudge delivery)."""
    rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM todo_config ORDER BY user_id")
    return [_config_row(r) for r in rows]


def delete_config(user_id: str) -> bool:
    """Delete a user's todo config. Used by user cleanup flows."""
    count = execute_in_schema(
        SCHEMA, "DELETE FROM todo_config WHERE user_id = %s", (user_id,)
    )
    return count > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_row(row) -> dict:
    return {
        "user_id": row["user_id"],
        "default_list_id": row.get("default_list_id") or "",
        "backlog_list_id": row.get("backlog_list_id") or "",
        "nudge_enabled": row.get("nudge_enabled", True),
        "nudge_day": row.get("nudge_day") or "saturday",
        "nudge_time": str(row["nudge_time"])[:5] if row.get("nudge_time") else "07:00",
        "show_on_calendar": row.get("show_on_calendar", True),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }
