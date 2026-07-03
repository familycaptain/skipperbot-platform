"""Home App — Schema-aware data layer
======================================
Home tables (home_tasks, home_task_log, home_task_categories, home_issues) live
in the app_home schema. Cross-schema references (public.images) use explicit
schema prefixes — never cross-schema FK constraints.
"""

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

SCHEMA = "app_home"

_TASK_HINT = (
    "Focus on: task name, category (HVAC/Plumbing/Exterior/etc), task type "
    "(recurring/adhoc), how often it recurs (interval_days), when it is next due, "
    "and any notes about the task."
)
_ISSUE_HINT = (
    "Focus on: issue title, location in the home, severity (minor/moderate/major/critical), "
    "current status, description of the problem, and any fix information."
)
_APPLIANCE_HINT = (
    "Focus on: appliance name, type, brand/model, serial number, location, "
    "purchase date and price, and warranty expiration."
)
_POLICY_HINT = (
    "Focus on: insurance provider, policy number, policy type (Home/Auto/Life/etc), "
    "coverage amount, premium and how often it is paid, deductible, renewal date, "
    "and what assets the policy covers."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


# ---------------------------------------------------------------------------
# Home Tasks (Maintenance Tab)
# ---------------------------------------------------------------------------

def _task_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "category": row.get("category") or "General",
        "task_type": row.get("task_type") or "recurring",
        "interval_days": row.get("interval_days"),
        "last_done_at": row["last_done_at"].isoformat() if row.get("last_done_at") else "",
        "next_due_at": row["next_due_at"].isoformat() if row.get("next_due_at") else "",
        "active": bool(row.get("active", True)),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _task_log_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "task_id": row.get("task_id") or "",
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else "",
        "completed_by": row.get("completed_by") or "",
        "notes": row.get("notes") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def create_task(task: dict) -> dict | None:
    """Insert a new home maintenance task."""
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO home_tasks (id, name, description, category, task_type,
                                    interval_days, last_done_at, next_due_at,
                                    active, notes, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            task["id"],
            task.get("name", ""),
            task.get("description", ""),
            task.get("category", "General"),
            task.get("task_type", "recurring"),
            task.get("interval_days"),
            task.get("last_done_at"),
            task.get("next_due_at"),
            task.get("active", True),
            task.get("notes", ""),
            task.get("created_by", ""),
            task.get("created_at", _now()),
            task.get("updated_at", _now()),
        ),
    )
    result = _task_row(row) if row else None
    if result:
        digest_record(app_id="home", entity_type="home maintenance task", action="created",
                      entity_id=result["id"], record=result,
                      by=task.get("created_by", ""), context_hint=_TASK_HINT)
    return result


def get_task(task_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM home_tasks WHERE id = %s", (task_id,))
    return _task_row(row) if row else None


def get_all_tasks(include_inactive: bool = False) -> list[dict]:
    if include_inactive:
        sql = "SELECT * FROM home_tasks ORDER BY next_due_at ASC NULLS LAST, name"
        rows = fetch_all_in_schema(SCHEMA, sql)
    else:
        sql = "SELECT * FROM home_tasks WHERE active = TRUE ORDER BY next_due_at ASC NULLS LAST, name"
        rows = fetch_all_in_schema(SCHEMA, sql)
    return [_task_row(r) for r in rows]


def get_tasks_by_category(category: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM home_tasks WHERE category = %s AND active = TRUE ORDER BY next_due_at ASC NULLS LAST",
        (category,),
    )
    return [_task_row(r) for r in rows]


def get_due_tasks(days_ahead: int = 7) -> list[dict]:
    """Return active tasks due within `days_ahead` days (or already overdue)."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM home_tasks
           WHERE active = TRUE
             AND next_due_at IS NOT NULL
             AND next_due_at <= CURRENT_DATE + %s
           ORDER BY next_due_at ASC""",
        (days_ahead,),
    )
    return [_task_row(r) for r in rows]


