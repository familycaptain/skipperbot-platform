"""Goals — data layer (SQL CRUD).

Owns reads + writes for the ``app_goals.goals/projects/tasks`` tables.
This is the low-level persistence layer; higher-level business logic
(orchestration, ranking, nag refresh, formatting) lives in
``apps/goals/store.py``.

Every public mutation calls ``platform.memory.digest_record`` so the
records are searchable from chat — see ``specs/MEMORY.md`` for why this
is non-negotiable.

Ported from ``data_layer/goals.py`` for sub-chunk 3c. Functionally
identical; only difference is routing all queries through the
``*_in_schema`` helpers from ``app_platform.db`` so the goals app's
tables land in (and read from) the ``app_goals`` schema.
"""

from __future__ import annotations

import logging

from psycopg2.extras import Json

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record
from data_layer.links import ensure_edge  # platform infra — links live in public.*


logger = logging.getLogger(__name__)

SCHEMA = "app_goals"


# ---------------------------------------------------------------------------
# Memory-digestion hints — what the dumb-model fact extractor should focus on
# when ingesting a goal/project/task record into searchable memories.
# See specs/MEMORY.md.
# ---------------------------------------------------------------------------

_GOAL_HINT = (
    "Focus on: goal name, owners, status, target date, definition of done, and notes. "
    "Goals are high-level family or personal objectives."
)
_PROJECT_HINT = (
    "Focus on: project name, parent goal, owners, due date, status, priority, "
    "definition of done, and notes. Projects are the main work units under a goal."
)
_TASK_HINT = (
    "Focus on: task name, parent project, assigned users, due date, status, priority, "
    "definition of done, and notes."
)


# ---------------------------------------------------------------------------
# Backfill registry — read by scripts/backfill_app_memories.py to walk every
# stored row and re-digest it (useful after first install or schema changes).
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES = [
    {
        "entity_type": "goal",
        "list_fn": lambda: list_entities("g-"),
        "context_hint": _GOAL_HINT,
    },
    {
        "entity_type": "project",
        "list_fn": lambda: list_entities("p-"),
        "context_hint": _PROJECT_HINT,
    },
    {
        "entity_type": "task",
        "list_fn": lambda: list_entities("t-"),
        "context_hint": _TASK_HINT,
    },
]


# ---------------------------------------------------------------------------
# Row → dict converters (preserve the shape that store.py / tools.py expect)
# ---------------------------------------------------------------------------

def _goal_row_to_dict(row: dict) -> dict:
    project_ids = [
        r["id"] for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT id FROM projects WHERE goal_id = %s ORDER BY stack_rank",
            (row["id"],),
        )
    ]
    return {
        "id": row["id"],
        "name": row["name"],
        "owners": row["owners"] or [],
        "collaborators": row.get("collaborators") or [],
        "target_date": row["target_date"] or "",
        "status": row["status"],
        "stack_rank": row["stack_rank"],
        "notes": row["notes"] or "",
        "definition_of_done": row.get("definition_of_done") or "",
        "history": row["history"] or [],
        "artifacts": row["artifacts"] or [],
        "created_by": row["created_by"] or "",
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "projects": project_ids,
    }


def _project_row_to_dict(row: dict) -> dict:
    task_ids = [
        r["id"] for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT id FROM tasks WHERE project_id = %s AND parent_task_id IS NULL "
            "ORDER BY stack_rank",
            (row["id"],),
        )
    ]
    return {
        "id": row["id"],
        "name": row["name"],
        "goal_id": row["goal_id"],
        "owners": row["owners"] or [],
        "due_date": row["due_date"] or "",
        "priority": row["priority"],
        "status": row["status"],
        "stack_rank": row["stack_rank"],
        "notes": row["notes"] or "",
        "definition_of_done": row.get("definition_of_done") or "",
        "history": row["history"] or [],
        "artifacts": row["artifacts"] or [],
        "auto_nag": row["auto_nag"],
        "trello": row["trello"],
        "pm_cadence_minutes": row.get("pm_cadence_minutes"),
        "created_by": row["created_by"] or "",
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "tasks": task_ids,
    }


