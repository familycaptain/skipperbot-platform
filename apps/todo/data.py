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


def claim_default_list(user_id, create_list_fn, resolve_list_fn, name):
    """Atomically get-or-create the user's default to-do list (concurrency-safe).

    The To-Do UI fires ``/config`` and ``/items`` on first open, and both call
    ``ensure_default_list`` in separate threads; a plain read-check-then-create
    races and produces TWO ``"<user>'s To-Do"`` lists. This serializes the
    bootstrap with a per-user, *transaction-scoped* Postgres advisory lock so N
    concurrent callers create EXACTLY ONE list: the winner creates it and
    publishes the pointer; every loser blocks on the lock, then re-reads the
    now-committed ``default_list_id`` and reuses it.

    The two cross-app operations are **injected** as callables so this module
    imports nothing from ``apps.lists`` (keeps the one-directional dependency —
    ``store.py`` supplies ``apps.lists.store.create_list`` and
    ``apps.lists.data.get_list``):

    * ``create_list_fn(name=, created_by=)`` -> the created list dict (``["id"]``)
    * ``resolve_list_fn(list_id)`` -> truthy iff that list still exists

    Only reached on a *miss* (the caller's fast path already handled the common
    case where the config points at a live list). Returns the config dict.
    """
    import psycopg2
    import psycopg2.extras

    try:
        with scoped_conn(SCHEMA) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Bound the wait so a stalled winner can't park pooled connections
                # indefinitely (the platform shares a small connection pool).
                cur.execute("SET LOCAL lock_timeout = '3s'")
                # Serialize this user's bootstrappers. hashtext() over a BOUND
                # param (never string-formatted) keys the lock per user; the
                # xact-scoped variant auto-releases at COMMIT/ROLLBACK, so no
                # lock leaks across pooled-connection reuse.
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('todo-default:' || %s))",
                    (user_id,),
                )
                # Guarantee a config row exists so the pointer write is a plain UPDATE.
                cur.execute(
                    "INSERT INTO todo_config (user_id) VALUES (%s) "
                    "ON CONFLICT (user_id) DO NOTHING",
                    (user_id,),
                )
                # Re-check UNDER the lock: a race loser sees the winner's pointer here.
                cur.execute(
                    "SELECT default_list_id FROM todo_config WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                existing = (row or {}).get("default_list_id")

            if existing and resolve_list_fn(existing):
                conn.commit()  # release the advisory lock; nothing to create
                return get_config(user_id)

            # Winner only. create_list_fn runs on its OWN connection/commit
            # (the lists app's write-through path); we never raw-SQL app_lists.
            lst = create_list_fn(name=name, created_by=user_id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE todo_config SET default_list_id = %s, updated_at = now() "
                    "WHERE user_id = %s",
                    (lst["id"], user_id),
                )
            conn.commit()  # publishes the pointer AND releases the lock atomically
        return get_config(user_id)

    except psycopg2.errors.LockNotAvailable:
        # A concurrent bootstrap is mid-flight and held the lock past lock_timeout
        # (e.g. a slow create_list). It has almost certainly committed the pointer
        # by now — re-read and reuse it rather than double-create or crash first-load.
        cfg = get_config(user_id)
        if cfg and cfg["default_list_id"] and resolve_list_fn(cfg["default_list_id"]):
            return cfg
        # Still unresolved: surface a retryable miss (the next poll hits the fast path).
        raise RuntimeError(
            f"todo default-list bootstrap for {user_id!r} is contended; retry"
        )


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