def search_tasks(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM home_tasks
           WHERE active = TRUE
             AND (name ILIKE %s OR description ILIKE %s OR category ILIKE %s OR notes ILIKE %s)
           ORDER BY next_due_at ASC NULLS LAST""",
        (pattern, pattern, pattern, pattern),
    )
    return [_task_row(r) for r in rows]


def update_task(task_id: str, updates: dict) -> bool:
    allowed = {
        "name", "description", "category", "task_type", "interval_days",
        "last_done_at", "next_due_at", "active", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(task_id)
    return execute_in_schema(
        SCHEMA, f"UPDATE home_tasks SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_task(task_id: str, by: str = "") -> bool:
    task = get_task(task_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM home_tasks WHERE id = %s", (task_id,)) > 0
    if ok and task:
        digest_record(app_id="home", entity_type="home maintenance task", action="deleted",
                      entity_id=task_id, record=task, by=by)
    return ok


def get_task_categories() -> list[str]:
    """Return all category names in configured sort order."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT name FROM home_task_categories ORDER BY sort_order, name",
    )
    return [r["name"] for r in rows if r.get("name")]


# ---------------------------------------------------------------------------
# Home Task Categories (configurable)
# ---------------------------------------------------------------------------

def _cat_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "color": row.get("color") or "slate",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def get_all_task_categories() -> list[dict]:
    """Return all configured task categories with full detail."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM home_task_categories ORDER BY sort_order, name",
    )
    return [_cat_row(r) for r in rows]


def create_task_category(cat_id: str, name: str, color: str = "slate") -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO home_task_categories (id, name, color, sort_order)
           VALUES (%s, %s, %s, COALESCE((SELECT MAX(sort_order)+1 FROM home_task_categories), 0))
           RETURNING *""",
        (cat_id, name, color),
    )
    return _cat_row(row) if row else None


def update_task_category(cat_id: str, updates: dict) -> bool:
    allowed = {"name", "color", "sort_order"}
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    vals.append(cat_id)
    return execute_in_schema(
        SCHEMA, f"UPDATE home_task_categories SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_task_category(cat_id: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM home_task_categories WHERE id = %s", (cat_id,)) > 0


# ---------------------------------------------------------------------------
# Home Task Log (completion history)
# ---------------------------------------------------------------------------

