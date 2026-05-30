"""Homeopathy App — Schema-aware data layer
=============================================
All tables live in app_homeopathy schema.
"""

import logging
from datetime import datetime, timezone, date

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_homeopathy"

_MEDICINE_HINT = (
    "Focus on: homeopathic medicine name, description, and any notes."
)
_REMEDY_HINT = (
    "Focus on: medicine name, strength/potency (e.g. 30C, 200C, 1M), source supplier, and notes."
)
_BOTTLE_HINT = (
    "Focus on: medicine name, strength, bottle size, storage location, fullness percentage, "
    "last checked date, and any notes. Note bottles at 25% or less need reordering."
)


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


def _fetch_one(query, params=()):
    return fetch_one_in_schema(SCHEMA, query, params)


def _fetch_all(query, params=()):
    return fetch_all_in_schema(SCHEMA, query, params)


def _execute(query, params=()):
    return execute_in_schema(SCHEMA, query, params)


# ---------------------------------------------------------------------------
# Sources (suppliers)
# ---------------------------------------------------------------------------

def save_source(src: dict):
    with scoped_conn(SCHEMA) as conn:
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
    row = _fetch_one("SELECT * FROM homeo_sources WHERE id = %s", (source_id,))
    return _source_row(row) if row else None


def get_all_sources() -> list[dict]:
    return [_source_row(r) for r in _fetch_all("SELECT * FROM homeo_sources ORDER BY name")]


