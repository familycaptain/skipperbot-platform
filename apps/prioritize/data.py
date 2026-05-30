"""Prioritize — data layer.

Owns CRUD on ``app_prioritize.priority_focus`` (focus slots) and the
backlog aggregator that pulls actionable items from every registered
provider.

Cross-app reads use the platform shims wherever possible
(``app_platform.reminders`` / ``schedules`` / ``todo``) so this app
has no hard dependency on the table layout of any other app. Goals,
projects, tasks, and users are still in ``public.*`` until the
goals/system apps are packaged — qualified explicitly so the
schema-isolated search_path doesn't surprise us.

Public surface — re-exported via ``app_platform.prioritize``:

- Focus slots: ``get_focus_slots``, ``set_focus``, ``promote_to_focus``,
  ``clear_focus``, ``clear_focus_by_source``, ``reorder_focus``,
  ``cleanup_stale_focus``
- Backlog: ``get_backlog``
- Focus-nag toggle: ``get_focus_nag_enabled``, ``set_focus_nag_enabled``
- Provider registries: ``register_backlog_provider``,
  ``register_activity_checker``
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    scoped_conn,
)
from data_layer.db import fetch_one, fetch_all, execute  # public.users + legacy goals/tasks reads
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)

SCHEMA = "app_prioritize"


# ---------------------------------------------------------------------------
# App-package provider registries
# ---------------------------------------------------------------------------
# App packages register callbacks at load time so the platform has no
# hard dependency on any particular app.

_backlog_providers: dict[str, Callable] = {}
# key (used as dict key in get_backlog result) -> fn(user_id) -> list[dict]

_activity_checkers: dict[str, Callable] = {}
# source_type -> fn(source_id) -> bool


def register_backlog_provider(key: str, fn: Callable):
    """Register an app-package backlog provider.

    Args:
        key:  Name used as the dict key in the backlog result (e.g. "auto_issues").
        fn:   Callable(user_id: str) -> list[dict].  Each dict should have at
              least ``source_type``, ``source_id``, and ``title``.
    """
    _backlog_providers[key] = fn
    logger.info("PRIORITIZE: Registered backlog provider '%s'", key)


def register_activity_checker(source_type: str, fn: Callable):
    """Register an app-package activity checker.

    Args:
        source_type:  The source_type string used in focus slots (e.g. "auto_issue").
        fn:           Callable(source_id: str) -> bool.  Return True if active.
    """
    _activity_checkers[source_type] = fn
    logger.info("PRIORITIZE: Registered activity checker for '%s'", source_type)


# ---------------------------------------------------------------------------
# Focus Slots
# ---------------------------------------------------------------------------

def get_focus_slots(user_id: str) -> list[dict]:
    """Get all focus slots for a user, ordered by slot_number."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM priority_focus WHERE user_id = %s ORDER BY slot_number",
        (user_id,),
    )
    return [_focus_row(r) for r in rows]


