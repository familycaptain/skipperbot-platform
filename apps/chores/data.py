"""Chores App — Schema-aware data layer.

All tables live in the app_chores schema. No cross-schema foreign keys.
References to public.users are stored as plain TEXT (the user's `name`).
"""

import logging
import uuid
from datetime import datetime, timezone

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_chores"

# Extraction hints — guide the LLM digest toward what semantic recall will
# actually need to look up later ("did the toilet" → ch-id, etc.).
_KID_HINT = (
    "Focus on: the kid's name, their linked username, color, and whether "
    "they receive morning chore notifications."
)
_ZONE_HINT = (
    "Focus on: the zone name and what household area it covers (e.g. shared "
    "bathroom, a kid's bedroom, a shared bedroom), the rotation "
    "start date, and the kids that rotate through it."
)
_CHORE_HINT = (
    "Focus on: the chore name (verb + object — vacuum, dust, toilet, sink, "
    "laundry, declutter, empty trash, mop), the zone it belongs to, the day "
    "of week it falls on, and the note (e.g. 'Thorough cleaning' / 'Quick "
    "clean'). These memories are how chat can recall which chore a kid "
    "means when they say 'I did the trash' or 'I cleaned the bathroom'."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kid_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row["name"],
        "color": row["color"],
        "sort_order": row["sort_order"],
        "user_id": row["user_id"],
        "notify_morning": row["notify_morning"],
        "notify_evening": row["notify_evening"],
        "active": row["active"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _zone_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "rotation_start": row["rotation_start"].isoformat() if row.get("rotation_start") else None,
        "sort_order": row["sort_order"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _chore_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "zone_id": row["zone_id"],
        "dow": row["dow"],
        "position": row["position"],
        "name": row["name"],
        "note": row["note"],
        "active": row["active"],
    }


def _completion_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "chore_id": row["chore_id"],
        "kid_id": row["kid_id"],
        "chore_date": row["chore_date"].isoformat() if row.get("chore_date") else None,
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
        "completed_by": row["completed_by"],
        "status": row["status"],
        "note": row["note"],
    }


# ---------------------------------------------------------------------------
# Kids
# ---------------------------------------------------------------------------

def list_kids(active_only: bool = True) -> list[dict]:
    where = "WHERE active = TRUE" if active_only else ""
    rows = fetch_all_in_schema(
        SCHEMA,
        f"SELECT * FROM kids {where} ORDER BY sort_order, name",
    )
    return [_kid_row(r) for r in rows]


def get_kid(kid_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM kids WHERE id = %s", (kid_id,))
    return _kid_row(row) if row else None


def eligible_member_accounts() -> list[dict]:
    """Household accounts eligible to link as a NEW kid: every non-bot human
    account (data_layer.users.get_human_users already excludes bots) MINUS any
    account already linked to an ACTIVE kid. Returned as {username, display_name}
    (label = display name, fallback username), sorted by display name. There is
    no 'kid' role today (#80 adds richer roles), so all non-bot humans qualify.
    """
    from data_layer.users import get_human_users, display_name_for
    linked = {k.get("user_id") for k in list_kids(active_only=True) if k.get("user_id")}
    members = [
        {"username": u["name"], "display_name": display_name_for(u["name"])}
        for u in get_human_users()
        if u.get("name") and u["name"] not in linked
    ]
    members.sort(key=lambda m: m["display_name"].lower())
    return members


def get_kid_by_user(user_id: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM kids WHERE user_id = %s AND active = TRUE", (user_id,)
    )
    return _kid_row(row) if row else None


def create_kid(name: str, color: str = "#888888", sort_order: int = 0,
               user_id: str | None = None, notify_morning: bool = True,
               notify_evening: bool = False, by: str = "") -> dict:
    kid_id = _gen_id("kid")
    row = execute_returning_in_schema(
        SCHEMA,
        """
        INSERT INTO kids (id, name, color, sort_order, user_id, notify_morning, notify_evening)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (kid_id, name, color, sort_order, user_id, notify_morning, notify_evening),
    )
    kid = _kid_row(row)
    if kid:
        digest_record(app_id="chores", entity_type="kid", action="created",
                      entity_id=kid["id"], record=kid, by=by, context_hint=_KID_HINT)
    return kid


def update_kid(kid_id: str, by: str = "", **fields) -> dict | None:
    allowed = {"name", "color", "sort_order", "user_id", "notify_morning",
               "notify_evening", "active"}
    sets = []
    params = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return get_kid(kid_id)
    sets.append("updated_at = now()")
    params.append(kid_id)
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE kids SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    kid = _kid_row(row) if row else None
    if kid:
        digest_record(app_id="chores", entity_type="kid", action="updated",
                      entity_id=kid["id"], record=kid, by=by, context_hint=_KID_HINT)
    return kid


def soft_delete_kid(kid_id: str, by: str = "") -> bool:
    kid = get_kid(kid_id)
    n = execute_in_schema(
        SCHEMA,
        "UPDATE kids SET active = FALSE, updated_at = now() WHERE id = %s",
        (kid_id,),
    )
    ok = n > 0
    if ok and kid:
        kid["active"] = False
        digest_record(app_id="chores", entity_type="kid", action="deleted",
                      entity_id=kid_id, record=kid, by=by)
    return ok


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def list_zones() -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA, "SELECT * FROM zones ORDER BY sort_order, name"
    )
    return [_zone_row(r) for r in rows]


def get_zone(zone_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM zones WHERE id = %s", (zone_id,))
    return _zone_row(row) if row else None


def get_zone_by_name(name: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM zones WHERE name = %s", (name,))
    return _zone_row(row) if row else None


def create_zone(name: str, rotation_start: str, description: str = "",
                sort_order: int = 0, by: str = "") -> dict:
    zone_id = _gen_id("cz")
    row = execute_returning_in_schema(
        SCHEMA,
        """
        INSERT INTO zones (id, name, description, rotation_start, sort_order)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (zone_id, name, description, rotation_start, sort_order),
    )
    zone = _zone_row(row)
    if zone:
        digest_record(app_id="chores", entity_type="zone", action="created",
                      entity_id=zone["id"], record=zone, by=by, context_hint=_ZONE_HINT)
    return zone


def update_zone(zone_id: str, by: str = "", **fields) -> dict | None:
    allowed = {"name", "description", "rotation_start", "sort_order"}
    sets = []
    params = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return get_zone(zone_id)
    sets.append("updated_at = now()")
    params.append(zone_id)
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE zones SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    zone = _zone_row(row) if row else None
    if zone:
        digest_record(app_id="chores", entity_type="zone", action="updated",
                      entity_id=zone["id"], record=zone, by=by, context_hint=_ZONE_HINT)
    return zone


def delete_zone(zone_id: str, by: str = "") -> bool:
    # ON DELETE CASCADE cleans chores and zone_members; completions block via RESTRICT
    zone = get_zone(zone_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM zones WHERE id = %s", (zone_id,))
    ok = n > 0
    if ok and zone:
        digest_record(app_id="chores", entity_type="zone", action="deleted",
                      entity_id=zone_id, record=zone, by=by)
    return ok


# ---------------------------------------------------------------------------
# Zone members
# ---------------------------------------------------------------------------

def get_zone_members(zone_id: str) -> list[dict]:
    """Return ordered list of {kid_id, position, kid_name, color} for a zone."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """
        SELECT zm.kid_id, zm.position, k.name AS kid_name, k.color, k.user_id
        FROM zone_members zm
        JOIN kids k ON k.id = zm.kid_id
        WHERE zm.zone_id = %s
        ORDER BY zm.position
        """,
        (zone_id,),
    )
    return [dict(r) for r in rows]


def set_zone_members(zone_id: str, kid_ids: list[str]) -> list[dict]:
    """Replace zone membership wholesale with the given ordered list."""
    execute_in_schema(SCHEMA, "DELETE FROM zone_members WHERE zone_id = %s", (zone_id,))
    for pos, kid_id in enumerate(kid_ids):
        execute_in_schema(
            SCHEMA,
            "INSERT INTO zone_members (zone_id, kid_id, position) VALUES (%s, %s, %s)",
            (zone_id, kid_id, pos),
        )
    return get_zone_members(zone_id)


# ---------------------------------------------------------------------------
# Chores
# ---------------------------------------------------------------------------

def list_chores(zone_id: str | None = None, active_only: bool = True) -> list[dict]:
    clauses = []
    params: list = []
    if zone_id:
        clauses.append("zone_id = %s")
        params.append(zone_id)
    if active_only:
        clauses.append("active = TRUE")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = fetch_all_in_schema(
        SCHEMA,
        f"SELECT * FROM chores {where} ORDER BY zone_id, dow, position",
        tuple(params),
    )
    return [_chore_row(r) for r in rows]


def get_chore(chore_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM chores WHERE id = %s", (chore_id,))
    return _chore_row(row) if row else None


def list_chores_for_dow(zone_id: str, dow: int) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """
        SELECT * FROM chores
        WHERE zone_id = %s AND dow = %s AND active = TRUE
        ORDER BY position
        """,
        (zone_id, dow),
    )
    return [_chore_row(r) for r in rows]


def next_free_position(zone_id: str, dow: int) -> int:
    row = fetch_one_in_schema(
        SCHEMA,
        "SELECT COALESCE(MAX(position) + 1, 0) AS next_pos FROM chores WHERE zone_id = %s AND dow = %s",
        (zone_id, dow),
    )
    return row["next_pos"] if row else 0


def _chore_with_zone(chore: dict) -> dict:
    """Augment a chore dict with zone_name + dow_name for richer memory facts."""
    if not chore:
        return chore
    zone = get_zone(chore["zone_id"])
    out = dict(chore)
    out["zone_name"] = zone["name"] if zone else ""
    out["dow_name"] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][chore["dow"]]
    return out


def create_chore(zone_id: str, dow: int, name: str, note: str = "",
                 position: int | None = None, by: str = "") -> dict:
    if position is None:
        position = next_free_position(zone_id, dow)
    chore_id = _gen_id("ch")
    row = execute_returning_in_schema(
        SCHEMA,
        """
        INSERT INTO chores (id, zone_id, dow, position, name, note)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (chore_id, zone_id, dow, position, name, note),
    )
    chore = _chore_row(row)
    if chore:
        digest_record(app_id="chores", entity_type="chore", action="created",
                      entity_id=chore["id"], record=_chore_with_zone(chore),
                      by=by, context_hint=_CHORE_HINT)
    return chore


def update_chore(chore_id: str, by: str = "", **fields) -> dict | None:
    allowed = {"name", "note", "dow", "position", "active"}
    sets = []
    params = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return get_chore(chore_id)
    sets.append("updated_at = now()")
    params.append(chore_id)
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE chores SET {', '.join(sets)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    chore = _chore_row(row) if row else None
    if chore:
        digest_record(app_id="chores", entity_type="chore", action="updated",
                      entity_id=chore["id"], record=_chore_with_zone(chore),
                      by=by, context_hint=_CHORE_HINT)
    return chore


def soft_delete_chore(chore_id: str, by: str = "") -> bool:
    chore = get_chore(chore_id)
    n = execute_in_schema(
        SCHEMA,
        "UPDATE chores SET active = FALSE, updated_at = now() WHERE id = %s",
        (chore_id,),
    )
    ok = n > 0
    if ok and chore:
        chore["active"] = False
        digest_record(app_id="chores", entity_type="chore", action="deleted",
                      entity_id=chore_id, record=_chore_with_zone(chore), by=by)
    return ok


# ---------------------------------------------------------------------------
# Chore completions
# ---------------------------------------------------------------------------

def get_completion(chore_id: str, kid_id: str, chore_date: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA,
        """
        SELECT * FROM chore_completions
        WHERE chore_id = %s AND kid_id = %s AND chore_date = %s
        """,
        (chore_id, kid_id, chore_date),
    )
    return _completion_row(row) if row else None


def list_completions_for_date(chore_date: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM chore_completions WHERE chore_date = %s ORDER BY completed_at",
        (chore_date,),
    )
    return [_completion_row(r) for r in rows]


def list_completions_in_range(date_from: str, date_to: str,
                              kid_id: str | None = None,
                              limit: int = 500) -> list[dict]:
    clauses = ["chore_date BETWEEN %s AND %s"]
    params: list = [date_from, date_to]
    if kid_id:
        clauses.append("kid_id = %s")
        params.append(kid_id)
    where = " AND ".join(clauses)
    params.append(limit)
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""
        SELECT * FROM chore_completions
        WHERE {where}
        ORDER BY chore_date DESC, completed_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [_completion_row(r) for r in rows]


def upsert_completion(chore_id: str, kid_id: str, chore_date: str,
                      completed_by: str | None = None,
                      status: str = "done", note: str = "") -> dict:
    """Idempotent: returns existing row if already present, else inserts."""
    existing = get_completion(chore_id, kid_id, chore_date)
    if existing:
        return existing
    cc_id = _gen_id("cc")
    row = execute_returning_in_schema(
        SCHEMA,
        """
        INSERT INTO chore_completions
            (id, chore_id, kid_id, chore_date, completed_by, status, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (cc_id, chore_id, kid_id, chore_date, completed_by, status, note),
    )
    return _completion_row(row)


def delete_completion(completion_id: str) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        "DELETE FROM chore_completions WHERE id = %s RETURNING *",
        (completion_id,),
    )
    return _completion_row(row) if row else None


def delete_completion_by_key(chore_id: str, kid_id: str, chore_date: str) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """
        DELETE FROM chore_completions
        WHERE chore_id = %s AND kid_id = %s AND chore_date = %s
        RETURNING *
        """,
        (chore_id, kid_id, chore_date),
    )
    return _completion_row(row) if row else None
