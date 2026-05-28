"""Lists + List Items — Postgres CRUD
=====================================
Drop-in replacement for list_store.py's flat-file persistence.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, fetch_all, execute
from data_layer.links import ensure_edge, delete_links_for_entity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

def save_list(lst: dict):
    """Insert or update a list."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lists (id, name, aliases, trello, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    aliases = EXCLUDED.aliases,
                    trello = EXCLUDED.trello
            """, (
                lst["id"], lst["name"], lst.get("aliases", []),
                Json(lst.get("trello")) if lst.get("trello") else None,
                lst.get("created_by", ""),
                lst.get("created_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()


def get_list(list_id: str) -> dict | None:
    """Get a list by ID, including its items."""
    row = fetch_one("SELECT * FROM lists WHERE id = %s", (list_id,))
    if not row:
        return None
    return _list_row_to_dict(row)


def get_all_lists() -> list[dict]:
    """Get all lists with their items."""
    rows = fetch_all("SELECT * FROM lists ORDER BY name")
    return [_list_row_to_dict(r) for r in rows]


def delete_list(list_id: str) -> bool:
    """Delete a list and its items (CASCADE)."""
    return execute("DELETE FROM lists WHERE id = %s", (list_id,)) > 0


# ---------------------------------------------------------------------------
# List Items
# ---------------------------------------------------------------------------

def add_item(list_id: str, item: dict):
    """Add an item to a list."""
    # Get next position
    row = fetch_one(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM list_items WHERE list_id = %s",
        (list_id,),
    )
    pos = row["next_pos"] if row else 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO list_items (id, list_id, text, position, archived, trello_card_id, added_by, added_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    text = EXCLUDED.text,
                    position = EXCLUDED.position,
                    archived = EXCLUDED.archived,
                    trello_card_id = EXCLUDED.trello_card_id
            """, (
                item["id"], list_id, item.get("text", ""),
                item.get("position", pos), item.get("archived", False),
                item.get("trello_card_id", ""), item.get("added_by", ""),
                item.get("added_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()
    ensure_edge(item["id"], list_id, "child_of", "parent_of")


def remove_item(item_id: str) -> bool:
    """Remove a list item by ID."""
    delete_links_for_entity(item_id)
    return execute("DELETE FROM list_items WHERE id = %s", (item_id,)) > 0


def archive_item(item_id: str) -> bool:
    """Archive a list item."""
    return execute("UPDATE list_items SET archived = TRUE, archived_at = now() WHERE id = %s", (item_id,)) > 0


def get_item(item_id: str) -> dict | None:
    """Get a single list item by ID."""
    row = fetch_one("SELECT * FROM list_items WHERE id = %s", (item_id,))
    return _item_row_to_dict(row) if row else None


def get_items(list_id: str, include_archived: bool = False) -> list[dict]:
    """Get all items for a list."""
    if include_archived:
        rows = fetch_all(
            "SELECT * FROM list_items WHERE list_id = %s ORDER BY position", (list_id,))
    else:
        rows = fetch_all(
            "SELECT * FROM list_items WHERE list_id = %s AND archived = FALSE ORDER BY position",
            (list_id,),
        )
    return [_item_row_to_dict(r) for r in rows]


def batch_reorder(list_id: str, item_ids: list[str]) -> bool:
    """Reorder active items in a list by setting positions from the ordered ID list."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for pos, iid in enumerate(item_ids):
                cur.execute(
                    "UPDATE list_items SET position = %s WHERE id = %s AND list_id = %s",
                    (pos, iid, list_id),
                )
        conn.commit()
    return True


def replace_items(list_id: str, items: list[dict]):
    """Replace all items in a list (used by Trello sync)."""
    # Collect old item IDs so we can clean up their link rows
    new_ids = {item["id"] for item in items}
    old_rows = fetch_all(
        "SELECT id FROM list_items WHERE list_id = %s", (list_id,))
    stale_ids = [r["id"] for r in old_rows if r["id"] not in new_ids]
    for stale_id in stale_ids:
        delete_links_for_entity(stale_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM list_items WHERE list_id = %s", (list_id,))
            for pos, item in enumerate(items):
                cur.execute("""
                    INSERT INTO list_items (id, list_id, text, position, archived,
                                            archived_at, trello_card_id, added_by, added_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    item["id"], list_id, item.get("text", ""),
                    pos, item.get("archived", False),
                    item.get("archived_at") or None,
                    item.get("trello_card_id", ""), item.get("added_by", ""),
                    item.get("added_at", datetime.now(timezone.utc).isoformat()),
                ))
        conn.commit()
    for item in items:
        ensure_edge(item["id"], list_id, "child_of", "parent_of")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_row_to_dict(row: dict) -> dict:
    """Convert a lists row + its items to the dict shape list_store expects."""
    items = fetch_all(
        "SELECT * FROM list_items WHERE list_id = %s ORDER BY position", (row["id"],))
    return {
        "id": row["id"],
        "name": row["name"],
        "aliases": row.get("aliases") or [],
        "trello": row.get("trello"),
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "items": [_item_row_to_dict(i) for i in items],
    }


def _item_row_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "text": row.get("text") or "",
        "added_by": row.get("added_by") or "",
        "added_at": row["added_at"].isoformat() if row.get("added_at") else "",
        "archived": row.get("archived", False),
        "archived_at": row["archived_at"].isoformat() if row.get("archived_at") else "",
        "trello_card_id": row.get("trello_card_id") or "",
    }