def _task_row_to_dict(row: dict) -> dict:
    subtask_ids = [
        r["id"] for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT id FROM tasks WHERE parent_task_id = %s ORDER BY stack_rank",
            (row["id"],),
        )
    ]
    return {
        "id": row["id"],
        "name": row["name"],
        "project_id": row["project_id"],
        "parent_task_id": row["parent_task_id"],
        "subtasks": subtask_ids,
        "assigned_to": row["assigned_to"] or [],
        "due_date": row["due_date"] or "",
        "priority": row["priority"],
        "status": row["status"],
        "stack_rank": row["stack_rank"],
        "depends_on": row["depends_on"] or [],
        "trello_card_id": row["trello_card_id"] or "",
        "trello_list": row["trello_list"] or "",
        "trello_linked": row["trello_linked"],
        "notes": row["notes"] or "",
        "definition_of_done": row.get("definition_of_done") or "",
        "history": row["history"] or [],
        "artifacts": row["artifacts"] or [],
        "created_by": row["created_by"] or "",
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
    }


# ---------------------------------------------------------------------------
# Load operations
# ---------------------------------------------------------------------------

def load_entity(entity_id: str) -> dict | None:
    """Load any goal/project/task by ID. Returns dict or None."""
    if entity_id.startswith("g-"):
        row = fetch_one_in_schema(SCHEMA, "SELECT * FROM goals WHERE id = %s", (entity_id,))
        return _goal_row_to_dict(row) if row else None
    elif entity_id.startswith("p-"):
        row = fetch_one_in_schema(SCHEMA, "SELECT * FROM projects WHERE id = %s", (entity_id,))
        return _project_row_to_dict(row) if row else None
    elif entity_id.startswith("t-"):
        row = fetch_one_in_schema(SCHEMA, "SELECT * FROM tasks WHERE id = %s", (entity_id,))
        return _task_row_to_dict(row) if row else None
    return None


def list_entities(prefix: str) -> list[dict]:
    """Load all entities with a given ID prefix ('g-', 'p-', 't-')."""
    if prefix == "g-":
        rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM goals ORDER BY stack_rank")
        return [_goal_row_to_dict(r) for r in rows]
    elif prefix == "p-":
        rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM projects ORDER BY stack_rank")
        return [_project_row_to_dict(r) for r in rows]
    elif prefix == "t-":
        rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM tasks ORDER BY stack_rank")
        return [_task_row_to_dict(r) for r in rows]
    return []


# ---------------------------------------------------------------------------
# Save operations — upserts. digest_record is fired by save_entity() after
# the row is persisted; the underlying _save_* helpers don't digest so we
# can use them from external migration scripts without flooding the memory
# queue.
# ---------------------------------------------------------------------------

def save_entity(entity: dict):
    """Upsert a goal/project/task and fire a digest_record."""
    eid = entity["id"]
    is_new = load_entity(eid) is None
    if eid.startswith("g-"):
        _save_goal(entity)
        entity_type, hint = "goal", _GOAL_HINT
    elif eid.startswith("p-"):
        _save_project(entity)
        entity_type, hint = "project", _PROJECT_HINT
    elif eid.startswith("t-"):
        _save_task(entity)
        entity_type, hint = "task", _TASK_HINT
    else:
        return
    saved = load_entity(eid)
    if saved:
        digest_record(
            app_id="goals",
            entity_type=entity_type,
            action="created" if is_new else "updated",
            entity_id=eid,
            record=saved,
            by=entity.get("created_by", ""),
            context_hint=hint,
        )