def complete_task(
    task_id: str,
    completed_at: str = "",
    completed_by: str = "",
    notes: str = "",
    log_id: str = "",
) -> dict:
    """Mark a task as done: creates log entry + advances next_due for recurring tasks."""
    import uuid
    from datetime import date, timedelta

    task = get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    done_date = completed_at or date.today().isoformat()
    entry_id = log_id or f"hmtl-{uuid.uuid4().hex[:8]}"

    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            # Insert log entry
            cur.execute("""
                INSERT INTO home_task_log (id, task_id, completed_at, completed_by, notes, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (entry_id, task_id, done_date, completed_by, notes, _now()))

            # Update task state
            if task["task_type"] == "recurring" and task.get("interval_days"):
                d = date.fromisoformat(done_date)
                next_due = (d + timedelta(days=task["interval_days"])).isoformat()
                cur.execute("""
                    UPDATE home_tasks
                    SET last_done_at = %s, next_due_at = %s, updated_at = %s
                    WHERE id = %s
                """, (done_date, next_due, _now(), task_id))
            else:
                # Ad-hoc: mark inactive (completed, no recurrence)
                cur.execute("""
                    UPDATE home_tasks
                    SET last_done_at = %s, active = FALSE, updated_at = %s
                    WHERE id = %s
                """, (done_date, _now(), task_id))
        conn.commit()

    updated = get_task(task_id)
    log_entries = get_task_log(task_id, limit=1)
    if updated:
        completion_record = dict(updated)
        completion_record["completed_at"] = done_date
        completion_record["completed_by"] = completed_by
        if notes:
            completion_record["completion_notes"] = notes
        digest_record(app_id="home", entity_type="home maintenance task", action="completed",
                      entity_id=task_id, record=completion_record,
                      by=completed_by, context_hint=_TASK_HINT)
    return {
        "task": updated,
        "log_entry": log_entries[0] if log_entries else {},
    }


def get_task_log(task_id: str, limit: int = 50) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM home_task_log WHERE task_id = %s ORDER BY completed_at DESC, created_at DESC LIMIT %s",
        (task_id, limit),
    )
    return [_task_log_row(r) for r in rows]


def get_recent_log(limit: int = 20) -> list[dict]:
    """Get most recent completions across all tasks."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT l.*, t.name as task_name, t.category
           FROM home_task_log l
           JOIN home_tasks t ON t.id = l.task_id
           ORDER BY l.completed_at DESC, l.created_at DESC
           LIMIT %s""",
        (limit,),
    )
    result = []
    for r in rows:
        entry = _task_log_row(r)
        entry["task_name"] = r.get("task_name") or ""
        entry["category"] = r.get("category") or ""
        result.append(entry)
    return result


def delete_log_entry(log_id: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM home_task_log WHERE id = %s", (log_id,)) > 0


# ---------------------------------------------------------------------------
# Home Issues (Issues Tab)
# ---------------------------------------------------------------------------

def _issue_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "location": row.get("location") or "",
        "sub_location": row.get("sub_location") or "",
        "category": row.get("category") or "General",
        "severity": row.get("severity") or "minor",
        "status": row.get("status") or "open",
        "date_noticed": row["date_noticed"].isoformat() if row.get("date_noticed") else "",
        "date_fixed": row["date_fixed"].isoformat() if row.get("date_fixed") else "",
        "fix_description": row.get("fix_description") or "",
        "cost": float(row["cost"]) if row.get("cost") is not None else None,
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def create_issue(issue: dict) -> dict | None:
    """Insert a new home issue."""
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO home_issues (id, title, description, location, sub_location,
                                    category, severity, status, date_noticed,
                                    notes, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            issue["id"],
            issue.get("title", ""),
            issue.get("description", ""),
            issue.get("location", ""),
            issue.get("sub_location", ""),
            issue.get("category", "General"),
            issue.get("severity", "minor"),
            issue.get("status", "open"),
            issue.get("date_noticed") or None,
            issue.get("notes", ""),
            issue.get("created_by", ""),
            issue.get("created_at", _now()),
            issue.get("updated_at", _now()),
        ),
    )
    result = _issue_row(row) if row else None
    if result:
        digest_record(app_id="home", entity_type="home issue", action="created",
                      entity_id=result["id"], record=result,
                      by=issue.get("created_by", ""), context_hint=_ISSUE_HINT)
    return result


def get_issue(issue_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM home_issues WHERE id = %s", (issue_id,))
    return _issue_row(row) if row else None


def get_all_issues(status: str = None, location: str = None, limit: int = 200) -> list[dict]:
    clauses, params = [], []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if location:
        clauses.append("location ILIKE %s")
        params.append(location)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT * FROM home_issues
            {where}
            ORDER BY
                CASE WHEN status IN ('open','in_progress') THEN 0 ELSE 1 END,
                CASE WHEN severity = 'critical' THEN 0
                     WHEN severity = 'major'    THEN 1
                     WHEN severity = 'moderate' THEN 2
                     ELSE 3 END,
                created_at DESC
            LIMIT %s""",
        tuple(params),
    )
    return [_issue_row(r) for r in rows]


def get_open_issues() -> list[dict]:
    """All open/in_progress issues ordered by severity."""
    return get_all_issues(status=None)


