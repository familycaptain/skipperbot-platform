"""Lists — data layer (SQL CRUD).

Owns reads + writes for the ``app_lists.lists`` and ``app_lists.list_items``
tables. This is the low-level persistence layer; higher-level business
logic (rendering, alias resolution, Trello sync coordination) lives in
``apps/lists/store.py``.

Every public mutation calls ``platform.memory.digest_record`` so the
records are searchable from chat — see ``specs/MEMORY.md`` for why this
is non-negotiable.

Ported from ``data_layer/lists.py`` for sub-chunk 4c. Functionally
identical; only difference is routing all queries through the
``*_in_schema`` helpers from ``app_platform.db`` so the lists app's
tables land in (and read from) the ``app_lists`` schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from psycopg2.extras import Json

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record
from data_layer.links import ensure_edge, delete_links_for_entity  # platform infra — links live in public.*


logger = logging.getLogger(__name__)

SCHEMA = "app_lists"


# ---------------------------------------------------------------------------
# Memory-digestion hints — what the dumb-model fact extractor should focus on
# when ingesting a list / list_item record into searchable memories.
# See specs/MEMORY.md.
# ---------------------------------------------------------------------------

_LIST_HINT = (
    "Focus on: the list's name and aliases. Lists are how chat recalls which "
    "ordered collection the user means when they say 'add it to the shopping list'."
)

_ITEM_HINT = (
    "Focus on: the item text and which list it belongs to. Used by chat to "
    "identify 'that thing on my list'."
)


# ---------------------------------------------------------------------------
# Backfill registry — read by scripts/backfill_app_memories.py to walk every
# stored row and re-digest it (useful after first install or schema changes).
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES = [
    {
        "entity_type": "list",
        "list_fn": lambda: get_all_lists(),
        "context_hint": _LIST_HINT,
    },
    {
        "entity_type": "list_item",
        "list_fn": lambda: _all_items(),
        "context_hint": _ITEM_HINT,
    },
]


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

def save_list(lst: dict):
    """Insert or update a list. Memorializes the list's IDENTITY (name/aliases) only on
    create or a real rename — NOT on every item/sync save (item changes are memorialized
    per-item), which previously re-created duplicate "X is a list named Y" memories."""
    prior = get_list_row(lst["id"])
    is_new = prior is None
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lists (id, name, aliases, trello, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    aliases = EXCLUDED.aliases,
                    trello = EXCLUDED.trello
                """,
                (
                    lst["id"],
                    lst["name"],
                    lst.get("aliases", []),
                    Json(lst.get("trello")) if lst.get("trello") else None,
                    lst.get("created_by", ""),
                    lst.get("created_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
        conn.commit()
    saved = get_list(lst["id"])
    identity_changed = is_new or (prior or {}).get("name") != lst.get("name") or \
        sorted((prior or {}).get("aliases") or []) != sorted(lst.get("aliases") or [])
    if saved and identity_changed:
        digest_record(
            app_id="lists",
            entity_type="list",
            action="created" if is_new else "updated",
            entity_id=lst["id"],
            record=saved,
            by=lst.get("created_by", ""),
            context_hint=_LIST_HINT,
        )


def get_list_row(list_id: str) -> dict | None:
    """Return the raw lists row (no items expanded)."""
    return fetch_one_in_schema(SCHEMA, "SELECT * FROM lists WHERE id = %s", (list_id,))


def get_list(list_id: str) -> dict | None:
    """Get a list by ID, including its items."""
    row = get_list_row(list_id)
    return _list_row_to_dict(row) if row else None


def get_all_lists() -> list[dict]:
    """Get all lists with their items."""
    rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM lists ORDER BY name")
    return [_list_row_to_dict(r) for r in rows]


def delete_list(list_id: str) -> bool:
    """Delete a list and its items (CASCADE). Fires a digest_record."""
    existing = get_list(list_id)
    count = execute_in_schema(SCHEMA, "DELETE FROM lists WHERE id = %s", (list_id,))
    ok = count > 0
    if ok and existing:
        digest_record(
            app_id="lists",
            entity_type="list",
            action="deleted",
            entity_id=list_id,
            record=existing,
            by="",
        )
    return ok


# ---------------------------------------------------------------------------
# List Items
# ---------------------------------------------------------------------------

def add_item(list_id: str, item: dict):
    """Add an item to a list. Fires a digest_record + links edge."""
    is_new = get_item(item["id"]) is None
    # Get next position
    row = fetch_one_in_schema(
        SCHEMA,
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM list_items WHERE list_id = %s",
        (list_id,),
    )
    pos = row["next_pos"] if row else 0

    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO list_items (id, list_id, text, position, archived,
                                        trello_card_id, added_by, added_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    text = EXCLUDED.text,
                    position = EXCLUDED.position,
                    archived = EXCLUDED.archived,
                    trello_card_id = EXCLUDED.trello_card_id
                """,
                (
                    item["id"],
                    list_id,
                    item.get("text", ""),
                    item.get("position", pos),
                    item.get("archived", False),
                    item.get("trello_card_id", ""),
                    item.get("added_by", ""),
                    item.get("added_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
        conn.commit()
    ensure_edge(item["id"], list_id, "child_of", "parent_of")
    saved = get_item(item["id"])
    if saved:
        digest_record(
            app_id="lists",
            entity_type="list_item",
            action="created" if is_new else "updated",
            entity_id=item["id"],
            record=saved,
            by=item.get("added_by", ""),
            context_hint=_ITEM_HINT,
        )


def remove_item(item_id: str) -> bool:
    """Remove a list item by ID. Fires a digest_record."""
    existing = get_item(item_id)
    delete_links_for_entity(item_id)
    count = execute_in_schema(SCHEMA, "DELETE FROM list_items WHERE id = %s", (item_id,))
    ok = count > 0
    if ok and existing:
        digest_record(
            app_id="lists",
            entity_type="list_item",
            action="deleted",
            entity_id=item_id,
            record=existing,
            by="",
        )
    return ok


def archive_item(item_id: str) -> bool:
    """Archive a list item. Fires a digest_record."""
    count = execute_in_schema(
        SCHEMA,
        "UPDATE list_items SET archived = TRUE, archived_at = now() WHERE id = %s",
        (item_id,),
    )
    ok = count > 0
    if ok:
        saved = get_item(item_id)
        if saved:
            digest_record(
                app_id="lists",
                entity_type="list_item",
                action="updated",
                entity_id=item_id,
                record=saved,
                by="",
                context_hint=_ITEM_HINT,
            )
    return ok


def get_item(item_id: str) -> dict | None:
    """Get a single list item by ID."""
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM list_items WHERE id = %s", (item_id,))
    return _item_row_to_dict(row) if row else None


def get_items(list_id: str, include_archived: bool = False) -> list[dict]:
    """Get all items for a list."""
    if include_archived:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM list_items WHERE list_id = %s ORDER BY position",
            (list_id,),
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM list_items WHERE list_id = %s AND archived = FALSE ORDER BY position",
            (list_id,),
        )
    return [_item_row_to_dict(r) for r in rows]


def batch_reorder(list_id: str, item_ids: list[str]) -> bool:
    """Reorder active items in a list by setting positions from the ordered ID list."""
    with scoped_conn(SCHEMA) as conn:
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
    new_ids = {item["id"] for item in items}
    old_rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT id FROM list_items WHERE list_id = %s",
        (list_id,),
    )
    stale_ids = [r["id"] for r in old_rows if r["id"] not in new_ids]
    for stale_id in stale_ids:
        delete_links_for_entity(stale_id)

    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM list_items WHERE list_id = %s", (list_id,))
            for pos, item in enumerate(items):
                cur.execute(
                    """
                    INSERT INTO list_items (id, list_id, text, position, archived,
                                            archived_at, trello_card_id, added_by, added_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item["id"],
                        list_id,
                        item.get("text", ""),
                        pos,
                        item.get("archived", False),
                        item.get("archived_at") or None,
                        item.get("trello_card_id", ""),
                        item.get("added_by", ""),
                        item.get("added_at", datetime.now(timezone.utc).isoformat()),
                    ),
                )
        conn.commit()
    for item in items:
        ensure_edge(item["id"], list_id, "child_of", "parent_of")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_row_to_dict(row: dict) -> dict:
    """Convert a lists row + its items to the dict shape store.py expects."""
    items = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM list_items WHERE list_id = %s ORDER BY position",
        (row["id"],),
    )
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


def _all_items() -> list[dict]:
    """All items across all lists. Used by BACKFILL_ENTITIES."""
    rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM list_items ORDER BY list_id, position")
    return [_item_row_to_dict(r) for r in rows]