def _save_goal(g: dict):
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goals (id, name, owners, collaborators, target_date, status,
                                   stack_rank, notes, definition_of_done, history, artifacts,
                                   created_by, created_at)
                VALUES (%(id)s, %(name)s, %(owners)s, %(collaborators)s, %(target_date)s,
                        %(status)s, %(stack_rank)s, %(notes)s, %(definition_of_done)s,
                        %(history)s, %(artifacts)s, %(created_by)s, %(created_at)s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    owners = EXCLUDED.owners,
                    collaborators = EXCLUDED.collaborators,
                    target_date = EXCLUDED.target_date,
                    status = EXCLUDED.status,
                    stack_rank = EXCLUDED.stack_rank,
                    notes = EXCLUDED.notes,
                    definition_of_done = EXCLUDED.definition_of_done,
                    history = EXCLUDED.history,
                    artifacts = EXCLUDED.artifacts
                """,
                {
                    "id": g["id"],
                    "name": g["name"],
                    "owners": g.get("owners", []),
                    "collaborators": g.get("collaborators", []),
                    "target_date": g.get("target_date", ""),
                    "status": g.get("status", "not_started"),
                    "stack_rank": g.get("stack_rank", 0),
                    "notes": g.get("notes", ""),
                    "definition_of_done": g.get("definition_of_done", ""),
                    "history": Json(g.get("history", [])),
                    "artifacts": g.get("artifacts", []),
                    "created_by": g.get("created_by", ""),
                    "created_at": g.get("created_at", ""),
                },
            )
        conn.commit()


def _save_project(p: dict):
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (id, name, goal_id, owners, due_date, priority,
                                      status, stack_rank, notes, definition_of_done, history,
                                      artifacts, auto_nag, trello, pm_cadence_minutes,
                                      created_by, created_at)
                VALUES (%(id)s, %(name)s, %(goal_id)s, %(owners)s, %(due_date)s,
                        %(priority)s, %(status)s, %(stack_rank)s, %(notes)s,
                        %(definition_of_done)s, %(history)s, %(artifacts)s, %(auto_nag)s,
                        %(trello)s, %(pm_cadence_minutes)s, %(created_by)s, %(created_at)s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    goal_id = EXCLUDED.goal_id,
                    owners = EXCLUDED.owners,
                    due_date = EXCLUDED.due_date,
                    priority = EXCLUDED.priority,
                    status = EXCLUDED.status,
                    stack_rank = EXCLUDED.stack_rank,
                    notes = EXCLUDED.notes,
                    definition_of_done = EXCLUDED.definition_of_done,
                    history = EXCLUDED.history,
                    artifacts = EXCLUDED.artifacts,
                    auto_nag = EXCLUDED.auto_nag,
                    trello = EXCLUDED.trello,
                    pm_cadence_minutes = EXCLUDED.pm_cadence_minutes
                """,
                {
                    "id": p["id"],
                    "name": p["name"],
                    "goal_id": p.get("goal_id", ""),
                    "owners": p.get("owners", []),
                    "due_date": p.get("due_date", ""),
                    "priority": p.get("priority", "medium"),
                    "status": p.get("status", "not_started"),
                    "stack_rank": p.get("stack_rank", 0),
                    "notes": p.get("notes", ""),
                    "definition_of_done": p.get("definition_of_done", ""),
                    "history": Json(p.get("history", [])),
                    "artifacts": p.get("artifacts", []),
                    "auto_nag": Json(p.get("auto_nag")) if p.get("auto_nag") else None,
                    "trello": Json(p.get("trello")) if p.get("trello") else None,
                    "pm_cadence_minutes": p.get("pm_cadence_minutes"),
                    "created_by": p.get("created_by", ""),
                    "created_at": p.get("created_at", ""),
                },
            )
        conn.commit()
    if p.get("goal_id"):
        ensure_edge(p["id"], p["goal_id"], "child_of", "parent_of")