def update_issue(issue_id: str, updates: dict, by: str = "") -> bool:
    allowed = {
        "title", "description", "location", "sub_location", "category",
        "severity", "status", "date_noticed", "date_fixed",
        "fix_description", "cost", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(issue_id)
    ok = execute_in_schema(
        SCHEMA, f"UPDATE home_issues SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_issue(issue_id)
        if updated:
            digest_record(app_id="home", entity_type="home issue", action="updated",
                          entity_id=issue_id, record=updated, by=by,
                          context_hint=_ISSUE_HINT)
    return ok


def delete_issue(issue_id: str, by: str = "") -> bool:
    issue = get_issue(issue_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM home_issues WHERE id = %s", (issue_id,)) > 0
    if ok and issue:
        digest_record(app_id="home", entity_type="home issue", action="deleted",
                      entity_id=issue_id, record=issue, by=by)
    return ok


def get_issue_locations() -> list[str]:
    """Distinct locations that have issues."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT DISTINCT location FROM home_issues WHERE location != '' ORDER BY location",
    )
    return [r["location"] for r in rows if r.get("location")]


def get_all_locations_merged() -> list[dict]:
    """Every distinct location across issues (both `location` and `sub_location`), as
    {name} dicts — used to populate the location filter in the Issues UI. The route
    references this; its absence 500'd GET /issues."""
    rows = fetch_all_in_schema(SCHEMA, "SELECT location, sub_location FROM home_issues")
    names = set()
    for r in rows:
        for v in (r.get("location"), r.get("sub_location")):
            if v and v.strip():
                names.add(v.strip())
    return [{"name": n} for n in sorted(names)]


# ---------------------------------------------------------------------------
# Home Issue Images (soft FK to public.images)
# ---------------------------------------------------------------------------

def get_issue_images(issue_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, hii.sort_order FROM public.images i
           JOIN home_issue_images hii ON hii.image_id = i.id
           WHERE hii.issue_id = %s
           ORDER BY hii.sort_order, i.created_at""",
        (issue_id,),
    )
    return [_image_row(r) for r in rows]


def link_issue_image(issue_id: str, image_id: str, sort_order: int = 0):
    execute_in_schema(
        SCHEMA,
        """INSERT INTO home_issue_images (image_id, issue_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, issue_id, sort_order),
    )


def unlink_issue_image(issue_id: str, image_id: str):
    execute_in_schema(
        SCHEMA,
        "DELETE FROM home_issue_images WHERE issue_id = %s AND image_id = %s",
        (issue_id, image_id),
    )


# ---------------------------------------------------------------------------
# Home Appliances (Appliances Tab)
# ---------------------------------------------------------------------------

def _appliance_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "appliance_type": row.get("appliance_type") or "General",
        "brand": row.get("brand") or "",
        "model": row.get("model") or "",
        "serial_number": row.get("serial_number") or "",
        "location": row.get("location") or "",
        "purchase_date": row["purchase_date"].isoformat() if row.get("purchase_date") else "",
        "purchase_price": float(row["purchase_price"]) if row.get("purchase_price") is not None else None,
        "warranty_expires": row["warranty_expires"].isoformat() if row.get("warranty_expires") else "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def create_appliance(appliance: dict) -> dict | None:
    """Insert a new home appliance."""
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO home_appliances (id, name, appliance_type, brand, model,
                                        serial_number, location, purchase_date,
                                        purchase_price, warranty_expires, notes,
                                        created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            appliance["id"],
            appliance.get("name", ""),
            appliance.get("appliance_type", "General"),
            appliance.get("brand", ""),
            appliance.get("model", ""),
            appliance.get("serial_number", ""),
            appliance.get("location", ""),
            appliance.get("purchase_date") or None,
            appliance.get("purchase_price"),
            appliance.get("warranty_expires") or None,
            appliance.get("notes", ""),
            appliance.get("created_by", ""),
            appliance.get("created_at", _now()),
            appliance.get("updated_at", _now()),
        ),
    )
    result = _appliance_row(row) if row else None
    if result:
        digest_record(app_id="home", entity_type="home appliance", action="created",
                      entity_id=result["id"], record=result,
                      by=appliance.get("created_by", ""), context_hint=_APPLIANCE_HINT)
    return result


def get_appliance(appliance_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM home_appliances WHERE id = %s", (appliance_id,))
    return _appliance_row(row) if row else None


def get_all_appliances(appliance_type: str = None, location: str = None, limit: int = 200) -> list[dict]:
    clauses, params = [], []
    if appliance_type:
        clauses.append("appliance_type = %s")
        params.append(appliance_type)
    if location:
        clauses.append("location ILIKE %s")
        params.append(location)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT * FROM home_appliances
            {where}
            ORDER BY created_at DESC
            LIMIT %s""",
        tuple(params),
    )
    return [_appliance_row(r) for r in rows]


def search_appliances(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM home_appliances
           WHERE name ILIKE %s OR appliance_type ILIKE %s OR brand ILIKE %s
              OR model ILIKE %s OR serial_number ILIKE %s OR location ILIKE %s
              OR notes ILIKE %s
           ORDER BY created_at DESC""",
        (pattern, pattern, pattern, pattern, pattern, pattern, pattern),
    )
    return [_appliance_row(r) for r in rows]


def update_appliance(appliance_id: str, updates: dict, by: str = "") -> bool:
    allowed = {
        "name", "appliance_type", "brand", "model", "serial_number",
        "location", "purchase_date", "purchase_price", "warranty_expires", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(appliance_id)
    ok = execute_in_schema(
        SCHEMA, f"UPDATE home_appliances SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_appliance(appliance_id)
        if updated:
            digest_record(app_id="home", entity_type="home appliance", action="updated",
                          entity_id=appliance_id, record=updated, by=by,
                          context_hint=_APPLIANCE_HINT)
    return ok


def delete_appliance(appliance_id: str, by: str = "") -> bool:
    appliance = get_appliance(appliance_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM home_appliances WHERE id = %s", (appliance_id,)) > 0
    if ok and appliance:
        digest_record(app_id="home", entity_type="home appliance", action="deleted",
                      entity_id=appliance_id, record=appliance, by=by)
    return ok


def get_appliance_types() -> list[str]:
    """Distinct appliance types in use."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT DISTINCT appliance_type FROM home_appliances WHERE appliance_type != '' ORDER BY appliance_type",
    )
    return [r["appliance_type"] for r in rows if r.get("appliance_type")]


def get_appliance_locations() -> list[str]:
    """Distinct locations that have appliances."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT DISTINCT location FROM home_appliances WHERE location != '' ORDER BY location",
    )
    return [r["location"] for r in rows if r.get("location")]


# ---------------------------------------------------------------------------
# Home Appliance Images (soft FK to public.images)
# ---------------------------------------------------------------------------

def get_appliance_images(appliance_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, hai.sort_order FROM public.images i
           JOIN home_appliance_images hai ON hai.image_id = i.id
           WHERE hai.appliance_id = %s
           ORDER BY hai.sort_order, i.created_at""",
        (appliance_id,),
    )
    return [_image_row(r) for r in rows]


def link_appliance_image(appliance_id: str, image_id: str, sort_order: int = 0):
    execute_in_schema(
        SCHEMA,
        """INSERT INTO home_appliance_images (image_id, appliance_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, appliance_id, sort_order),
    )


def unlink_appliance_image(appliance_id: str, image_id: str):
    execute_in_schema(
        SCHEMA,
        "DELETE FROM home_appliance_images WHERE appliance_id = %s AND image_id = %s",
        (appliance_id, image_id),
    )


# ---------------------------------------------------------------------------
# Home Insurance Policies (Insurance Tab)
# ---------------------------------------------------------------------------

def _policy_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "provider": row.get("provider") or "",
        "policy_number": row.get("policy_number") or "",
        "policy_type": row.get("policy_type") or "Home",
        "coverage_amount": float(row["coverage_amount"]) if row.get("coverage_amount") is not None else None,
        "premium": float(row["premium"]) if row.get("premium") is not None else None,
        "premium_period": row.get("premium_period") or "annual",
        "deductible": float(row["deductible"]) if row.get("deductible") is not None else None,
        "renewal_date": row["renewal_date"].isoformat() if row.get("renewal_date") else "",
        "insured_assets": row.get("insured_assets") or "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def create_policy(policy: dict) -> dict | None:
    """Insert a new home insurance policy."""
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO home_insurance_policies (id, provider, policy_number, policy_type,
                                                coverage_amount, premium, premium_period,
                                                deductible, renewal_date, insured_assets,
                                                notes, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            policy["id"],
            policy.get("provider", ""),
            policy.get("policy_number", ""),
            policy.get("policy_type", "Home"),
            policy.get("coverage_amount"),
            policy.get("premium"),
            policy.get("premium_period", "annual"),
            policy.get("deductible"),
            policy.get("renewal_date") or None,
            policy.get("insured_assets", ""),
            policy.get("notes", ""),
            policy.get("created_by", ""),
            policy.get("created_at", _now()),
            policy.get("updated_at", _now()),
        ),
    )
    result = _policy_row(row) if row else None
    if result:
        digest_record(app_id="home", entity_type="home insurance policy", action="created",
                      entity_id=result["id"], record=result,
                      by=policy.get("created_by", ""), context_hint=_POLICY_HINT)
    return result


def get_policy(policy_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM home_insurance_policies WHERE id = %s", (policy_id,))
    return _policy_row(row) if row else None


def get_all_policies(policy_type: str = None, limit: int = 200) -> list[dict]:
    clauses, params = [], []
    if policy_type:
        clauses.append("policy_type = %s")
        params.append(policy_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT * FROM home_insurance_policies
            {where}
            ORDER BY renewal_date ASC NULLS LAST, created_at DESC
            LIMIT %s""",
        tuple(params),
    )
    return [_policy_row(r) for r in rows]


def search_policies(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM home_insurance_policies
           WHERE provider ILIKE %s OR policy_number ILIKE %s OR policy_type ILIKE %s
              OR insured_assets ILIKE %s OR notes ILIKE %s
           ORDER BY renewal_date ASC NULLS LAST, created_at DESC""",
        (pattern, pattern, pattern, pattern, pattern),
    )
    return [_policy_row(r) for r in rows]


def update_policy(policy_id: str, updates: dict, by: str = "") -> bool:
    allowed = {
        "provider", "policy_number", "policy_type", "coverage_amount", "premium",
        "premium_period", "deductible", "renewal_date", "insured_assets", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(policy_id)
    ok = execute_in_schema(
        SCHEMA, f"UPDATE home_insurance_policies SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_policy(policy_id)
        if updated:
            digest_record(app_id="home", entity_type="home insurance policy", action="updated",
                          entity_id=policy_id, record=updated, by=by,
                          context_hint=_POLICY_HINT)
    return ok


def delete_policy(policy_id: str, by: str = "") -> bool:
    policy = get_policy(policy_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM home_insurance_policies WHERE id = %s", (policy_id,)) > 0
    if ok and policy:
        digest_record(app_id="home", entity_type="home insurance policy", action="deleted",
                      entity_id=policy_id, record=policy, by=by)
    return ok


def get_policy_types() -> list[str]:
    """Distinct policy types in use."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT DISTINCT policy_type FROM home_insurance_policies WHERE policy_type != '' ORDER BY policy_type",
    )
    return [r["policy_type"] for r in rows if r.get("policy_type")]


# ---------------------------------------------------------------------------
# Home Insurance Policy Images (soft FK to public.images)
# ---------------------------------------------------------------------------

def get_policy_images(policy_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, hipi.sort_order FROM public.images i
           JOIN home_insurance_policy_images hipi ON hipi.image_id = i.id
           WHERE hipi.policy_id = %s
           ORDER BY hipi.sort_order, i.created_at""",
        (policy_id,),
    )
    return [_image_row(r) for r in rows]


def link_policy_image(policy_id: str, image_id: str, sort_order: int = 0):
    execute_in_schema(
        SCHEMA,
        """INSERT INTO home_insurance_policy_images (image_id, policy_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, policy_id, sort_order),
    )


def unlink_policy_image(policy_id: str, image_id: str):
    execute_in_schema(
        SCHEMA,
        "DELETE FROM home_insurance_policy_images WHERE policy_id = %s AND image_id = %s",
        (policy_id, image_id),
    )


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "home maintenance task",
     "list_fn": lambda: get_all_tasks(include_inactive=True),
     "context_hint": _TASK_HINT},
    {"entity_type": "home issue",
     "list_fn": get_all_issues,
     "context_hint": _ISSUE_HINT},
    {"entity_type": "home appliance",
     "list_fn": get_all_appliances,
     "context_hint": _APPLIANCE_HINT},
    {"entity_type": "home insurance policy",
     "list_fn": get_all_policies,
     "context_hint": _POLICY_HINT},
]
