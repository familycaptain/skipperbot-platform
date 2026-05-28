"""DEPRECATED — Moved to apps/homeopathy/data.py (app package).
This file is no longer imported. Safe to delete.

Homeopathy — Postgres CRUD
==============================
Data layer for homeopathic remedy inventory: sources, medicines, remedies,
bottle sizes, locations, and bottles.
"""

import logging
from datetime import datetime, timezone, date

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sources (suppliers)
# ---------------------------------------------------------------------------

def save_source(src: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO homeo_sources (id, name, website, phone, notes, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, website = EXCLUDED.website, phone = EXCLUDED.phone,
                    notes = EXCLUDED.notes, updated_at = EXCLUDED.updated_at
            """, (
                src["id"], src["name"], src.get("website"), src.get("phone"),
                src.get("notes", ""), src.get("created_by", ""), src.get("created_at", _now()), _now(),
            ))
        conn.commit()


def get_source(source_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM homeo_sources WHERE id = %s", (source_id,))
    return _source_row(row) if row else None


def get_all_sources() -> list[dict]:
    return [_source_row(r) for r in fetch_all("SELECT * FROM homeo_sources ORDER BY name")]


def update_source(source_id: str, updates: dict) -> bool:
    allowed = {"name", "website", "phone", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(source_id)
    return execute(f"UPDATE homeo_sources SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_source(source_id: str) -> bool:
    return execute("DELETE FROM homeo_sources WHERE id = %s", (source_id,)) > 0


# ---------------------------------------------------------------------------
# Medicines (name + description)
# ---------------------------------------------------------------------------

def save_medicine(med: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO homeo_medicines (id, name, description, notes, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, description = EXCLUDED.description,
                    notes = EXCLUDED.notes, updated_at = EXCLUDED.updated_at
            """, (
                med["id"], med["name"], med.get("description", ""),
                med.get("notes", ""), med.get("created_by", ""), med.get("created_at", _now()), _now(),
            ))
        conn.commit()


def get_medicine(medicine_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM homeo_medicines WHERE id = %s", (medicine_id,))
    return _medicine_row(row) if row else None


def get_medicine_by_name(name: str) -> dict | None:
    row = fetch_one("SELECT * FROM homeo_medicines WHERE name ILIKE %s", (name,))
    return _medicine_row(row) if row else None


def get_all_medicines() -> list[dict]:
    return [_medicine_row(r) for r in fetch_all("SELECT * FROM homeo_medicines ORDER BY name")]


def update_medicine(medicine_id: str, updates: dict) -> bool:
    allowed = {"name", "description", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(medicine_id)
    return execute(f"UPDATE homeo_medicines SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_medicine(medicine_id: str) -> bool:
    return execute("DELETE FROM homeo_medicines WHERE id = %s", (medicine_id,)) > 0


# ---------------------------------------------------------------------------
# Remedies (medicine + strength)
# ---------------------------------------------------------------------------

def save_remedy(rem: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO homeo_remedies (id, medicine_id, strength, source_id, notes,
                                            created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    medicine_id = EXCLUDED.medicine_id, strength = EXCLUDED.strength,
                    source_id = EXCLUDED.source_id, notes = EXCLUDED.notes,
                    updated_at = EXCLUDED.updated_at
            """, (
                rem["id"], rem["medicine_id"], rem["strength"],
                rem.get("source_id"), rem.get("notes", ""),
                rem.get("created_by", ""), rem.get("created_at", _now()), _now(),
            ))
        conn.commit()


def get_remedy(remedy_id: str) -> dict | None:
    row = fetch_one("""
        SELECT r.*, m.name as medicine_name, m.description as medicine_description,
               s.name as source_name
        FROM homeo_remedies r
        JOIN homeo_medicines m ON m.id = r.medicine_id
        LEFT JOIN homeo_sources s ON s.id = r.source_id
        WHERE r.id = %s
    """, (remedy_id,))
    return _remedy_row(row) if row else None


def get_remedy_by_name_strength(medicine_name: str, strength: str) -> dict | None:
    row = fetch_one("""
        SELECT r.*, m.name as medicine_name, m.description as medicine_description,
               s.name as source_name
        FROM homeo_remedies r
        JOIN homeo_medicines m ON m.id = r.medicine_id
        LEFT JOIN homeo_sources s ON s.id = r.source_id
        WHERE m.name ILIKE %s AND r.strength ILIKE %s
    """, (medicine_name, strength))
    return _remedy_row(row) if row else None


def get_all_remedies(medicine_id: str = None) -> list[dict]:
    if medicine_id:
        rows = fetch_all("""
            SELECT r.*, m.name as medicine_name, m.description as medicine_description,
                   s.name as source_name
            FROM homeo_remedies r
            JOIN homeo_medicines m ON m.id = r.medicine_id
            LEFT JOIN homeo_sources s ON s.id = r.source_id
            WHERE r.medicine_id = %s
            ORDER BY m.name, r.strength
        """, (medicine_id,))
    else:
        rows = fetch_all("""
            SELECT r.*, m.name as medicine_name, m.description as medicine_description,
                   s.name as source_name
            FROM homeo_remedies r
            JOIN homeo_medicines m ON m.id = r.medicine_id
            LEFT JOIN homeo_sources s ON s.id = r.source_id
            ORDER BY m.name, r.strength
        """)
    return [_remedy_row(r) for r in rows]


def update_remedy(remedy_id: str, updates: dict) -> bool:
    allowed = {"medicine_id", "strength", "source_id", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(remedy_id)
    return execute(f"UPDATE homeo_remedies SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_remedy(remedy_id: str) -> bool:
    return execute("DELETE FROM homeo_remedies WHERE id = %s", (remedy_id,)) > 0


# ---------------------------------------------------------------------------
# Bottle Sizes
# ---------------------------------------------------------------------------

def save_bottle_size(size: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO homeo_bottle_sizes (id, name, sort_order, notes, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, sort_order = EXCLUDED.sort_order, notes = EXCLUDED.notes
            """, (
                size["id"], size["name"], size.get("sort_order", 0),
                size.get("notes", ""), size.get("created_by", ""), size.get("created_at", _now()),
            ))
        conn.commit()


def get_all_bottle_sizes() -> list[dict]:
    return [_size_row(r) for r in fetch_all(
        "SELECT * FROM homeo_bottle_sizes ORDER BY sort_order, name"
    )]


def update_bottle_size(size_id: str, updates: dict) -> bool:
    allowed = {"name", "sort_order", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    vals.append(size_id)
    return execute(f"UPDATE homeo_bottle_sizes SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_bottle_size(size_id: str) -> bool:
    return execute("DELETE FROM homeo_bottle_sizes WHERE id = %s", (size_id,)) > 0


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def save_location(loc: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO homeo_locations (id, name, sort_order, notes, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, sort_order = EXCLUDED.sort_order, notes = EXCLUDED.notes
            """, (
                loc["id"], loc["name"], loc.get("sort_order", 0),
                loc.get("notes", ""), loc.get("created_by", ""), loc.get("created_at", _now()),
            ))
        conn.commit()


def get_all_locations() -> list[dict]:
    return [_location_row(r) for r in fetch_all(
        "SELECT * FROM homeo_locations ORDER BY sort_order, name"
    )]


def update_location(loc_id: str, updates: dict) -> bool:
    allowed = {"name", "sort_order", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    vals.append(loc_id)
    return execute(f"UPDATE homeo_locations SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_location(loc_id: str) -> bool:
    return execute("DELETE FROM homeo_locations WHERE id = %s", (loc_id,)) > 0


# ---------------------------------------------------------------------------
# Bottles (inventory)
# ---------------------------------------------------------------------------

def save_bottle(bot: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO homeo_bottles (id, remedy_id, size_id, location_id, fullness,
                                           last_checked, notes, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    remedy_id = EXCLUDED.remedy_id, size_id = EXCLUDED.size_id,
                    location_id = EXCLUDED.location_id, fullness = EXCLUDED.fullness,
                    last_checked = EXCLUDED.last_checked, notes = EXCLUDED.notes,
                    updated_at = EXCLUDED.updated_at
            """, (
                bot["id"], bot["remedy_id"], bot.get("size_id"), bot.get("location_id"),
                bot.get("fullness", 100), bot.get("last_checked"),
                bot.get("notes", ""), bot.get("created_by", ""), bot.get("created_at", _now()), _now(),
            ))
        conn.commit()


def get_bottle(bottle_id: str) -> dict | None:
    row = fetch_one(_BOTTLE_QUERY + " WHERE b.id = %s", (bottle_id,))
    return _bottle_row(row) if row else None


def get_all_bottles(location_id: str = None, low_only: bool = False,
                    remedy_id: str = None, strength: str = None) -> list[dict]:
    clauses, params = [], []
    if location_id:
        clauses.append("b.location_id = %s")
        params.append(location_id)
    if low_only:
        clauses.append("b.fullness <= 25")
    if remedy_id:
        clauses.append("b.remedy_id = %s")
        params.append(remedy_id)
    if strength:
        clauses.append("r.strength ILIKE %s")
        params.append(strength)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = fetch_all(
        _BOTTLE_QUERY + where + " ORDER BY r.strength, m.name, b.fullness",
        tuple(params),
    )
    return [_bottle_row(r) for r in rows]


def get_bottles_grouped_by_strength(low_only: bool = False) -> dict:
    """Return bottles grouped by strength for the main display view.

    Returns: { "200C": [ {medicine_name, bottles: [...] }, ... ], ... }
    """
    all_bottles = get_all_bottles(low_only=low_only)
    groups = {}
    for bot in all_bottles:
        strength = bot["strength"]
        med_name = bot["medicine_name"]
        if strength not in groups:
            groups[strength] = {}
        if med_name not in groups[strength]:
            groups[strength][med_name] = {
                "medicine_name": med_name,
                "medicine_description": bot.get("medicine_description", ""),
                "strength": strength,
                "bottles": [],
            }
        groups[strength][med_name]["bottles"].append(bot)
    # Convert to sorted lists
    result = {}
    for strength in sorted(groups.keys(), key=_strength_sort_key):
        result[strength] = sorted(groups[strength].values(), key=lambda x: x["medicine_name"])
    return result


def update_bottle(bottle_id: str, updates: dict) -> bool:
    allowed = {"remedy_id", "size_id", "location_id", "fullness", "last_checked", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(bottle_id)
    return execute(f"UPDATE homeo_bottles SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def check_bottle(bottle_id: str, fullness: int) -> bool:
    """Quick-update fullness and set last_checked to today."""
    return execute(
        "UPDATE homeo_bottles SET fullness = %s, last_checked = %s, updated_at = %s WHERE id = %s",
        (fullness, date.today().isoformat(), _now(), bottle_id),
    ) > 0


def bulk_check(bottle_ids: list[str], fullness_map: dict[str, int] = None):
    """Mark multiple bottles as checked today. Optionally update fullness per bottle."""
    today = date.today().isoformat()
    now = _now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for bid in bottle_ids:
                if fullness_map and bid in fullness_map:
                    cur.execute(
                        "UPDATE homeo_bottles SET fullness = %s, last_checked = %s, updated_at = %s WHERE id = %s",
                        (fullness_map[bid], today, now, bid),
                    )
                else:
                    cur.execute(
                        "UPDATE homeo_bottles SET last_checked = %s, updated_at = %s WHERE id = %s",
                        (today, now, bid),
                    )
        conn.commit()


def delete_bottle(bottle_id: str) -> bool:
    return execute("DELETE FROM homeo_bottles WHERE id = %s", (bottle_id,)) > 0


def get_reorder_list() -> list[dict]:
    """Get all bottles with fullness <= 25%, grouped by source for ordering."""
    rows = fetch_all(
        _BOTTLE_QUERY + " WHERE b.fullness <= 25 ORDER BY s.name NULLS LAST, m.name, r.strength",
    )
    return [_bottle_row(r) for r in rows]


def search_bottles(query: str) -> list[dict]:
    """Search across medicine names, strengths, locations, notes."""
    pattern = f"%{query}%"
    rows = fetch_all(
        _BOTTLE_QUERY + """
        WHERE m.name ILIKE %s OR r.strength ILIKE %s OR m.description ILIKE %s
              OR l.name ILIKE %s OR sz.name ILIKE %s OR b.notes ILIKE %s
        ORDER BY m.name, r.strength
        """,
        (pattern, pattern, pattern, pattern, pattern, pattern),
    )
    return [_bottle_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Shared bottle query
# ---------------------------------------------------------------------------

_BOTTLE_QUERY = """
    SELECT b.*,
           r.strength, r.medicine_id, r.source_id,
           m.name as medicine_name, m.description as medicine_description,
           s.name as source_name,
           sz.name as size_name,
           l.name as location_name
    FROM homeo_bottles b
    JOIN homeo_remedies r ON r.id = b.remedy_id
    JOIN homeo_medicines m ON m.id = r.medicine_id
    LEFT JOIN homeo_sources s ON s.id = r.source_id
    LEFT JOIN homeo_bottle_sizes sz ON sz.id = b.size_id
    LEFT JOIN homeo_locations l ON l.id = b.location_id
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_update(updates: dict, allowed: set) -> tuple[list[str], list]:
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    return sets, vals


def _strength_sort_key(strength: str) -> tuple:
    """Sort strengths: higher potencies first (1M > 200C > 30C > 6C), then alpha."""
    s = strength.upper().strip()
    if s.endswith("M"):
        try:
            return (0, -int(s[:-1]))
        except ValueError:
            pass
    if s.endswith("C"):
        try:
            return (1, -int(s[:-1]))
        except ValueError:
            pass
    if s.endswith("X"):
        try:
            return (2, -int(s[:-1]))
        except ValueError:
            pass
    return (3, 0)


def _source_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "website": row.get("website") or "",
        "phone": row.get("phone") or "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _medicine_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _remedy_row(row: dict) -> dict:
    if not row:
        return {}
    result = {
        "id": row["id"],
        "medicine_id": row.get("medicine_id") or "",
        "strength": row.get("strength") or "",
        "source_id": row.get("source_id") or "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }
    if row.get("medicine_name"):
        result["medicine_name"] = row["medicine_name"]
    if row.get("medicine_description") is not None:
        result["medicine_description"] = row["medicine_description"]
    if row.get("source_name"):
        result["source_name"] = row["source_name"]
    return result


def _size_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "sort_order": row.get("sort_order", 0),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _location_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "sort_order": row.get("sort_order", 0),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _bottle_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "remedy_id": row.get("remedy_id") or "",
        "size_id": row.get("size_id") or "",
        "location_id": row.get("location_id") or "",
        "fullness": row.get("fullness", 100),
        "last_checked": row["last_checked"].isoformat() if row.get("last_checked") else "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
        # Joined fields
        "medicine_id": row.get("medicine_id") or "",
        "medicine_name": row.get("medicine_name") or "",
        "medicine_description": row.get("medicine_description") or "",
        "strength": row.get("strength") or "",
        "source_id": row.get("source_id") or "",
        "source_name": row.get("source_name") or "",
        "size_name": row.get("size_name") or "",
        "location_name": row.get("location_name") or "",
    }