def _save_task(t: dict):
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (id, name, project_id, parent_task_id, assigned_to,
                                   due_date, priority, status, stack_rank, depends_on,
                                   trello_card_id, trello_list, trello_linked,
                                   notes, definition_of_done, history, artifacts,
                                   created_by, created_at)
                VALUES (%(id)s, %(name)s, %(project_id)s, %(parent_task_id)s,
                        %(assigned_to)s, %(due_date)s, %(priority)s, %(status)s,
                        %(stack_rank)s, %(depends_on)s, %(trello_card_id)s,
                        %(trello_list)s, %(trello_linked)s, %(notes)s,
                        %(definition_of_done)s, %(history)s, %(artifacts)s,
                        %(created_by)s, %(created_at)s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    project_id = EXCLUDED.project_id,
                    parent_task_id = EXCLUDED.parent_task_id,
                    assigned_to = EXCLUDED.assigned_to,
                    due_date = EXCLUDED.due_date,
                    priority = EXCLUDED.priority,
                    status = EXCLUDED.status,
                    stack_rank = EXCLUDED.stack_rank,
                    depends_on = EXCLUDED.depends_on,
                    trello_card_id = EXCLUDED.trello_card_id,
                    trello_list = EXCLUDED.trello_list,
                    trello_linked = EXCLUDED.trello_linked,
                    notes = EXCLUDED.notes,
                    definition_of_done = EXCLUDED.definition_of_done,
                    history = EXCLUDED.history,
                    artifacts = EXCLUDED.artifacts
                """,
                {
                    "id": t["id"],
                    "name": t["name"],
                    "project_id": t.get("project_id", ""),
                    "parent_task_id": t.get("parent_task_id"),
                    "assigned_to": t.get("assigned_to", []),
                    "due_date": t.get("due_date", ""),
                    "priority": t.get("priority", "medium"),
                    "status": t.get("status", "not_started"),
                    "stack_rank": t.get("stack_rank", 0),
                    "depends_on": t.get("depends_on", []),
                    "trello_card_id": t.get("trello_card_id", ""),
                    "trello_list": t.get("trello_list", ""),
                    "trello_linked": bool(t.get("trello_linked", False)),
                    "notes": t.get("notes", ""),
                    "definition_of_done": t.get("definition_of_done", ""),
                    "history": Json(t.get("history", [])),
                    "artifacts": t.get("artifacts", []),
                    "created_by": t.get("created_by", ""),
                    "created_at": t.get("created_at", ""),
                },
            )
        conn.commit()
    if t.get("project_id"):
        ensure_edge(t["id"], t["project_id"], "child_of", "parent_of")
    if t.get("parent_task_id"):
        ensure_edge(t["id"], t["parent_task_id"], "child_of", "parent_of")
    for dep_id in (t.get("depends_on") or []):
        if dep_id:
            ensure_edge(t["id"], dep_id, "depends_on", "dependency_of")


# ---------------------------------------------------------------------------
# Notes operations (stored in the notes column on each table)
# ---------------------------------------------------------------------------

def load_notes(entity_id: str) -> str:
    table = _table_for_id(entity_id)
    if not table:
        return ""
    row = fetch_one_in_schema(SCHEMA, f"SELECT notes FROM {table} WHERE id = %s", (entity_id,))
    return row["notes"] if row else ""


def save_notes(entity_id: str, content: str):
    table = _table_for_id(entity_id)
    if not table:
        return
    execute_in_schema(SCHEMA, f"UPDATE {table} SET notes = %s WHERE id = %s", (content, entity_id))


def append_note(entity_id: str, text: str):
    """Atomically append text to an entity's notes (SQL concat, no read needed)."""
    table = _table_for_id(entity_id)
    if not table:
        return
    execute_in_schema(
        SCHEMA,
        f"UPDATE {table} SET notes = COALESCE(notes, '') || %s WHERE id = %s",
        (text, entity_id),
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_entity(entity_id: str) -> bool:
    """Delete by ID. CASCADE handles child cleanup for projects/goals."""
    entity = load_entity(entity_id)
    table = _table_for_id(entity_id)
    if not table:
        return False
    count = execute_in_schema(SCHEMA, f"DELETE FROM {table} WHERE id = %s", (entity_id,))
    ok = count > 0
    if ok and entity:
        if entity_id.startswith("g-"):
            entity_type = "goal"
        elif entity_id.startswith("p-"):
            entity_type = "project"
        else:
            entity_type = "task"
        digest_record(
            app_id="goals",
            entity_type=entity_type,
            action="deleted",
            entity_id=entity_id,
            record=entity,
            by="",
        )
    return ok


# ---------------------------------------------------------------------------
# Hierarchy queries — avoid loading every entity just to filter
# ---------------------------------------------------------------------------

def get_projects_for_goal(goal_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM projects WHERE goal_id = %s ORDER BY stack_rank",
        (goal_id,),
    )
    return [_project_row_to_dict(r) for r in rows]


def get_tasks_for_project(project_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM tasks WHERE project_id = %s ORDER BY stack_rank",
        (project_id,),
    )
    return [_task_row_to_dict(r) for r in rows]


def get_subtasks(task_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM tasks WHERE parent_task_id = %s ORDER BY stack_rank",
        (task_id,),
    )
    return [_task_row_to_dict(r) for r in rows]


def get_top_level_tasks(project_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM tasks WHERE project_id = %s AND parent_task_id IS NULL "
        "ORDER BY stack_rank",
        (project_id,),
    )
    return [_task_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_for_id(entity_id: str) -> str | None:
    """Map an entity ID prefix to its (unqualified) table name."""
    if entity_id.startswith("g-"):
        return "goals"
    elif entity_id.startswith("p-"):
        return "projects"
    elif entity_id.startswith("t-"):
        return "tasks"
    return None