def set_focus(user_id: str, slot_number: int, source_type: str, source_id: str) -> dict | None:
    """Pin an item to a focus slot. Replaces whatever was in that slot."""
    pf_id = f"pf-{uuid.uuid4().hex[:8]}"
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            # Remove existing item from any slot for this user (in case it's already focused)
            cur.execute(
                "DELETE FROM priority_focus WHERE user_id = %s AND source_id = %s",
                (user_id, source_id),
            )
            # Remove whatever is in the target slot
            cur.execute(
                "DELETE FROM priority_focus WHERE user_id = %s AND slot_number = %s",
                (user_id, slot_number),
            )
            cur.execute(
                """INSERT INTO priority_focus (id, user_id, slot_number, source_type, source_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (pf_id, user_id, slot_number, source_type, source_id),
            )
        conn.commit()
    ensure_edge(pf_id, source_id, "pinned_to", "pinned_by")
    return {"id": pf_id, "user_id": user_id, "slot_number": slot_number,
            "source_type": source_type, "source_id": source_id}


def promote_to_focus(user_id: str, source_type: str, source_id: str) -> dict | None:
    """Promote an item to the next available focus slot (1, 2, or 3).
    Returns the new focus row or None if all slots are full.
    """
    slots = get_focus_slots(user_id)
    used = {s["slot_number"] for s in slots}
    for s in slots:
        if s["source_id"] == source_id:
            return s  # already in a slot
    for n in (1, 2, 3):
        if n not in used:
            return set_focus(user_id, n, source_type, source_id)
    return None  # all slots full


def clear_focus(user_id: str, slot_number: int) -> bool:
    """Remove an item from a focus slot (does NOT close it in the source app)."""
    return execute_in_schema(
        SCHEMA,
        "DELETE FROM priority_focus WHERE user_id = %s AND slot_number = %s",
        (user_id, slot_number),
    ) > 0


def clear_focus_by_source(user_id: str, source_id: str) -> bool:
    """Remove an item from focus by its source ID."""
    return execute_in_schema(
        SCHEMA,
        "DELETE FROM priority_focus WHERE user_id = %s AND source_id = %s",
        (user_id, source_id),
    ) > 0


def reorder_focus(user_id: str, ordered_source_ids: list[str]) -> bool:
    """Reorder focus slots. ordered_source_ids is a list of source IDs in desired order.
    The first becomes slot 1, second slot 2, etc.

    Uses a temporary negative slot_number to avoid UNIQUE constraint violations
    during the swap.
    """
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            for i, source_id in enumerate(ordered_source_ids[:3], start=1):
                cur.execute(
                    "UPDATE priority_focus SET slot_number = %s WHERE user_id = %s AND source_id = %s",
                    (-i, user_id, source_id),
                )
            for i, source_id in enumerate(ordered_source_ids[:3], start=1):
                cur.execute(
                    "UPDATE priority_focus SET slot_number = %s WHERE user_id = %s AND source_id = %s",
                    (i, user_id, source_id),
                )
        conn.commit()
    return True


def cleanup_stale_focus(user_id: str) -> int:
    """Remove focus items whose source no longer exists or is inactive.
    Returns the number of stale items removed.
    """
    slots = get_focus_slots(user_id)
    removed = 0
    for slot in slots:
        if not _source_is_active(slot["source_type"], slot["source_id"]):
            clear_focus(user_id, slot["slot_number"])
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Backlog — aggregate from source apps
# ---------------------------------------------------------------------------

def get_backlog(user_id: str) -> dict:
    """Get all actionable items for a user, grouped by source app.

    The goals_tree nests projects under goals and tasks under projects so the
    frontend can render a hierarchy with indentation.
    """
    result = {
        "goals_tree": _backlog_goals_tree(user_id),
        "reminders": _backlog_reminders(user_id),
        "nags": _backlog_nags(user_id),
        "schedules": _backlog_schedules(user_id),
        "todo": _backlog_todo(user_id),
    }
    # Append items from app-package providers
    for key, fn in _backlog_providers.items():
        try:
            result[key] = fn(user_id)
        except Exception as e:
            logger.error("PRIORITIZE: Backlog provider '%s' failed: %s", key, e)
            result[key] = []
    return result


def _backlog_goals_tree(user_id: str) -> list[dict]:
    """Build a nested goal → project → task hierarchy for the user.

    Goals / projects / tasks still live in ``public.*`` — the goals app
    hasn't been packaged yet. Queries are explicitly qualified so they
    don't depend on the current search_path.
    """
    # 1. All active tasks assigned to user
    task_rows = fetch_all(
        """SELECT t.id, t.name, t.status, t.stack_rank, t.priority, t.due_date,
                  t.project_id, p.owners as project_owners
           FROM app_goals.tasks t
           LEFT JOIN app_goals.projects p ON p.id = t.project_id
           WHERE t.status NOT IN ('done', 'cancelled')
             AND %s = ANY(t.assigned_to)
           ORDER BY t.stack_rank""",
        (user_id,),
    )

    task_project_ids = {r["project_id"] for r in task_rows if r.get("project_id")}

    # 2. All active projects the user owns OR that contain their tasks
    project_rows = fetch_all(
        """SELECT p.id, p.name, p.status, p.stack_rank, p.priority, p.due_date,
                  p.goal_id, p.owners
           FROM app_goals.projects p
           WHERE p.status NOT IN ('done', 'cancelled')
             AND (%s = ANY(p.owners) OR p.id = ANY(%s))
           ORDER BY p.stack_rank""",
        (user_id, list(task_project_ids) if task_project_ids else [""]),
    )

    project_goal_ids = {r["goal_id"] for r in project_rows if r.get("goal_id")}

    # 3. All active goals the user owns OR that contain relevant projects
    goal_rows = fetch_all(
        """SELECT id, name, status, stack_rank, target_date, owners
           FROM app_goals.goals
           WHERE status NOT IN ('done', 'cancelled')
             AND (%s = ANY(owners) OR id = ANY(%s))
           ORDER BY stack_rank""",
        (user_id, list(project_goal_ids) if project_goal_ids else [""]),
    )

    # Build lookup maps
    tasks_by_project = {}
    for r in task_rows:
        pid = r.get("project_id") or "_none"
        tasks_by_project.setdefault(pid, []).append({
            "source_type": "task", "source_id": r["id"],
            "title": r["name"], "status": r["status"],
            "priority": r["priority"], "stack_rank": r["stack_rank"],
            "due_date": r.get("due_date") or "",
            "project_id": r.get("project_id") or "",
            "owned_project": user_id in (r.get("project_owners") or []),
        })

    projects_by_goal = {}
    for r in project_rows:
        gid = r.get("goal_id") or "_none"
        projects_by_goal.setdefault(gid, []).append({
            "source_type": "project", "source_id": r["id"],
            "title": r["name"], "status": r["status"],
            "priority": r["priority"], "stack_rank": r["stack_rank"],
            "due_date": r.get("due_date") or "",
            "is_owner": user_id in (r.get("owners") or []),
            "tasks": tasks_by_project.get(r["id"], []),
        })

    tree = []
    seen_project_ids = set()
    seen_goal_ids = set()
    for r in goal_rows:
        seen_goal_ids.add(r["id"])
        projects = projects_by_goal.get(r["id"], [])
        for p in projects:
            seen_project_ids.add(p["source_id"])
        tree.append({
            "source_type": "goal", "source_id": r["id"],
            "title": r["name"], "status": r["status"],
            "stack_rank": r["stack_rank"],
            "detail": r.get("target_date") or "",
            "is_owner": user_id in (r.get("owners") or []),
            "projects": projects,
        })

    # Orphan projects (no goal match in tree) — shouldn't normally happen
    for gid, projs in projects_by_goal.items():
        if gid not in seen_goal_ids and gid != "_none":
            for p in projs:
                if p["source_id"] not in seen_project_ids:
                    tree.append(p)

    return tree


def _backlog_reminders(user_id: str) -> list[dict]:
    """Active non-nag reminders for user. Reads through the reminders shim."""
    from app_platform.reminders import get_user_reminders
    rows = get_user_reminders(user_id)
    return [
        {
            "source_type": "reminder",
            "source_id": r["id"],
            "title": r["message"],
            "detail": r["remind_at"] if isinstance(r.get("remind_at"), str)
                      else (r["remind_at"].isoformat() if r.get("remind_at") else ""),
            "recurrence": r.get("recurrence") or "",
            "sort_order": r.get("sort_order", 0),
        }
        for r in rows
        if r.get("active") and not r.get("nag")
    ]


def _backlog_nags(user_id: str) -> list[dict]:
    """Active nags for user. Reads through the reminders shim."""
    from app_platform.reminders import get_user_reminders
    rows = get_user_reminders(user_id)
    return [
        {
            "source_type": "nag",
            "source_id": r["id"],
            "title": r["message"],
            "detail": r.get("time_slot") or "",
            "sort_order": r.get("sort_order", 0),
        }
        for r in rows
        if r.get("active") and r.get("nag")
    ]


def _backlog_schedules(user_id: str) -> list[dict]:
    """Active schedules assigned to user that are overdue or due within 7 days.

    Delegated to the schedules shim's ``get_due_schedules`` helper —
    cross-app reads stay on the stable platform contract instead of
    reaching into ``app_schedules.*`` directly.
    """
    from datetime import datetime
    from app_platform.time import get_timezone
    from app_platform.schedules import get_due_schedules

    tz = get_timezone()
    now = datetime.now(tz)
    rows = get_due_schedules(
        assigned_to=user_id, days_ahead=7, exclude_reminder_backed=True,
    )
    result = []
    for r in rows:
        next_due_raw = r.get("next_due")
        # The shim returns ISO strings; coerce back to a datetime for comparison.
        next_due = None
        if isinstance(next_due_raw, str) and next_due_raw:
            try:
                next_due = datetime.fromisoformat(next_due_raw)
            except ValueError:
                next_due = None
        elif hasattr(next_due_raw, "isoformat"):
            next_due = next_due_raw

        overdue = False
        detail = ""
        if next_due is not None:
            overdue = next_due < now
            if overdue:
                delta = now - next_due
                days_overdue = round(delta.total_seconds() / 86400)
                detail = f"{days_overdue}d overdue" if days_overdue > 0 else "overdue"
            else:
                detail = next_due.strftime("%I:%M %p").lstrip("0") if next_due.hour or next_due.minute else "today"

        result.append({
            "source_type": "schedule", "source_id": r["id"],
            "title": r["title"],
            "category": r.get("category") or "general",
            "detail": detail,
            "overdue": overdue,
            "next_due": next_due.isoformat() if next_due else "",
        })
    return result


def _backlog_todo(user_id: str) -> list[dict]:
    """Top items from the user's default to-do list."""
    try:
        from apps.todo.store import get_todo_items
        result = get_todo_items(user_id)
        if not result or not result.get("items"):
            return []
        active = [i for i in result["items"] if not i.get("archived")]
        return [
            {
                "source_type": "todo",
                "source_id": item["id"],
                "title": item["text"],
                "detail": result.get("list_name", ""),
                "list_id": result.get("list_id", ""),
                "position": idx + 1,
            }
            for idx, item in enumerate(active[:10])
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Focus nag preference — stored on the platform-owned users table.
# ---------------------------------------------------------------------------

def get_focus_nag_enabled(user_id: str) -> bool:
    """Check if focus nag is enabled for a user."""
    row = fetch_one("SELECT focus_nag_enabled FROM public.users WHERE name = %s", (user_id,))
    return row["focus_nag_enabled"] if row else True


def set_focus_nag_enabled(user_id: str, enabled: bool) -> bool:
    """Toggle focus nag for a user."""
    return execute(
        "UPDATE public.users SET focus_nag_enabled = %s, updated_at = now() WHERE name = %s",
        (enabled, user_id),
    ) > 0


# ---------------------------------------------------------------------------
# Source activity check (for cleanup_stale_focus)
# ---------------------------------------------------------------------------

def _source_is_active(source_type: str, source_id: str) -> bool:
    """Check if a source item still exists and is active.

    Goals/projects/tasks still in public.*. Reminders/schedules
    go through their qualified app schemas (or, where the platform
    shim exposes a fitting helper, the shim).
    """
    if source_type == "goal":
        row = fetch_one("SELECT status FROM app_goals.goals WHERE id = %s", (source_id,))
        return bool(row and row["status"] not in ("done", "cancelled"))
    if source_type == "project":
        row = fetch_one("SELECT status FROM app_goals.projects WHERE id = %s", (source_id,))
        return bool(row and row["status"] not in ("done", "cancelled"))
    if source_type == "task":
        row = fetch_one("SELECT status FROM app_goals.tasks WHERE id = %s", (source_id,))
        return bool(row and row["status"] not in ("done", "cancelled"))
    if source_type in ("reminder", "nag"):
        from app_platform.reminders import get_reminder
        r = get_reminder(source_id)
        return bool(r and r.get("active"))
    if source_type == "schedule":
        from app_platform.schedules import get_schedule
        s = get_schedule(source_id)
        return bool(s and s.get("active"))
    if source_type == "todo":
        # Lists app owns list_items. Use its data-layer single-item read
        # rather than reaching into its schema.
        from apps.lists.data import get_item as _list_get_item
        item = _list_get_item(source_id)
        return bool(item and not item.get("archived"))
    # Fall through to app-package activity checkers
    checker = _activity_checkers.get(source_type)
    if checker:
        try:
            return checker(source_id)
        except Exception as e:
            logger.error("PRIORITIZE: Activity checker for '%s' failed: %s", source_type, e)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _focus_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "slot_number": row["slot_number"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
