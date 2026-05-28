"""To-Do Config — per-user default list + nudge settings
========================================================
Thin layer over todo_config table + list_store for item ops.
"""

import logging
from datetime import datetime, timezone

from data_layer.db import fetch_one, fetch_all, execute, get_conn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------

def get_config(user_id: str) -> dict | None:
    """Get to-do config for a user.  Returns None if not configured yet."""
    row = fetch_one("SELECT * FROM todo_config WHERE user_id = %s", (user_id,))
    if not row:
        return None
    return _config_row(row)


def upsert_config(user_id: str, **kwargs) -> dict:
    """Create or update to-do config.  Only supplied kwargs are updated."""
    allowed = {"default_list_id", "backlog_list_id", "nudge_enabled", "nudge_day", "nudge_time", "show_on_calendar"}
    nullable = {"default_list_id", "backlog_list_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and (v is not None or k in nullable)}

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
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO todo_config ({col_str}) VALUES ({placeholders})", vals)
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
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE todo_config SET {', '.join(set_parts)} WHERE user_id = %s",
                    vals,
                )
            conn.commit()

    return get_config(user_id)


def get_all_configs() -> list[dict]:
    """Get all to-do configs (for nudge delivery)."""
    rows = fetch_all("SELECT * FROM todo_config ORDER BY user_id")
    return [_config_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Convenience: resolve user's default list + items
# ---------------------------------------------------------------------------

def get_todo_items(user_id: str, include_archived: bool = False) -> dict | None:
    """Get the user's default to-do list with items.
    Returns {config, list, items} or None if no config/list.
    """
    cfg = get_config(user_id)
    if not cfg or not cfg["default_list_id"]:
        return None

    from data_layer.lists import get_list, get_items
    lst = get_list(cfg["default_list_id"])
    if not lst:
        return None

    items = get_items(cfg["default_list_id"], include_archived=include_archived)
    return {
        "config": cfg,
        "list_id": lst["id"],
        "list_name": lst["name"],
        "items": items,
        "count": len([i for i in items if not i.get("archived")]),
    }


def get_backlog_items(user_id: str, include_archived: bool = False) -> dict | None:
    """Get the user's backlog list with items.
    Returns {config, list_id, list_name, items, count} or None if no backlog configured.
    """
    cfg = get_config(user_id)
    if not cfg or not cfg.get("backlog_list_id"):
        return None

    from data_layer.lists import get_list, get_items
    lst = get_list(cfg["backlog_list_id"])
    if not lst:
        return None

    items = get_items(cfg["backlog_list_id"], include_archived=include_archived)
    return {
        "config": cfg,
        "list_id": lst["id"],
        "list_name": lst["name"],
        "items": items,
        "count": len([i for i in items if not i.get("archived")]),
    }


def move_item_between_lists(item_id: str, from_list_id: str, to_list_id: str) -> bool:
    """Move a list item from one list to another.
    Puts it at position 0 (top) in the destination list.
    """
    from data_layer.db import get_conn, fetch_one
    from data_layer.links import ensure_edge, delete_links_for_entity

    row = fetch_one("SELECT * FROM list_items WHERE id = %s AND list_id = %s", (item_id, from_list_id))
    if not row:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Shift existing items in destination list down
            cur.execute(
                "UPDATE list_items SET position = position + 1 WHERE list_id = %s AND archived = FALSE",
                (to_list_id,),
            )
            # Move the item
            cur.execute(
                "UPDATE list_items SET list_id = %s, position = 0 WHERE id = %s",
                (to_list_id, item_id),
            )
        conn.commit()

    # Update link edges
    delete_links_for_entity(item_id)
    ensure_edge(item_id, to_list_id, "child_of", "parent_of")
    return True


def ensure_default_list(user_id: str, display_name: str = "") -> dict:
    """Ensure user has a default to-do list.  Creates one if needed.
    Returns the config dict.
    """
    cfg = get_config(user_id)
    if cfg and cfg["default_list_id"]:
        # Verify the list still exists
        from data_layer.lists import get_list
        if get_list(cfg["default_list_id"]):
            return cfg

    # Create a new list
    from list_store import create_list
    name = f"{display_name or user_id.title()}'s To-Do"
    lst = create_list(name=name, created_by=user_id)

    return upsert_config(user_id, default_list_id=lst["id"])


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
