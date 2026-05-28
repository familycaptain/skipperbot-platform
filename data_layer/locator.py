"""DEPRECATED — Moved to apps/home/data.py (app package).
This file is no longer imported. Safe to delete.

Original: Item Locator — Postgres CRUD
Data layer for located items and item locations.
"""

import logging
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Located Items
# ---------------------------------------------------------------------------

def save_item(item: dict):
    """Insert or update a located item."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO located_items (id, name, description, location, sub_location,
                                           category, tags, quantity, notes,
                                           created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    location = EXCLUDED.location,
                    sub_location = EXCLUDED.sub_location,
                    category = EXCLUDED.category,
                    tags = EXCLUDED.tags,
                    quantity = EXCLUDED.quantity,
                    notes = EXCLUDED.notes,
                    updated_at = EXCLUDED.updated_at
            """, (
                item["id"],
                item.get("name", ""),
                item.get("description", ""),
                item.get("location", ""),
                item.get("sub_location", ""),
                item.get("category", ""),
                item.get("tags", []),
                item.get("quantity"),
                item.get("notes", ""),
                item.get("created_by", ""),
                item.get("created_at", _now()),
                item.get("updated_at", _now()),
            ))
        conn.commit()


def get_item(item_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM located_items WHERE id = %s", (item_id,))
    return _item_row(row) if row else None


def get_all_items() -> list[dict]:
    return [_item_row(r) for r in fetch_all(
        "SELECT * FROM located_items ORDER BY updated_at DESC"
    )]


def search_items(query: str) -> list[dict]:
    """Search items by name, description, location, sub_location, or tags."""
    pattern = f"%{query}%"
    rows = fetch_all(
        """SELECT * FROM located_items
           WHERE name ILIKE %s OR description ILIKE %s
                 OR location ILIKE %s OR sub_location ILIKE %s
                 OR notes ILIKE %s
                 OR array_to_string(tags, ' ') ILIKE %s
           ORDER BY updated_at DESC""",
        (pattern, pattern, pattern, pattern, pattern, pattern),
    )
    return [_item_row(r) for r in rows]


def filter_by_location(location: str) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM located_items WHERE location ILIKE %s ORDER BY updated_at DESC",
        (location,),
    )
    return [_item_row(r) for r in rows]


def filter_by_category(category: str) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM located_items WHERE category ILIKE %s ORDER BY updated_at DESC",
        (category,),
    )
    return [_item_row(r) for r in rows]


def update_item(item_id: str, updates: dict) -> bool:
    """Partial update — only set the provided fields."""
    allowed = {
        "name", "description", "location", "sub_location",
        "category", "tags", "quantity", "notes",
    }
    sets = []
    vals = []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(item_id)
    return execute(
        f"UPDATE located_items SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_item(item_id: str) -> bool:
    return execute("DELETE FROM located_items WHERE id = %s", (item_id,)) > 0


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def get_all_locations() -> list[dict]:
    return [_loc_row(r) for r in fetch_all(
        "SELECT * FROM item_locations ORDER BY sort_order, name"
    )]


def get_all_locations_merged() -> list[dict]:
    """Return locations from the locations table plus any extra names
    found on items that aren't in the table yet."""
    table_locs = get_all_locations()
    known_names = {loc["name"].lower() for loc in table_locs}
    rows = fetch_all(
        "SELECT DISTINCT location AS name FROM located_items WHERE location != '' ORDER BY location"
    )
    extras = []
    for r in rows:
        name = r["name"] if isinstance(r, dict) else r[0]
        if name and name.lower() not in known_names:
            extras.append({"id": f"_inline_{name}", "name": name, "sort_order": 9999})
            known_names.add(name.lower())
    return table_locs + extras


def create_location(loc_id: str, name: str, description: str = "") -> dict | None:
    return _loc_row(execute_returning(
        """INSERT INTO item_locations (id, name, description, sort_order)
           VALUES (%s, %s, %s, COALESCE((SELECT MAX(sort_order)+1 FROM item_locations), 0))
           RETURNING *""",
        (loc_id, name, description),
    ))


def delete_location(loc_id: str) -> bool:
    return execute("DELETE FROM item_locations WHERE id = %s", (loc_id,)) > 0


# ---------------------------------------------------------------------------
# Item–Image links
# ---------------------------------------------------------------------------

def get_item_images(item_id: str) -> list[dict]:
    rows = fetch_all(
        """SELECT i.*, li.sort_order FROM images i
           JOIN locator_images li ON li.image_id = i.id
           WHERE li.item_id = %s
           ORDER BY li.sort_order, i.created_at""",
        (item_id,),
    )
    return [_image_row(r) for r in rows]


def link_image(item_id: str, image_id: str, sort_order: int = 0):
    execute(
        """INSERT INTO locator_images (item_id, image_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (item_id, image_id, sort_order),
    )


def unlink_image(item_id: str, image_id: str):
    execute(
        "DELETE FROM locator_images WHERE item_id = %s AND image_id = %s",
        (item_id, image_id),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _item_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "location": row.get("location") or "",
        "sub_location": row.get("sub_location") or "",
        "category": row.get("category") or "",
        "tags": list(row.get("tags") or []),
        "quantity": row.get("quantity"),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _loc_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _image_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "filename": row.get("filename") or "",
        "mime_type": row.get("mime_type") or "",
        "size_bytes": row.get("size_bytes", 0),
        "storage_path": row.get("storage_path") or "",
        "sort_order": row.get("sort_order", 0),
        "uploaded_by": row.get("uploaded_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
