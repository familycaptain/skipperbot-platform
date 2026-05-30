"""Meals App — Schema-aware data layer
=======================================
All tables live in the app_meals schema.
"""

import json
import logging
from datetime import datetime, timezone

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_meals"

_MEAL_HINT = (
    "Focus on: meal name, effort level (low/medium/high), "
    "tags/descriptors (including cuisine as a lowercase tag), rating (1-5), prep and cook times, and any notes about the meal."
)
_COMPONENT_HINT = (
    "Focus on: component name, type (protein/vegetable/starch/sauce/etc), "
    "description, and any tags."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jslist(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return list(val)


def _normalize_tag_value(value: str) -> str:
    """Normalize user-facing tag filters like '#snack' to stored tag values."""
    return (value or "").strip().lower().lstrip("#").strip()


def _tag_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _component_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "type": row.get("type") or "other",
        "description": row.get("description") or "",
        "tags": _jslist(row.get("tags")),
        "recipe_id": row.get("recipe_id"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _image_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "filename": row.get("filename") or "",
        "mime_type": row.get("mime_type") or "image/jpeg",
        "storage_path": row.get("storage_path") or "",
        "uploaded_by": row.get("uploaded_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "sort_order": row.get("sort_order", 0),
    }


def _meal_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "effort": row.get("effort") or "medium",
        "prep_time_min": row.get("prep_time_min"),
        "cook_time_min": row.get("cook_time_min"),
        "tags": _jslist(row.get("tags")),
        "notes": row.get("notes") or "",
        "rating": row.get("rating"),
        "recipe_doc_id": row.get("recipe_doc_id"),
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
        "primary_photo": {
            "id": row["primary_photo_id"],
            "storage_path": row.get("primary_photo_path") or "",
        } if row.get("primary_photo_id") else None,
    }


def _link_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "meal_id": row.get("meal_id") or "",
        "component_id": row.get("component_id") or "",
        "component_name": row.get("component_name") or "",
        "component_type": row.get("component_type") or "",
        "component_recipe_id": row.get("recipe_id"),
        "role": row.get("role") or "side",
        "sort_order": row.get("sort_order", 0),
        "notes": row.get("notes") or "",
    }


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def tag_cloud() -> list[dict]:
    """Return all distinct tags actually used on meals, with counts, sorted by frequency."""
    rows = fetch_all_in_schema(SCHEMA,
        """SELECT tag, COUNT(*) AS count
           FROM meals, jsonb_array_elements_text(tags) AS tag
           GROUP BY tag
           ORDER BY tag""")
    return [{"name": r["tag"], "count": int(r["count"])} for r in rows]


def list_tags(with_counts: bool = False) -> list[dict]:
    if with_counts:
        rows = fetch_all_in_schema(SCHEMA,
            """SELECT t.*, COUNT(m.id) AS usage_count
               FROM meal_tags t
               LEFT JOIN meals m ON m.tags @> to_jsonb(t.name)
               GROUP BY t.id
               ORDER BY t.name""")
        return [{**_tag_row(r), "usage_count": r.get("usage_count", 0)} for r in rows]
    rows = fetch_all_in_schema(SCHEMA,
        "SELECT * FROM meal_tags ORDER BY name")
    return [_tag_row(r) for r in rows]


def _prune_tags() -> None:
    """Remove tags from meal_tags that are no longer used on any meal."""
    execute_in_schema(SCHEMA,
        """DELETE FROM meal_tags
           WHERE name NOT IN (
               SELECT DISTINCT tag
               FROM meals, jsonb_array_elements_text(tags) AS tag
           )""")


def _ensure_tags(tags: list) -> None:
    """Insert any tags not yet in meal_tags registry (idempotent)."""
    if not tags:
        return
    existing = {r["name"] for r in fetch_all_in_schema(SCHEMA, "SELECT name FROM meal_tags")}
    for tag in tags:
        tag = tag.strip().lower()
        if tag and tag not in existing:
            import uuid as _uuid
            tag_id = f"mtg-{_uuid.uuid4().hex[:8]}"
            execute_in_schema(SCHEMA,
                """INSERT INTO meal_tags (id, name, sort_order)
                   VALUES (%s, %s, (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM meal_tags))
                   ON CONFLICT (name) DO NOTHING""",
                (tag_id, tag))
            existing.add(tag)


def create_tag(tag_id: str, name: str) -> dict:
    row = execute_returning_in_schema(SCHEMA,
        """INSERT INTO meal_tags (id, name, sort_order)
           VALUES (%s, %s, (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM meal_tags))
           RETURNING *""",
        (tag_id, name.strip()))
    return _tag_row(row) if row else {}


def delete_tag(tag_id: str) -> bool:
    n = execute_in_schema(SCHEMA,
        "DELETE FROM meal_tags WHERE id=%s", (tag_id,))
    return n > 0


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def list_components(q: str = "", type_filter: str = "") -> list[dict]:
    if q.strip():
        rows = fetch_all_in_schema(SCHEMA,
            "SELECT * FROM meal_components WHERE name ILIKE %s ORDER BY name",
            (f"%{q.strip()}%",))
    elif type_filter.strip():
        rows = fetch_all_in_schema(SCHEMA,
            "SELECT * FROM meal_components WHERE type=%s ORDER BY name",
            (type_filter.strip(),))
    else:
        rows = fetch_all_in_schema(SCHEMA,
            "SELECT * FROM meal_components ORDER BY name")
    return [_component_row(r) for r in rows]


def get_component(component_id: str) -> dict:
    row = fetch_one_in_schema(SCHEMA,
        "SELECT * FROM meal_components WHERE id=%s", (component_id,))
    return _component_row(row) if row else {}


def create_component(component_id: str, name: str, comp_type: str = "other",
                     description: str = "", tags: list = None,
                     recipe_id: str = None, by: str = "") -> dict:
    row = execute_returning_in_schema(SCHEMA,
        """INSERT INTO meal_components (id, name, type, description, tags, recipe_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (component_id, name.strip(), comp_type, description,
         json.dumps(tags or []), recipe_id))
    component = _component_row(row) if row else {}
    if component:
        digest_record(app_id="meals", entity_type="meal component", action="created",
                      entity_id=component_id, record=component, by=by,
                      context_hint=_COMPONENT_HINT)
    return component


def update_component(component_id: str, by: str = "", **fields) -> dict:
    allowed = {"name", "type", "description", "tags", "recipe_id"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "tags":
            v = json.dumps(v if isinstance(v, list) else [])
        sets.append(f"{k}=%s")
        params.append(v)
    if not sets:
        return get_component(component_id)
    sets.append("updated_at=now()")
    params.append(component_id)
    row = execute_returning_in_schema(SCHEMA,
        f"UPDATE meal_components SET {', '.join(sets)} WHERE id=%s RETURNING *",
        tuple(params))
    component = _component_row(row) if row else {}
    if component:
        digest_record(app_id="meals", entity_type="meal component", action="updated",
                      entity_id=component_id, record=component, by=by,
                      context_hint=_COMPONENT_HINT)
    return component


def delete_component(component_id: str, by: str = "") -> bool:
    component = get_component(component_id)
    n = execute_in_schema(SCHEMA,
        "DELETE FROM meal_components WHERE id=%s", (component_id,))
    if n > 0 and component:
        digest_record(app_id="meals", entity_type="meal component", action="deleted",
                      entity_id=component_id, record=component, by=by)
    return n > 0


# ---------------------------------------------------------------------------
# Meals
# ---------------------------------------------------------------------------

def list_meals(effort: str = "", q: str = "", tag: str = "") -> list[dict]:
    where, params = [], []
    if q.strip():
        where.append("m.name ILIKE %s")
        params.append(f"%{q.strip()}%")
    if effort.strip():
        where.append("m.effort=%s")
        params.append(effort.strip())
    tag_value = _normalize_tag_value(tag)
    if tag_value:
        where.append("m.tags @> to_jsonb(ARRAY[%s::text])")
        params.append(tag_value)
    sql = """
        SELECT m.*,
               photo.id            AS primary_photo_id,
               photo.storage_path  AS primary_photo_path
        FROM meals m
        LEFT JOIN LATERAL (
            SELECT i.id, i.storage_path
            FROM meal_photos mp
            JOIN public.images i ON i.id = mp.image_id
            WHERE mp.meal_id = m.id
            ORDER BY mp.sort_order, i.created_at
            LIMIT 1
        ) photo ON true
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.name"
    rows = fetch_all_in_schema(SCHEMA, sql, tuple(params))
    return [_meal_row(r) for r in rows]


def get_meal(meal_id: str) -> dict:
    row = fetch_one_in_schema(SCHEMA,
        "SELECT * FROM meals WHERE id=%s", (meal_id,))
    if not row:
        return {}
    meal = _meal_row(row)
    meal["components"] = get_meal_components(meal_id)
    meal["photos"] = get_meal_photos(meal_id)
    meal["primary_photo"] = meal["photos"][0] if meal["photos"] else None
    return meal


def create_meal(meal_id: str, name: str, created_by: str,
                effort: str = "medium",
                description: str = "", tags: list = None,
                notes: str = "", rating: int = None,
                prep_time_min: int = None, cook_time_min: int = None,
                recipe_doc_id: str = None) -> dict:
    row = execute_returning_in_schema(SCHEMA,
        """INSERT INTO meals
               (id, name, description, effort, prep_time_min, cook_time_min,
                tags, notes, rating, recipe_doc_id, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (meal_id, name.strip(), description, effort,
         prep_time_min, cook_time_min,
         json.dumps(tags or []), notes, rating, recipe_doc_id, created_by))
    meal = _meal_row(row) if row else {}
    if meal:
        _ensure_tags(tags or [])
        digest_record(app_id="meals", entity_type="meal", action="created",
                      entity_id=meal_id, record=meal, by=created_by,
                      context_hint=_MEAL_HINT)
    return meal


def update_meal(meal_id: str, by: str = "", **fields) -> dict:
    allowed = {"name", "description", "effort", "prep_time_min",
               "cook_time_min", "tags", "notes", "rating", "recipe_doc_id"}
    sets, params = [], []
    _tags_changed = False
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "tags":
            _ensure_tags(v if isinstance(v, list) else [])
            v = json.dumps(v if isinstance(v, list) else [])
            _tags_changed = True
        sets.append(f"{k}=%s")
        params.append(v)
    if not sets:
        return get_meal(meal_id)
    sets.append("updated_at=now()")
    params.append(meal_id)
    execute_in_schema(SCHEMA,
        f"UPDATE meals SET {', '.join(sets)} WHERE id=%s",
        tuple(params))
    meal = get_meal(meal_id)
    if meal:
        if _tags_changed:
            _prune_tags()
        digest_record(app_id="meals", entity_type="meal", action="updated",
                      entity_id=meal_id, record=meal, by=by,
                      context_hint=_MEAL_HINT)
    return meal


def delete_meal(meal_id: str, by: str = "") -> bool:
    meal = get_meal(meal_id)
    n = execute_in_schema(SCHEMA,
        "DELETE FROM meals WHERE id=%s", (meal_id,))
    if n > 0 and meal:
        _prune_tags()
        digest_record(app_id="meals", entity_type="meal", action="deleted",
                      entity_id=meal_id, record=meal, by=by)
    return n > 0


# ---------------------------------------------------------------------------
# Meal–Component links
# ---------------------------------------------------------------------------

def get_meal_components(meal_id: str) -> list[dict]:
    rows = fetch_all_in_schema(SCHEMA,
        """SELECT mcl.*, mc.name AS component_name, mc.type AS component_type,
                  mc.recipe_id
           FROM meal_component_links mcl
           JOIN meal_components mc ON mc.id = mcl.component_id
           WHERE mcl.meal_id = %s
           ORDER BY mcl.sort_order, mcl.id""",
        (meal_id,))
    return [_link_row(r) for r in rows]


def set_meal_components(meal_id: str, components: list[dict]) -> list[dict]:
    """Replace all component links for a meal.

    Each item in components: {component_id, role, sort_order, notes}
    """
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meal_component_links WHERE meal_id=%s", (meal_id,))
            for i, c in enumerate(components):
                cur.execute(
                    """INSERT INTO meal_component_links
                           (meal_id, component_id, role, sort_order, notes)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (meal_id,
                     c["component_id"],
                     c.get("role", "side"),
                     c.get("sort_order", i),
                     c.get("notes", "")))
        conn.commit()
    return get_meal_components(meal_id)


# ---------------------------------------------------------------------------
# Meal Photos (soft FK to public.images)
# ---------------------------------------------------------------------------

def get_meal_photos(meal_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, mp.sort_order FROM public.images i
           JOIN meal_photos mp ON mp.image_id = i.id
           WHERE mp.meal_id = %s
           ORDER BY mp.sort_order, i.created_at""",
        (meal_id,),
    )
    return [_image_row(r) for r in rows]


def get_photos_for_meals(meal_ids: list) -> dict:
    """Batch-load photos for multiple meals. Returns {meal_id: [photo, ...]}."""
    if not meal_ids:
        return {}
    placeholders = ",".join(["%s"] * len(meal_ids))
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT i.*, mp.meal_id, mp.sort_order FROM public.images i
            JOIN meal_photos mp ON mp.image_id = i.id
            WHERE mp.meal_id IN ({placeholders})
            ORDER BY mp.meal_id, mp.sort_order, i.created_at""",
        tuple(meal_ids),
    )
    result: dict = {}
    for r in rows:
        mid = r["meal_id"]
        if mid not in result:
            result[mid] = []
        result[mid].append(_image_row(r))
    return result


def link_meal_photo(meal_id: str, image_id: str, sort_order: int = None):
    if sort_order is None:
        row = fetch_one_in_schema(
            SCHEMA,
            "SELECT COALESCE(MAX(sort_order), -1) AS mx FROM meal_photos WHERE meal_id = %s",
            (meal_id,),
        )
        sort_order = (row["mx"] + 1) if row else 0
    execute_in_schema(
        SCHEMA,
        """INSERT INTO meal_photos (image_id, meal_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, meal_id, sort_order),
    )


def set_meal_photo_primary(meal_id: str, image_id: str) -> None:
    """Make image_id the primary (sort_order=0) photo; renumber all others."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT image_id FROM meal_photos WHERE meal_id = %s ORDER BY sort_order, created_at",
        (meal_id,),
    )
    ids = [r["image_id"] for r in rows]
    if image_id not in ids:
        return
    ordered = [image_id] + [i for i in ids if i != image_id]
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            for i, img_id in enumerate(ordered):
                cur.execute(
                    "UPDATE meal_photos SET sort_order=%s WHERE meal_id=%s AND image_id=%s",
                    (i, meal_id, img_id),
                )
        conn.commit()


def unlink_meal_photo(meal_id: str, image_id: str):
    execute_in_schema(
        SCHEMA,
        "DELETE FROM meal_photos WHERE meal_id = %s AND image_id = %s",
        (meal_id, image_id),
    )


# ---------------------------------------------------------------------------
# Discover — include / exclude filter engine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Component helpers
# ---------------------------------------------------------------------------

def find_meal_by_name(name: str) -> dict:
    """Exact case-insensitive match on meal name."""
    row = fetch_one_in_schema(SCHEMA,
        """SELECT *
           FROM meals
           WHERE LOWER(name) = LOWER(%s)
           ORDER BY updated_at DESC, created_at DESC, id DESC
           LIMIT 1""",
        (name.strip(),))
    return _meal_row(row) if row else {}


def find_meals_by_name_contains(keyword: str) -> list[dict]:
    """Find meals whose name contains the keyword (case-insensitive), shortest name first."""
    rows = fetch_all_in_schema(SCHEMA,
        "SELECT * FROM meals WHERE LOWER(name) LIKE LOWER(%s) ORDER BY LENGTH(name), name",
        (f"%{keyword.strip()}%",))
    return [_meal_row(r) for r in rows]


def get_meals_with_components(limit: int = 150) -> list[dict]:
    """Return all meals with their linked component names — used for LLM candidate matching."""
    rows = fetch_all_in_schema(SCHEMA,
        """SELECT m.id, m.name, m.tags,
                  COALESCE(
                      json_agg(
                          json_build_object('name', mc.name, 'role', mcl.role)
                          ORDER BY mcl.sort_order
                      ) FILTER (WHERE mc.id IS NOT NULL),
                      '[]'::json
                  ) AS components
           FROM meals m
           LEFT JOIN meal_component_links mcl ON mcl.meal_id = m.id
           LEFT JOIN meal_components mc ON mc.id = mcl.component_id
           GROUP BY m.id
           ORDER BY m.name
           LIMIT %s""",
        (limit,))
    result = []
    for r in rows:
        comps = r["components"]
        if isinstance(comps, str):
            try:
                comps = json.loads(comps)
            except Exception:
                comps = []
        result.append({
            "id": r["id"],
            "name": r["name"],
            "tags": _jslist(r.get("tags")),
            "components": comps or [],
        })
    return result


def find_component_by_name(name: str) -> dict:
    """Exact case-insensitive match on component name."""
    row = fetch_one_in_schema(SCHEMA,
        "SELECT * FROM meal_components WHERE LOWER(name) = LOWER(%s)", (name.strip(),))
    return _component_row(row) if row else {}


def get_meals_with_main(component_id: str) -> list[dict]:
    """Return meals where this component is linked with role='main'."""
    rows = fetch_all_in_schema(SCHEMA,
        """SELECT m.* FROM meals m
           JOIN meal_component_links mcl ON mcl.meal_id = m.id
           WHERE mcl.component_id = %s AND mcl.role = 'main'
           ORDER BY m.name""",
        (component_id,))
    return [_meal_row(r) for r in rows]


def link_component_to_meal(meal_id: str, component_id: str, role: str = "side") -> bool:
    """Add a component to a meal if not already linked. Returns True if a new link was created."""
    existing = fetch_one_in_schema(SCHEMA,
        "SELECT 1 FROM meal_component_links WHERE meal_id=%s AND component_id=%s",
        (meal_id, component_id))
    if existing:
        return False
    execute_in_schema(SCHEMA,
        """INSERT INTO meal_component_links (meal_id, component_id, role, sort_order)
           VALUES (%s, %s, %s,
               (SELECT COALESCE(MAX(sort_order), 0) + 1
                FROM meal_component_links WHERE meal_id=%s))""",
        (meal_id, component_id, role, meal_id))
    return True


# ---------------------------------------------------------------------------
# Dinner Log
# ---------------------------------------------------------------------------

def _meal_log_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "logged_date": row["logged_date"].isoformat() if row.get("logged_date") else "",
        "meal_type": row.get("meal_type") or "dinner",
        "meal_id": row.get("meal_id"),
        "meal_name": row.get("meal_name"),
        "description": row.get("description") or "",
        "logged_by": row.get("logged_by") or "",
        "notes": row.get("notes") or "",
        "logged_at": row["logged_at"].isoformat() if row.get("logged_at") else "",
    }


def create_meal_log(log_id: str, logged_date: str, description: str,
                    logged_by: str = "", meal_id: str = None,
                    notes: str = "", meal_type: str = "dinner") -> dict:
    row = execute_returning_in_schema(SCHEMA,
        """INSERT INTO meal_log (id, logged_date, meal_type, meal_id, description, logged_by, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (log_id, logged_date, meal_type, meal_id or None, description, logged_by, notes))
    entry = _meal_log_row(row) if row else {}
    if entry:
        digest_record(app_id="meals", entity_type="meal log entry", action="created",
                      entity_id=log_id, record=entry, by=logged_by,
                      context_hint="Focus on: date, meal type (dinner/lunch), what was eaten, meal name.")
    return entry


def get_meal_log_for_date(date_str: str, meal_type: str = "dinner") -> dict:
    """Return the meal log entry for a specific date and meal type, or {} if not logged."""
    row = fetch_one_in_schema(SCHEMA,
        """SELECT ml.*, m.name AS meal_name
           FROM meal_log ml
           LEFT JOIN meals m ON m.id = ml.meal_id
           WHERE ml.logged_date = %s AND ml.meal_type = %s""",
        (date_str, meal_type))
    return _meal_log_row(row) if row else {}


def get_meal_log(days: int = 30, meal_type: str = "") -> list[dict]:
    """Return meal log entries for the past N days, most recent first."""
    if meal_type.strip():
        rows = fetch_all_in_schema(SCHEMA,
            """SELECT ml.*, m.name AS meal_name
               FROM meal_log ml
               LEFT JOIN meals m ON m.id = ml.meal_id
               WHERE ml.logged_date >= CURRENT_DATE - %s AND ml.meal_type = %s
               ORDER BY ml.logged_date DESC, ml.meal_type""",
            (days, meal_type.strip()))
    else:
        rows = fetch_all_in_schema(SCHEMA,
            """SELECT ml.*, m.name AS meal_name
               FROM meal_log ml
               LEFT JOIN meals m ON m.id = ml.meal_id
               WHERE ml.logged_date >= CURRENT_DATE - %s
               ORDER BY ml.logged_date DESC, ml.meal_type""",
            (days,))
    return [_meal_log_row(r) for r in rows]


def discover_meals(filters: list[dict]) -> list[dict]:
    """Filter meals by include/exclude criteria.

    Each filter: {"type": "cuisine"|"effort"|"tag"|"component", "mode": "include"|"exclude", "value": str}

    Logic:
    - All INCLUDE filters are ANDed: meal must satisfy every one.
    - Each EXCLUDE filter independently eliminates matching meals.
    """
    include_filters = [f for f in filters if f.get("mode") == "include"]
    exclude_filters = [f for f in filters if f.get("mode") == "exclude"]

    where_parts = []
    params = []

    # --- INCLUDE filters ---
    for f in include_filters:
        ftype = f.get("type")
        val = f.get("value", "")
        if ftype == "cuisine":
            where_parts.append("m.tags @> %s::jsonb")
            params.append(json.dumps([_normalize_tag_value(val)]))
        elif ftype == "effort":
            where_parts.append("m.effort = %s")
            params.append((val or "").strip().lower())
        elif ftype == "tag":
            where_parts.append("m.tags @> %s::jsonb")
            params.append(json.dumps([_normalize_tag_value(val)]))
        elif ftype == "component":
            # meal must have at least one component link matching the component id or name
            where_parts.append(
                """EXISTS (
                    SELECT 1 FROM meal_component_links mcl
                    JOIN meal_components mc ON mc.id = mcl.component_id
                    WHERE mcl.meal_id = m.id
                      AND (mc.id = %s OR mc.name ILIKE %s)
                )""")
            params.append(val)
            params.append(f"%{val}%")

    # --- EXCLUDE filters ---
    for f in exclude_filters:
        ftype = f.get("type")
        val = f.get("value", "")
        if ftype == "cuisine":
            where_parts.append("NOT (m.tags @> %s::jsonb)")
            params.append(json.dumps([_normalize_tag_value(val)]))
        elif ftype == "effort":
            where_parts.append("m.effort != %s")
            params.append((val or "").strip().lower())
        elif ftype == "tag":
            where_parts.append("NOT (m.tags @> %s::jsonb)")
            params.append(json.dumps([_normalize_tag_value(val)]))
        elif ftype == "component":
            where_parts.append(
                """NOT EXISTS (
                    SELECT 1 FROM meal_component_links mcl
                    JOIN meal_components mc ON mc.id = mcl.component_id
                    WHERE mcl.meal_id = m.id
                      AND (mc.id = %s OR mc.name ILIKE %s)
                )""")
            params.append(val)
            params.append(f"%{val}%")

    sql = "SELECT m.* FROM meals m"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += " ORDER BY m.name"

    rows = fetch_all_in_schema(SCHEMA, sql, tuple(params))
    return [_meal_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "meal", "list_fn": list_meals, "context_hint": _MEAL_HINT},
    {"entity_type": "meal component", "list_fn": list_components, "context_hint": _COMPONENT_HINT},
]