def update_source(source_id: str, updates: dict) -> bool:
    allowed = {"name", "website", "phone", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(source_id)
    return _execute(f"UPDATE homeo_sources SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_source(source_id: str) -> bool:
    return _execute("DELETE FROM homeo_sources WHERE id = %s", (source_id,)) > 0


# ---------------------------------------------------------------------------
# Medicines (name + description)
# ---------------------------------------------------------------------------

def save_medicine(med: dict):
    is_new = get_medicine(med["id"]) is None
    with scoped_conn(SCHEMA) as conn:
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
    saved = get_medicine(med["id"])
    if saved:
        digest_record(app_id="homeopathy", entity_type="medicine",
                      action="created" if is_new else "updated",
                      entity_id=med["id"], record=saved,
                      by=med.get("created_by", ""), context_hint=_MEDICINE_HINT)


def get_medicine(medicine_id: str) -> dict | None:
    row = _fetch_one("SELECT * FROM homeo_medicines WHERE id = %s", (medicine_id,))
    return _medicine_row(row) if row else None


def get_medicine_by_name(name: str) -> dict | None:
    row = _fetch_one("SELECT * FROM homeo_medicines WHERE name ILIKE %s", (name,))
    return _medicine_row(row) if row else None


def get_all_medicines() -> list[dict]:
    return [_medicine_row(r) for r in _fetch_all("SELECT * FROM homeo_medicines ORDER BY name")]


def update_medicine(medicine_id: str, updates: dict) -> bool:
    allowed = {"name", "description", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(medicine_id)
    ok = _execute(f"UPDATE homeo_medicines SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0
    if ok:
        updated = get_medicine(medicine_id)
        if updated:
            digest_record(app_id="homeopathy", entity_type="medicine", action="updated",
                          entity_id=medicine_id, record=updated,
                          by=updates.get("updated_by", ""), context_hint=_MEDICINE_HINT)
    return ok


def delete_medicine(medicine_id: str) -> bool:
    medicine = get_medicine(medicine_id)
    ok = _execute("DELETE FROM homeo_medicines WHERE id = %s", (medicine_id,)) > 0
    if ok and medicine:
        digest_record(app_id="homeopathy", entity_type="medicine", action="deleted",
                      entity_id=medicine_id, record=medicine, by="")
    return ok


# ---------------------------------------------------------------------------
# Remedies (medicine + strength)
# ---------------------------------------------------------------------------

def save_remedy(rem: dict):
    is_new = get_remedy(rem["id"]) is None
    with scoped_conn(SCHEMA) as conn:
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
    saved = get_remedy(rem["id"])
    if saved:
        digest_record(app_id="homeopathy", entity_type="remedy",
                      action="created" if is_new else "updated",
                      entity_id=rem["id"], record=saved,
                      by=rem.get("created_by", ""), context_hint=_REMEDY_HINT)


def get_remedy(remedy_id: str) -> dict | None:
    row = _fetch_one("""
        SELECT r.*, m.name as medicine_name, m.description as medicine_description,
               s.name as source_name
        FROM homeo_remedies r
        JOIN homeo_medicines m ON m.id = r.medicine_id
        LEFT JOIN homeo_sources s ON s.id = r.source_id
        WHERE r.id = %s
    """, (remedy_id,))
    return _remedy_row(row) if row else None


def get_remedy_by_name_strength(medicine_name: str, strength: str) -> dict | None:
    row = _fetch_one("""
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
        rows = _fetch_all("""
            SELECT r.*, m.name as medicine_name, m.description as medicine_description,
                   s.name as source_name
            FROM homeo_remedies r
            JOIN homeo_medicines m ON m.id = r.medicine_id
            LEFT JOIN homeo_sources s ON s.id = r.source_id
            WHERE r.medicine_id = %s
            ORDER BY m.name, r.strength
        """, (medicine_id,))
    else:
        rows = _fetch_all("""
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
    ok = _execute(f"UPDATE homeo_remedies SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0
    if ok:
        updated = get_remedy(remedy_id)
        if updated:
            digest_record(app_id="homeopathy", entity_type="remedy", action="updated",
                          entity_id=remedy_id, record=updated,
                          by=updates.get("updated_by", ""), context_hint=_REMEDY_HINT)
    return ok


def delete_remedy(remedy_id: str) -> bool:
    remedy = get_remedy(remedy_id)
    ok = _execute("DELETE FROM homeo_remedies WHERE id = %s", (remedy_id,)) > 0
    if ok and remedy:
        digest_record(app_id="homeopathy", entity_type="remedy", action="deleted",
                      entity_id=remedy_id, record=remedy, by="")
    return ok


# ---------------------------------------------------------------------------
# Bottle Sizes
# ---------------------------------------------------------------------------

def save_bottle_size(size: dict):
    with scoped_conn(SCHEMA) as conn:
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
    return [_size_row(r) for r in _fetch_all(
        "SELECT * FROM homeo_bottle_sizes ORDER BY sort_order, name"
    )]


def update_bottle_size(size_id: str, updates: dict) -> bool:
    allowed = {"name", "sort_order", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    vals.append(size_id)
    return _execute(f"UPDATE homeo_bottle_sizes SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_bottle_size(size_id: str) -> bool:
    return _execute("DELETE FROM homeo_bottle_sizes WHERE id = %s", (size_id,)) > 0


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def save_location(loc: dict):
    with scoped_conn(SCHEMA) as conn:
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
    return [_location_row(r) for r in _fetch_all(
        "SELECT * FROM homeo_locations ORDER BY sort_order, name"
    )]


def update_location(loc_id: str, updates: dict) -> bool:
    allowed = {"name", "sort_order", "notes"}
    sets, vals = _build_update(updates, allowed)
    if not sets:
        return False
    vals.append(loc_id)
    return _execute(f"UPDATE homeo_locations SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0


def delete_location(loc_id: str) -> bool:
    return _execute("DELETE FROM homeo_locations WHERE id = %s", (loc_id,)) > 0


# ---------------------------------------------------------------------------
# Bottles (inventory)
# ---------------------------------------------------------------------------

def save_bottle(bot: dict):
    is_new = get_bottle(bot["id"]) is None
    with scoped_conn(SCHEMA) as conn:
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
    saved = get_bottle(bot["id"])
    if saved:
        digest_record(app_id="homeopathy", entity_type="bottle",
                      action="created" if is_new else "updated",
                      entity_id=bot["id"], record=saved,
                      by=bot.get("created_by", ""), context_hint=_BOTTLE_HINT)


def get_bottle(bottle_id: str) -> dict | None:
    row = _fetch_one(_BOTTLE_QUERY + " WHERE b.id = %s", (bottle_id,))
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
    rows = _fetch_all(
        _BOTTLE_QUERY + where + " ORDER BY r.strength, m.name, b.fullness",
        tuple(params),
    )
    return [_bottle_row(r) for r in rows]


def get_bottles_grouped_by_strength(low_only: bool = False) -> dict:
    """Return bottles grouped by strength for the main display view."""
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
    ok = _execute(f"UPDATE homeo_bottles SET {', '.join(sets)} WHERE id = %s", tuple(vals)) > 0
    if ok:
        updated = get_bottle(bottle_id)
        if updated:
            digest_record(app_id="homeopathy", entity_type="bottle", action="updated",
                          entity_id=bottle_id, record=updated,
                          by=updates.get("updated_by", ""), context_hint=_BOTTLE_HINT)
    return ok


def check_bottle(bottle_id: str, fullness: int) -> bool:
    """Quick-update fullness and set last_checked to today."""
    return _execute(
        "UPDATE homeo_bottles SET fullness = %s, last_checked = %s, updated_at = %s WHERE id = %s",
        (fullness, date.today().isoformat(), _now(), bottle_id),
    ) > 0


def bulk_check(bottle_ids: list[str], fullness_map: dict[str, int] = None):
    """Mark multiple bottles as checked today. Optionally update fullness per bottle."""
    today = date.today().isoformat()
    now = _now()
    with scoped_conn(SCHEMA) as conn:
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
    bottle = get_bottle(bottle_id)
    ok = _execute("DELETE FROM homeo_bottles WHERE id = %s", (bottle_id,)) > 0
    if ok and bottle:
        digest_record(app_id="homeopathy", entity_type="bottle", action="deleted",
                      entity_id=bottle_id, record=bottle, by="")
    return ok


def get_reorder_list() -> list[dict]:
    """Get all bottles with fullness <= 25%, grouped by source for ordering."""
    rows = _fetch_all(
        _BOTTLE_QUERY + " WHERE b.fullness <= 25 ORDER BY s.name NULLS LAST, m.name, r.strength",
    )
    return [_bottle_row(r) for r in rows]


def search_bottles(query: str) -> list[dict]:
    """Search across medicine names, strengths, locations, notes."""
    pattern = f"%{query}%"
    rows = _fetch_all(
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
# Row formatters
# ---------------------------------------------------------------------------

def _strength_sort_key(strength: str) -> tuple:
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


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "medicine", "list_fn": get_all_medicines, "context_hint": _MEDICINE_HINT},
    {"entity_type": "remedy", "list_fn": get_all_remedies, "context_hint": _REMEDY_HINT},
    {"entity_type": "bottle", "list_fn": get_all_bottles, "context_hint": _BOTTLE_HINT},
]
