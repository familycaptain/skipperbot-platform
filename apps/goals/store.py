"""Goal / Project / Task Store
============================
Hierarchical productivity tracking: Goals → Projects → Tasks.

Backed by Postgres via data_layer.goals.

Parent references link the hierarchy:
  Project → goal_id FK
  Task    → project_id FK

All times use the configured TIMEZONE.
"""

import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE
from auto_memory import log_entity_change
from link_registry import create_link, delete_links_for_entity
from apps.goals import data as _dl_goals
# legacy data_layer.config replaced with platform.config (scope=platform)
from app_platform import config as _dl_config

CENTRAL_TZ = ZoneInfo(TIMEZONE)

VALID_STATUSES = {"not_started", "in_progress", "done", "blocked", "deferred", "cancelled"}
TERMINAL_STATUSES = {"done", "cancelled", "deferred"}
VALID_PRIORITIES = {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# Persistence — Postgres via data_layer
# ---------------------------------------------------------------------------

def _load_entity(entity_id: str) -> dict | None:
    return _dl_goals.load_entity(entity_id)

def _save_entity(entity: dict):
    _dl_goals.save_entity(entity)

def _load_notes(entity_id: str) -> str:
    return _dl_goals.load_notes(entity_id)

def _save_notes(entity_id: str, content: str):
    _dl_goals.save_notes(entity_id, content)

def _list_entities(prefix: str) -> list[dict]:
    return _dl_goals.list_entities(prefix)

def _delete_entity(entity_id: str) -> bool:
    return _dl_goals.delete_entity(entity_id)


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


def _add_history(item: dict, by: str, note: str):
    if "history" not in item:
        item["history"] = []
    item["history"].append({
        "timestamp": _now_iso(),
        "by": by,
        "note": note,
    })


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------

def _get_projects_for_goal(goal_id: str) -> list[dict]:
    return _dl_goals.get_projects_for_goal(goal_id)


def _get_tasks_for_project(project_id: str) -> list[dict]:
    return _dl_goals.get_tasks_for_project(project_id)


def _find_item(item_id: str) -> dict | None:
    """Find any entity by ID. Returns the entity dict or None."""
    return _load_entity(item_id)


def _entity_type(item_id: str) -> str:
    if item_id.startswith("g-"):
        return "Goal"
    elif item_id.startswith("p-"):
        return "Project"
    elif item_id.startswith("t-"):
        return "Task"
    return "Unknown"


# ---------------------------------------------------------------------------
# Task-tree & dependency helpers
# ---------------------------------------------------------------------------

def _get_subtasks(task: dict) -> list[dict]:
    """Return loaded subtask entities sorted by stack_rank."""
    return _dl_goals.get_subtasks(task["id"])


def _get_top_level_tasks(project_id: str) -> list[dict]:
    """Return project's direct tasks (no parent_task_id), sorted by stack_rank."""
    return _dl_goals.get_top_level_tasks(project_id)


def _is_task_blocked(task: dict) -> bool:
    """Check if a task is blocked by unfinished dependencies."""
    if task.get("status") == "blocked":
        return True
    for dep_id in task.get("depends_on", []):
        dep = _load_entity(dep_id)
        if dep and dep.get("status") not in TERMINAL_STATUSES:
            return True
    return False


def _find_actionable_in_tree(task: dict) -> dict | None:
    """Depth-first search for the next actionable leaf task in a task tree.

    Walks children by stack_rank. Returns the first leaf (or childless node)
    that is not done/deferred and not blocked by dependencies.
    """
    if task.get("status") in TERMINAL_STATUSES:
        return None
    if _is_task_blocked(task):
        return None

    subtasks = _get_subtasks(task)
    if subtasks:
        for sub in subtasks:
            result = _find_actionable_in_tree(sub)
            if result:
                return result
        # All subtasks done/blocked — parent itself may be actionable
        # (e.g. wrap-up work after all children finished)
        all_subs_done = all(s.get("status") in TERMINAL_STATUSES for s in subtasks)
        if all_subs_done:
            return task
        return None

    # Leaf node — actionable
    return task


def get_next_naggable_task(project_id: str) -> dict | None:
    """Return the next actionable task by project-global stack_rank.

    Sorts ALL project tasks (at any depth) by stack_rank, then returns the
    first one that is:
      - not done or deferred
      - not blocked by unfinished dependencies
      - a leaf task (no subtasks) or a task whose subtasks are all done
    """
    all_tasks = _get_tasks_for_project(project_id)
    all_tasks.sort(key=lambda t: t.get("stack_rank", 0))

    for task in all_tasks:
        if task.get("status") in TERMINAL_STATUSES:
            continue
        if _is_task_blocked(task):
            continue
        subtasks = _get_subtasks(task)
        if subtasks:
            # Only actionable if all subtasks are done/deferred (wrap-up)
            if all(s.get("status") in TERMINAL_STATUSES for s in subtasks):
                return task
            continue  # has unfinished subtasks — not directly actionable
        return task
    return None


def _rerank_project(project_id: str) -> None:
    """Auto-rerank all tasks in a project using tree structure + dependencies.

    Ordering rules:
    1. Milestones (top-level tasks with subtasks) come first, topologically
       sorted by depends_on, with current rank as tiebreaker.
    2. Each milestone's subtasks (recursively) immediately follow it in
       depth-first order, sorted by current rank.
    3. Uncategorized (top-level leaf tasks with no subtasks) come last,
       sorted by current rank.

    Assigns ranks 1..N across all tasks.
    """
    all_tasks = _get_tasks_for_project(project_id)
    if not all_tasks:
        return

    top_level = [t for t in all_tasks if not t.get("parent_task_id")]
    milestones = [t for t in top_level if t.get("subtasks")]
    uncategorized = [t for t in top_level if not t.get("subtasks")]

    # ── Topological sort of milestones by depends_on ────────────────────
    milestone_ids = {t["id"] for t in milestones}
    milestone_map = {t["id"]: t for t in milestones}
    in_degree = {t["id"]: 0 for t in milestones}
    graph: dict[str, list[str]] = {t["id"]: [] for t in milestones}

    for t in milestones:
        for dep_id in t.get("depends_on", []):
            if dep_id in milestone_ids:
                in_degree[t["id"]] += 1
                graph[dep_id].append(t["id"])

    # Kahn's algorithm — use current rank as tiebreaker
    queue = sorted(
        [tid for tid, deg in in_degree.items() if deg == 0],
        key=lambda tid: milestone_map[tid].get("stack_rank", 0),
    )
    sorted_milestones: list[str] = []
    while queue:
        tid = queue.pop(0)
        sorted_milestones.append(tid)
        for neighbor in sorted(
            graph[tid],
            key=lambda n: milestone_map[n].get("stack_rank", 0),
        ):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=lambda n: milestone_map[n].get("stack_rank", 0))

    # Circular deps fallback — append remaining by current rank
    remaining = [tid for tid in milestone_ids if tid not in sorted_milestones]
    remaining.sort(key=lambda tid: milestone_map[tid].get("stack_rank", 0))
    sorted_milestones.extend(remaining)

    # ── Depth-first walk ────────────────────────────────────────────────
    def _dfs(task: dict):
        yield task
        for sub in _get_subtasks(task):  # already sorted by stack_rank
            yield from _dfs(sub)

    ordered: list[dict] = []
    for mid in sorted_milestones:
        ordered.extend(_dfs(milestone_map[mid]))

    uncategorized.sort(key=lambda t: t.get("stack_rank", 0))
    ordered.extend(uncategorized)

    # ── Assign ranks 1..N, only write if changed ───────────────────────
    for i, task in enumerate(ordered, 1):
        if task.get("stack_rank") != i:
            task["stack_rank"] = i
            _save_entity(task)


def _rerank_goal(goal_id: str) -> None:
    """Auto-rerank all projects in a goal using dependencies.

    Ordering: topological sort by depends_on, with current rank as tiebreaker.
    Projects don't nest, so no DFS walk needed.
    Assigns ranks 1..N across all projects.
    """
    projects = _get_projects_for_goal(goal_id)
    if not projects:
        return

    proj_map = {p["id"]: p for p in projects}
    proj_ids = set(proj_map.keys())
    in_degree = {pid: 0 for pid in proj_ids}
    graph: dict[str, list[str]] = {pid: [] for pid in proj_ids}

    for p in projects:
        for dep_id in p.get("depends_on", []):
            if dep_id in proj_ids:
                in_degree[p["id"]] += 1
                graph[dep_id].append(p["id"])

    # Kahn's algorithm — current rank as tiebreaker
    queue = sorted(
        [pid for pid, deg in in_degree.items() if deg == 0],
        key=lambda pid: proj_map[pid].get("stack_rank", 0),
    )
    ordered: list[str] = []
    while queue:
        pid = queue.pop(0)
        ordered.append(pid)
        for neighbor in sorted(
            graph[pid],
            key=lambda n: proj_map[n].get("stack_rank", 0),
        ):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=lambda n: proj_map[n].get("stack_rank", 0))

    # Circular deps fallback
    remaining = [pid for pid in proj_ids if pid not in ordered]
    remaining.sort(key=lambda pid: proj_map[pid].get("stack_rank", 0))
    ordered.extend(remaining)

    # Assign ranks 1..N, only write if changed
    for i, pid in enumerate(ordered, 1):
        proj = proj_map[pid]
        if proj.get("stack_rank") != i:
            proj["stack_rank"] = i
            _save_entity(proj)


def _rerank_goals() -> None:
    """Auto-rerank all goals globally using dependencies.

    Ordering: topological sort by depends_on, with current rank as tiebreaker.
    Assigns ranks 1..N across all goals.
    """
    goals = _list_entities("g-")
    if not goals:
        return

    goal_map = {g["id"]: g for g in goals}
    goal_ids = set(goal_map.keys())
    in_degree = {gid: 0 for gid in goal_ids}
    graph: dict[str, list[str]] = {gid: [] for gid in goal_ids}

    for g in goals:
        for dep_id in g.get("depends_on", []):
            if dep_id in goal_ids:
                in_degree[g["id"]] += 1
                graph[dep_id].append(g["id"])

    # Kahn's algorithm — current rank as tiebreaker
    queue = sorted(
        [gid for gid, deg in in_degree.items() if deg == 0],
        key=lambda gid: goal_map[gid].get("stack_rank", 0),
    )
    ordered: list[str] = []
    while queue:
        gid = queue.pop(0)
        ordered.append(gid)
        for neighbor in sorted(
            graph[gid],
            key=lambda n: goal_map[n].get("stack_rank", 0),
        ):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=lambda n: goal_map[n].get("stack_rank", 0))

    # Circular deps fallback
    remaining = [gid for gid in goal_ids if gid not in ordered]
    remaining.sort(key=lambda gid: goal_map[gid].get("stack_rank", 0))
    ordered.extend(remaining)

    # Assign ranks 1..N, only write if changed
    for i, gid in enumerate(ordered, 1):
        goal = goal_map[gid]
        if goal.get("stack_rank") != i:
            goal["stack_rank"] = i
            _save_entity(goal)


def _check_parent_completion(task_id: str, updated_by: str) -> str | None:
    """After a subtask completes, check if all siblings are done.

    Returns a hint string if the parent task can be completed, else None.
    Does NOT auto-complete the parent — that's the user's call.
    """
    task = _load_entity(task_id)
    if not task:
        return None
    parent_id = task.get("parent_task_id")
    if not parent_id:
        return None

    parent = _load_entity(parent_id)
    if not parent:
        return None

    subs = _get_subtasks(parent)
    if not subs:
        return None

    all_done = all(s.get("status") in TERMINAL_STATUSES for s in subs)
    if all_done and parent.get("status") not in TERMINAL_STATUSES:
        return (
            f"All subtasks of '{parent['name']}' ({parent_id}) are now complete. "
            f"Consider marking it done: update_item(\"{parent_id}\", status=\"done\")"
        )
    return None


def _refresh_project_nag(project_id: str, reason: str = ""):
    """Re-evaluate the project's auto-nag target after any material change.

    Called whenever something changes that could affect which task should be
    nagged about: task creation, status change, assignment change, reparenting,
    reordering, dependency change, etc.

    This is idempotent — if the current nag target is still correct, it's a no-op.
    """
    project = _load_entity(project_id)
    if not project:
        logger.warning("AUTONAG: Project %s not found — skipping refresh", project_id)
        return
    nag_config = project.get("auto_nag")
    if not nag_config or not nag_config.get("enabled"):
        logger.info("AUTONAG: Project %s has no active auto_nag config — skipping", project_id)
        return

    nag_id = nag_config.get("nag_id")
    if not nag_id:
        logger.warning("AUTONAG: Project %s auto_nag has no nag_id — skipping", project_id)
        return

    current_task_id = nag_config.get("current_task_id")
    next_task = get_next_naggable_task(project_id)
    next_task_id = next_task["id"] if next_task else None

    logger.info("AUTONAG: Project %s — current=%s, next=%s",
                project_id, current_task_id, next_task_id)

    # No change needed
    if next_task_id == current_task_id:
        logger.info("AUTONAG: No change needed for project %s", project_id)
        return

    from app_platform.reminders import _load_reminders, _save_reminders

    reminders = _load_reminders()
    nag = None
    for r in reminders:
        if r["id"] == nag_id:
            nag = r
            break

    if not nag:
        logger.warning("AUTONAG: Nag %s not found for project %s", nag_id, project_id)
        return

    reason_tag = f" ({reason})" if reason else ""

    if next_task:
        nag["message"] = f"[{project.get('name', project_id)}] Next up: {next_task['name']} ({next_task['id']})"
        nag["active"] = True
        _save_reminders(reminders)

        nag_config["current_task_id"] = next_task["id"]
        _save_entity(project)
        logger.info("AUTONAG: Refreshed nag %s → task %s (%s)%s",
                     nag_id, next_task["id"], next_task["name"], reason_tag)
    else:
        # All tasks done or blocked — pause the nag
        nag["message"] = f"[{project.get('name', project_id)}] All tasks complete or blocked!"
        nag["active"] = False
        _save_reminders(reminders)
        nag_config["current_task_id"] = None
        _save_entity(project)
        logger.info("AUTONAG: No actionable tasks for project %s — nag paused%s",
                     project_id, reason_tag)


def _auto_unblock_dependents(completed_task_id: str, updated_by: str):
    """When a task completes, check if any tasks that depend on it can be unblocked."""
    all_tasks = _list_entities("t-")
    for task in all_tasks:
        deps = task.get("depends_on", [])
        if completed_task_id not in deps:
            continue
        # This task depends on the completed one — check if ALL deps are now done
        all_deps_done = True
        for dep_id in deps:
            dep = _load_entity(dep_id)
            if dep and dep.get("status") not in TERMINAL_STATUSES:
                all_deps_done = False
                break
        if all_deps_done and task.get("status") == "blocked":
            task["status"] = "not_started"
            _add_history(task, updated_by,
                         f"Auto-unblocked: dependency {completed_task_id} completed")
            _save_entity(task)
            logger.info("AUTONAG: Auto-unblocked task %s (%s)", task["id"], task["name"])


def _ensure_goal_collaborators(users: list[str], project_id: str):
    """Add users as collaborators on the parent goal if not already owner/collaborator.

    Walks from project → goal and adds any missing users to goal.collaborators.
    Silently does nothing if the project or goal can't be found.
    """
    if not users or not project_id:
        return
    project = _load_entity(project_id)
    if not project:
        return
    goal_id = project.get("goal_id", "")
    if not goal_id:
        return
    goal = _load_entity(goal_id)
    if not goal:
        return
    owners = set(goal.get("owners", []))
    collabs = set(goal.get("collaborators", []))
    new_collabs = [u for u in users if u and u not in owners and u not in collabs]
    if not new_collabs:
        return
    goal.setdefault("collaborators", []).extend(new_collabs)
    _save_entity(goal)
    logger.info("COLLAB: Auto-added %s as collaborator(s) on goal %s", new_collabs, goal_id)


# ---------------------------------------------------------------------------
# Create operations
# ---------------------------------------------------------------------------

def create_goal(
    name: str,
    created_by: str,
    description: str = "",
    owners: list[str] | None = None,
    target_date: str = "",
) -> dict:
    """Create a new goal.

    Args:
        name: Goal name.
        created_by: Person who created it.
        description: Initial notes (written to notes.md, not stored in JSON).
        owners: List of owners. Defaults to [created_by].
        target_date: Optional target completion date.

    Returns:
        The created goal dict.
    """
    goal = {
        "id": _new_id("g"),
        "name": name,
        "owners": owners or [created_by],
        "collaborators": [],
        "target_date": target_date,
        "status": "not_started",
        "created_at": _now_iso(),
        "created_by": created_by,
        "projects": [],
        "history": [],
    }
    # Initial stack_rank: append after existing goals
    existing = _list_entities("g-")
    max_rank = max((g.get("stack_rank", 0) for g in existing), default=0)
    goal["stack_rank"] = max_rank + 1

    _add_history(goal, created_by, "Goal created")
    _save_entity(goal)
    _rerank_goals()

    # Initialize notes.md
    notes = f"# {name}\n"
    if description.strip():
        notes += f"\n{description.strip()}\n"
    _save_notes(goal["id"], notes)

    log_entity_change("created", goal["id"], "goal", f"{name}", by=created_by)
    return goal


def create_project(
    goal_id: str,
    name: str,
    created_by: str,
    description: str = "",
    owners: list[str] | None = None,
    due_date: str = "",
    priority: str = "medium",
) -> dict | str:
    """Create a project under a goal.

    Returns:
        The created project dict, or an error string.
    """
    goal = _load_entity(goal_id)
    if not goal or not goal_id.startswith("g-"):
        return f"Error: Goal '{goal_id}' not found."

    if priority.lower() not in VALID_PRIORITIES:
        priority = "medium"

    project = {
        "id": _new_id("p"),
        "name": name,
        "goal_id": goal_id,
        "owners": owners or [created_by],
        "due_date": due_date,
        "priority": priority.lower(),
        "status": "not_started",
        "created_at": _now_iso(),
        "created_by": created_by,
        "tasks": [],
        "history": [],
    }
    # Initial stack_rank: append after existing projects in this goal
    siblings = _get_projects_for_goal(goal_id)
    max_rank = max((p.get("stack_rank", 0) for p in siblings), default=0)
    project["stack_rank"] = max_rank + 1

    _add_history(project, created_by, "Project created")
    _save_entity(project)

    # Register on parent goal
    goal.setdefault("projects", []).append(project["id"])
    _save_entity(goal)

    _rerank_goal(goal_id)

    notes = f"# {name}\n"
    if description.strip():
        notes += f"\n{description.strip()}\n"
    _save_notes(project["id"], notes)

    # Bidirectional link: goal ↔ project
    create_link(goal_id, project["id"], relation="has_project", created_by=created_by)

    # Auto-add project owners as collaborators on parent goal
    _ensure_goal_collaborators(project["owners"], project_id=project["id"])

    log_entity_change("created", project["id"], "project", f"{name} under {goal_id}",
                      by=created_by, related_entities=[goal_id])
    return project


def create_task(
    project_id: str,
    name: str,
    created_by: str,
    assigned_to: list[str] | None = None,
    due_date: str = "",
    priority: str = "medium",
    parent_task_id: str | None = None,
    trello_card_id: str = "",
    trello_list: str = "",
) -> dict | str:
    """Create a task under a project, or as a subtask under another task.

    When parent_task_id is provided the task becomes a child of that task.
    It still inherits project_id (from the root ancestor) so project-level
    queries keep working.

    When trello_card_id is provided (e.g. from Trello sync), the task is
    linked to an existing card. Otherwise, if the project is linked to a
    Trello board, a new card is auto-created on the default list.

    Returns:
        The created task dict, or an error string.
    """
    # --- resolve parent task (subtask mode) ---
    parent_task = None
    if parent_task_id:
        parent_task = _load_entity(parent_task_id)
        if not parent_task or not parent_task_id.startswith("t-"):
            return f"Error: Parent task '{parent_task_id}' not found."
        # Inherit project_id from parent task
        project_id = parent_task.get("project_id", project_id)

    project = _load_entity(project_id)
    if not project or not project_id.startswith("p-"):
        return f"Error: Project '{project_id}' not found."

    if priority.lower() not in VALID_PRIORITIES:
        priority = "medium"

    # Auto-assign stack_rank — project-global (not per-sibling-group)
    all_project_tasks = _get_tasks_for_project(project_id)
    max_rank = max((t.get("stack_rank", 0) for t in all_project_tasks), default=0)

    task = {
        "id": _new_id("t"),
        "name": name,
        "project_id": project_id,
        "parent_task_id": parent_task_id,
        "subtasks": [],
        "assigned_to": assigned_to or [],
        "due_date": due_date,
        "priority": priority.lower(),
        "status": "not_started",
        "stack_rank": max_rank + 1,
        "depends_on": [],
        "trello_card_id": trello_card_id,
        "trello_list": trello_list,
        "created_at": _now_iso(),
        "created_by": created_by,
        "history": [],
    }
    _add_history(task, created_by, "Task created")
    _save_entity(task)

    if parent_task:
        # Register on parent task's subtasks list
        parent_task.setdefault("subtasks", []).append(task["id"])
        _save_entity(parent_task)
        create_link(parent_task_id, task["id"], relation="has_subtask", created_by=created_by)
        log_entity_change("created", task["id"], "task",
                          f"{name} under task {parent_task_id}",
                          by=created_by, related_entities=[parent_task_id, project_id])
    else:
        # Register on parent project (top-level task)
        project.setdefault("tasks", []).append(task["id"])
        _save_entity(project)
        create_link(project_id, task["id"], relation="has_task", created_by=created_by)
        log_entity_change("created", task["id"], "task", f"{name} under {project_id}",
                          by=created_by, related_entities=[project_id])

    _save_notes(task["id"], f"# {name}\n")

    # Auto-add task assignees as collaborators on parent goal
    _ensure_goal_collaborators(task["assigned_to"], project_id=project_id)

    # Re-rank so new task slots into correct tree position
    _rerank_project(project_id)

    # Re-evaluate auto-nag (new task may change which leaf is actionable)
    _refresh_project_nag(project_id, reason=f"new task {task['id']}")

    # --- Trello auto-sync: create card if project is linked and no card ID yet ---
    if not trello_card_id and not parent_task_id:
        try:
            from trello_task_sync import sync_task_to_trello, get_project_trello_config
            if get_project_trello_config(project):
                result = sync_task_to_trello(task, project)
                if result:
                    card_id, list_name = result
                    task["trello_card_id"] = card_id
                    task["trello_linked"] = True
                    task["trello_list"] = list_name or project["trello"].get("backlog_list", "Backlog")
                    _save_entity(task)
        except Exception as e:
            logger.warning("TRELLO_TASK_SYNC: Auto-sync failed for new task %s: %s",
                           task["id"], e)

    return task


# ---------------------------------------------------------------------------
# Update operations
# ---------------------------------------------------------------------------

def update_item(
    item_id: str,
    updated_by: str,
    status: str = "",
    history_note: str = "",
    fields: dict | None = None,
) -> str:
    """Update any item (goal, project, or task) by ID.

    Args:
        item_id: The entity ID (g-xxx, p-xxx, or t-xxx).
        updated_by: Who is making the change.
        status: New status (not_started, in_progress, done, blocked, deferred, cancelled).
        history_note: A timestamped comment added to the entity's history log.
                      This is NOT the notes document — use update_entity_notes for that.
        fields: Dict of other fields to update (name, owners,
                assigned_to, target_date, due_date, priority).

    Returns:
        Confirmation string with the updated state.
    """
    item = _find_item(item_id)
    if not item:
        return f"Error: Item '{item_id}' not found."

    item_type = _entity_type(item_id)
    changes = []

    # Status change
    if status and status.strip():
        new_status = status.strip().lower()
        if new_status not in VALID_STATUSES:
            return (
                f"Error: Invalid status '{new_status}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )
        old_status = item.get("status", "not_started")
        if old_status != new_status:
            item["status"] = new_status
            changes.append(f"Status: {old_status} → {new_status}")
            _add_history(item, updated_by, f"Status changed from {old_status} to {new_status}")

    # Field updates
    if fields:
        # Block cross-parent migration fields — must use proper tools
        blocked_fields = {"project_id", "goal_id", "parent_task_id"}
        bad = blocked_fields & set(fields.keys())
        if bad:
            return (
                f"Error: Cannot change {', '.join(bad)} via update_item. "
                f"Use set_task_parent to move tasks between projects."
            )
        for key, value in fields.items():
            if key in ("name", "priority", "target_date", "due_date", "definition_of_done", "pm_cadence_minutes"):
                if key == "priority" and str(value).lower() not in VALID_PRIORITIES:
                    continue
                if key == "priority":
                    value = str(value).lower()
                old_val = item.get(key, "")
                if old_val != value:
                    item[key] = value
                    changes.append(f"{key}: {old_val!r} → {value!r}")
                    _add_history(item, updated_by, f"Changed {key} to {value!r}")
            elif key in ("owners", "assigned_to", "collaborators"):
                if isinstance(value, str):
                    value = [v.strip().lower() for v in value.split(",") if v.strip()]
                item[key] = value
                changes.append(f"{key}: {value}")
                _add_history(item, updated_by, f"Changed {key} to {value}")
                # Auto-add as collaborators on parent goal
                if key in ("owners", "assigned_to") and value:
                    pid = item.get("project_id", "")
                    if item_id.startswith("p-"):
                        pid = item_id
                    if pid:
                        try:
                            _ensure_goal_collaborators(value, project_id=pid)
                        except Exception as e:
                            logger.warning("Failed to auto-add collaborators on goal for %s: %s", pid, e)

    # History note
    if history_note and history_note.strip():
        _add_history(item, updated_by, history_note.strip())
        changes.append(f"Note: {history_note.strip()}")

    if not changes:
        return f"No changes made to '{item_id}'. Provide status, note, or fields to update."

    _save_entity(item)

    # --- Task side-effects ---
    parent_hint = None
    if item_id.startswith("t-"):
        project_id = item.get("project_id")
        is_trello = item.get("trello_card_id") and project_id
        logger.info("TRELLO_SIDEEFFECT: item=%s trello_card_id=%s project_id=%s is_trello=%s fields_keys=%s",
                    item_id, item.get("trello_card_id"), project_id, bool(is_trello),
                    list(fields.keys()) if fields else None)

        if item.get("status") in ("done", "cancelled"):
            # 1. Auto-unblock tasks that depended on this one
            _auto_unblock_dependents(item_id, updated_by)
            # 2. Check if parent task's subtasks are all done/cancelled
            parent_hint = _check_parent_completion(item_id, updated_by)
            # 3. Trello: move card to Done list
            if is_trello:
                try:
                    from trello_task_sync import sync_task_completion_to_trello
                    proj = _load_entity(project_id)
                    if proj:
                        sync_task_completion_to_trello(item, proj)
                except Exception as e:
                    logger.warning("TRELLO_TASK: completion sync failed for %s: %s",
                                   item_id, e)

        # 3b. Trello: status changes other than "done"/"cancelled"
        if is_trello and status and item.get("status") not in ("done", "cancelled"):
            try:
                from trello_task_sync import (
                    get_project_trello_config, move_card_to_list, get_user_list,
                )
                proj = _load_entity(project_id)
                config = get_project_trello_config(proj) if proj else None
                if config:
                    new_status = item["status"]
                    if new_status == "not_started":
                        move_card_to_list(item, proj, config.get("backlog_list", "Backlog"))
                    elif new_status == "in_progress":
                        # Move to the updating user's list if configured
                        user_list = get_user_list(updated_by, config)
                        if user_list:
                            move_card_to_list(item, proj, user_list)
            except Exception as e:
                logger.warning("TRELLO_TASK: status move failed for %s: %s", item_id, e)

        # 3c. Trello: assignment change → move card to user's list
        if is_trello and fields and "assigned_to" in fields:
            try:
                from trello_task_sync import (
                    get_project_trello_config, move_card_to_list, ensure_user_list,
                )
                proj = _load_entity(project_id)
                config = get_project_trello_config(proj) if proj else None
                if config:
                    new_assignees = item.get("assigned_to", [])
                    if new_assignees:
                        target_list = ensure_user_list(new_assignees[0], proj)
                        logger.info("TRELLO_ASSIGN: task=%s → user=%s list=%s",
                                    item_id, new_assignees[0], target_list)
                        if target_list:
                            move_card_to_list(item, proj, target_list)
            except Exception as e:
                logger.warning("TRELLO_TASK: assign move failed for %s: %s", item_id, e,
                               exc_info=True)

        # 3d. Trello: due date or name sync
        if is_trello and fields:
            try:
                from trello_task_sync import get_project_trello_config
                from trello_client import update_card as _trello_update_card
                proj = _load_entity(project_id)
                config = get_project_trello_config(proj) if proj else None
                if config:
                    board = config["board"]
                    card_id = item["trello_card_id"]
                    if "due_date" in fields and fields["due_date"]:
                        _trello_update_card(board, "", due=fields["due_date"], card_id=card_id)
                    if "name" in fields and fields["name"]:
                        _trello_update_card(board, "", new_name=fields["name"], card_id=card_id)
            except Exception as e:
                logger.warning("TRELLO_TASK: field sync failed for %s: %s", item_id, e)

        # 4. Re-evaluate auto-nag on any material change
        if project_id:
            logger.info("AUTONAG: Task %s changed (project %s), refreshing nag...", item_id, project_id)
            _refresh_project_nag(project_id, reason="; ".join(changes))
        else:
            logger.warning("AUTONAG: Task %s has no project_id — skipping nag refresh", item_id)

    # --- Project side-effects: rerank on status change ---
    if item_id.startswith("p-") and status:
        goal_id = item.get("goal_id")
        if goal_id:
            _rerank_goal(goal_id)

    # --- Goal side-effects: rerank on status change ---
    if item_id.startswith("g-") and status:
        _rerank_goals()

    log_entity_change("updated", item_id, item_type.lower(),
                      "; ".join(changes), by=updated_by)

    # Read-after-write verification
    verified = False
    v_item = _load_entity(item_id)
    if v_item and v_item.get("status") == item.get("status"):
        verified = True

    tag = "VERIFIED" if verified else "UNVERIFIED"
    result = f"{item_type} '{item_id}' updated [{tag}].\n"
    result += f"  Name: {item.get('name')}\n"
    result += f"  Status: {item.get('status')}\n"
    if item.get("priority"):
        result += f"  Priority: {item.get('priority')}\n"
    date_key = "target_date" if item_id.startswith("g-") else "due_date"
    if item.get(date_key):
        result += f"  {'Target' if item_id.startswith('g-') else 'Due'}: {item.get(date_key)}\n"
    people_key = "owners" if item_id.startswith(("g-", "p-")) else "assigned_to"
    if item.get(people_key):
        result += f"  {people_key.replace('_', ' ').title()}: {', '.join(item[people_key])}\n"
    result += f"  Changes: {'; '.join(changes)}\n"
    if parent_hint:
        result += f"  ⚡ {parent_hint}\n"
    result += "Report these values exactly as shown above.\n"
    return result


def update_notes(
    item_id: str,
    content: str,
    updated_by: str = "",
) -> str:
    """Update the notes.md document for any entity.

    Args:
        item_id: Entity ID.
        content: New content for the notes file (replaces entirely).
        updated_by: Who is making the change.

    Returns:
        Confirmation.
    """
    item = _find_item(item_id)
    if not item:
        return f"Error: Item '{item_id}' not found."

    # Trello-linked tasks: push to Trello card description
    if item_id.startswith("t-") and item.get("trello_linked") and item.get("trello_card_id"):
        try:
            from trello_task_sync import update_card_description, get_project_trello_config
            project = _load_entity(item.get("project_id", ""))
            if project and get_project_trello_config(project):
                result = update_card_description(item, project, content)
                if result.startswith("Error"):
                    return result
                if updated_by:
                    _add_history(item, updated_by, "Updated notes (Trello card description)")
                    _save_entity(item)
                log_entity_change("updated_notes", item_id, "task",
                                  f"Notes updated for task {item_id} (Trello)",
                                  by=updated_by)
                return f"Notes updated for {item_id}."
        except Exception as e:
            logger.warning("update_notes: Trello push failed for %s: %s", item_id, e)
            return f"Error: Failed to update Trello card description: {e}"

    item["notes"] = content
    _save_notes(item_id, content)
    if updated_by:
        _add_history(item, updated_by, "Updated notes")
        _save_entity(item)

    entity_type = "goal" if item_id.startswith("g-") else "project" if item_id.startswith("p-") else "task"
    log_entity_change("updated_notes", item_id, entity_type,
                      f"Notes updated for {entity_type} {item_id}",
                      by=updated_by)

    return f"Notes updated for {item_id}."


def get_notes(item_id: str) -> str:
    """Read the notes/description for an entity.

    For Trello-linked tasks, fetches the card description from Trello.
    For all other entities, reads from local notes file.
    """
    item = _find_item(item_id)
    if not item:
        return f"Error: Item '{item_id}' not found."

    # Trello-linked tasks: read from Trello card description
    if item_id.startswith("t-") and item.get("trello_linked") and item.get("trello_card_id"):
        try:
            from trello_task_sync import get_card_description, get_project_trello_config
            project = _load_entity(item.get("project_id", ""))
            if project and get_project_trello_config(project):
                desc = get_card_description(item, project)
                if desc is not None:
                    if not desc.strip():
                        return f"No notes for {item_id}."
                    return desc
        except Exception as e:
            logger.warning("get_notes: Trello fetch failed for %s, falling back to local: %s", item_id, e)

    notes = _load_notes(item_id)
    if not notes.strip():
        return f"No notes for {item_id}."
    return notes


# ---------------------------------------------------------------------------
# Delete operations
# ---------------------------------------------------------------------------

def delete_item(item_id: str, deleted_by: str) -> str:
    """Delete a goal, project, or task by ID.

    Handles cleanup:
      - Tasks: removed from parent project's tasks list.
      - Projects: all child tasks deleted first, removed from parent goal's projects list.
      - Goals: all child projects (and their tasks) deleted first.
      - Links involving the entity are removed.

    Args:
        item_id: The entity ID (g-xxx, p-xxx, or t-xxx).
        deleted_by: Who is performing the deletion.

    Returns:
        Confirmation string.
    """
    item = _find_item(item_id)
    if not item:
        return f"Error: Item '{item_id}' not found."

    entity_type = _entity_type(item_id)
    name = item.get("name", item_id)

    if item_id.startswith("g-"):
        # Delete all child projects (which recursively delete their tasks)
        for pid in list(item.get("projects", [])):
            delete_item(pid, deleted_by)

    elif item_id.startswith("p-"):
        # Delete all child tasks
        for tid in list(item.get("tasks", [])):
            delete_item(tid, deleted_by)
        # Remove from parent goal's projects list
        goal_id = item.get("goal_id")
        if goal_id:
            goal = _load_entity(goal_id)
            if goal and item_id in goal.get("projects", []):
                goal["projects"].remove(item_id)
                _save_entity(goal)

    elif item_id.startswith("t-"):
        # Archive Trello card if this is a Trello-linked task
        if item.get("trello_linked") and item.get("trello_card_id"):
            project_id_for_trello = item.get("project_id")
            if project_id_for_trello:
                try:
                    from trello_task_sync import archive_trello_card
                    proj = _load_entity(project_id_for_trello)
                    if proj:
                        archive_trello_card(item, proj)
                except Exception as e:
                    logger.warning("TRELLO_TASK: archive failed for %s: %s", item_id, e)

        # Remove from parent project's tasks list
        project_id = item.get("project_id")
        if project_id:
            project = _load_entity(project_id)
            if project and item_id in project.get("tasks", []):
                project["tasks"].remove(item_id)
                _save_entity(project)

    # Remove all links involving this entity
    removed_links = delete_links_for_entity(item_id)

    # Delete the entity directory
    _delete_entity(item_id)

    log_entity_change("deleted", item_id, entity_type.lower(),
                      f"{name} deleted", by=deleted_by)

    result = f"{entity_type} '{item_id}' ({name}) deleted."
    if removed_links:
        result += f" ({removed_links} links removed.)"
    return result


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------

def get_goals_summary(user_id: str = "") -> str:
    """Get a summary of all goals with progress."""
    goals = _list_entities("g-")
    if not goals:
        return "No goals found."

    goals.sort(key=lambda g: g.get("stack_rank", 0))
    user = user_id.lower().strip() if user_id else ""

    goal_blocks = []
    for goal in goals:
        projects = _get_projects_for_goal(goal["id"])

        # Filter by user if specified
        # Include: user is an owner, OR owners is empty (family/shared goal),
        #          OR user is involved in a project/task.
        # Exclude: goal has owners and none of them are the user (someone else's goal).
        if user:
            goal_owners = [o.lower() for o in goal.get("owners", [])]
            if not goal_owners:
                pass  # no owners = family/shared goal, include it
            elif user in goal_owners:
                pass  # user is an owner, include it
            else:
                # goal belongs to someone else — check project/task involvement
                has_involvement = False
                for proj in projects:
                    proj_owners = [o.lower() for o in proj.get("owners", [])]
                    if user in proj_owners:
                        has_involvement = True
                        break
                    for task in _get_tasks_for_project(proj["id"]):
                        if user in [a.lower() for a in task.get("assigned_to", [])]:
                            has_involvement = True
                            break
                    if has_involvement:
                        break
                if not has_involvement:
                    continue

        total_tasks = 0
        done_tasks = 0
        for proj in projects:
            for task in _get_tasks_for_project(proj["id"]):
                if task.get("status") not in ("deferred", "cancelled"):
                    total_tasks += 1
                    if task.get("status") == "done":
                        done_tasks += 1

        pct = int(done_tasks / total_tasks * 100) if total_tasks > 0 else 0
        status_icon = {"in_progress": "►", "done": "✓", "blocked": "✕",
                       "deferred": "⏸", "cancelled": "✗"}.get(goal.get("status", "not_started"), "○")

        # Goal header line with G-rank
        g_rank = goal.get("stack_rank", 0)
        block_lines = []
        target_tag = f" — due {goal['target_date']}" if goal.get("target_date") else ""
        header_text = (
            f"G{g_rank}. {status_icon} {goal['name']}** [{goal['id']}]"
            f" — {goal['status'].upper()}{target_tag}"
        )
        progress_text = (
            f"  {done_tasks}/{total_tasks} tasks done ({pct}%) · "
            f"{len(projects)} project{'s' if len(projects) != 1 else ''}"
        )
        if goal.get("status") in ("done", "cancelled"):
            block_lines.append(f"~~**{header_text}~~")
            block_lines.append(f"~~{progress_text}~~")
        else:
            block_lines.append(f"**{header_text}")
            block_lines.append(progress_text)

        goal_blocks.append((goal["id"], goal["name"], "\n".join(block_lines)))

    if not goal_blocks:
        return f"No goals found for '{user}'." if user else "No goals found."

    header = "**Goals**"
    if user:
        header += f" for {user}"
    header += f" ({len(goal_blocks)})"

    full_text = header + "\n\n" + "\n\n".join(text for _, _, text in goal_blocks)

    # Build a G-rank ID lookup for the LLM context
    # Re-read entities to get their stack_rank for the map
    id_map = " | ".join(
        f"G{_load_entity(gid).get('stack_rank', i+1)} {gname}={gid}"
        for i, (gid, gname, _) in enumerate(goal_blocks)
    )
    return _direct_display(
        full_text,
        context_footer=(
            f"[Already displayed to the user — do NOT repeat or reformat. "
            f"Goal index: {id_map}. "
            f"If the user asks about a SPECIFIC goal (by G-rank, number, name, or description), "
            f"call get_goal_detail with the matching goal ID. "
            f"Do NOT call get_goals_summary again.]"
        ),
    )


def _render_task_tree(tasks: list[dict], lines: list[str], indent: int = 8,
                      parent_rank: int | None = None):
    """Render tasks in a clean hierarchy for Discord code-block display.

    Layout:
    - Milestones (tasks with subtasks): paragraph-spaced, no bullet
      - Their subtasks: single-indent bullet
    - Uncategorized (leaf tasks with no parent): grouped at end
    """
    pad = " " * indent

    # Build task map for resolving depends_on IDs → T-ranks
    all_tasks_here = list(tasks)
    for t in tasks:
        all_tasks_here.extend(_get_subtasks(t))
    task_map = {t["id"]: t for t in all_tasks_here}

    def _icon(task):
        return {"done": "✓", "in_progress": "►", "blocked": "✕",
                "deferred": "⏸", "not_started": "○",
                }.get(task.get("status", "not_started"), "?")

    def _deps(task):
        deps = task.get("depends_on", [])
        if not deps:
            return ""
        parts = [f"T{task_map[d].get('stack_rank', '?')}"
                 for d in deps if d in task_map]
        return f"  (depends on {', '.join(parts)})" if parts else ""

    def _due(task):
        d = task.get("due_date")
        return f"  [due {d}]" if d else ""

    def _trello(task):
        tl = task.get("trello_list")
        return f"  [Trello: {tl}]" if tl else ""

    # Split into milestones (has subtasks) vs uncategorized (leaf)
    milestones = []
    uncategorized = []
    for t in tasks:
        subs = _get_subtasks(t)
        if subs:
            milestones.append((t, subs))
        else:
            uncategorized.append(t)

    # ── Milestones ──────────────────────────────────────────────────────
    for task, subs in milestones:
        rank = task.get("stack_rank", "?")
        lines.append("")  # paragraph spacing
        text = (
            f"T{rank} ({task['id']}) {_icon(task)} {task['name']}"
            f" — {task['status'].upper()}{_deps(task)}{_due(task)}"
        )
        if task.get("status") == "done":
            lines.append(f"{pad}~~**{text}**~~")
        else:
            lines.append(f"{pad}**{text}**")
        for sub in subs:
            sr = sub.get("stack_rank", "?")
            sub_text = (
                f"T{sr} ({sub['id']}) {sub['name']}"
                f" — {sub['status'].upper()}{_deps(sub)}{_trello(sub)}"
            )
            if sub.get("status") == "done":
                lines.append(f"{pad}• ~~{sub_text}~~")
            else:
                lines.append(f"{pad}• {sub_text}")

    # ── Uncategorized (leaf tasks) ──────────────────────────────────────
    if uncategorized:
        lines.append("")
        lines.append(f"{pad}**Uncategorized:**")
        for task in uncategorized:
            rank = task.get("stack_rank", "?")
            task_text = (
                f"T{rank} ({task['id']}) {task['name']}"
                f" — {task['status'].upper()}{_deps(task)}{_trello(task)}"
            )
            if task.get("status") == "done":
                lines.append(f"{pad}• ~~{task_text}~~")
            else:
                lines.append(f"{pad}• {task_text}")


_ENTITY_ID_RE = re.compile(r'\s*[\(\[](g|p|t)-[a-f0-9]+[\)\]]')


def _strip_entity_ids(text: str) -> str:
    """Remove entity ID references like (g-xxx), (p-xxx), (t-xxx), [g-xxx] for display."""
    return _ENTITY_ID_RE.sub('', text)


def _direct_display(full_text: str, context_footer: str = "") -> str:
    """Return a JSON envelope that chat.py will intercept.

    - ``display``: ID-stripped version sent directly to Discord.
    - ``context``: Full version (with IDs) as compact reference for the LLM.
    """
    # Strip IDs and remove [INSTRUCTION:...] lines for the display version
    display_lines = []
    for line in full_text.split("\n"):
        if line.strip().startswith("[INSTRUCTION"):
            continue
        display_lines.append(_strip_entity_ids(line))
    display = "\n".join(display_lines).strip()

    # Build compact reference context — NOT formatted display text.
    # This prevents the LLM from parroting the display back to the user.
    context = (
        "[ALREADY DISPLAYED TO USER — do NOT repeat, reformat, or summarize this content. "
        "It is visible in the chat above your reply. "
        "Just answer any follow-up question or stay silent. "
        "Entity IDs below are for YOUR reference only.]\n"
        "---\n"
        + full_text
    )
    if context_footer:
        context += "\n" + context_footer

    return json.dumps({
        "__direct_display__": True,
        "display": display,
        "context": context,
    })


# Scoped rank resolution context — set by detail views so follow-up
# rank references (P1, T3) resolve within the correct parent.
# Persisted to Postgres (config table) because MCP tool calls run in
# separate subprocesses.


def _load_view_context() -> tuple[str, str]:
    """Load the last-viewed goal/project. Scoped 'app:goals' via platform.config."""
    ctx = _dl_config.get("view_context", default={})
    return ctx.get("goal", ""), ctx.get("project", "")


def _save_view_context(goal: str = "", project: str = ""):
    """Persist the last-viewed goal/project. Scoped 'app:goals' via platform.config."""
    old_goal, old_project = _load_view_context()
    _dl_config.set("view_context", {
        "goal": goal or old_goal,
        "project": project or old_project,
    })


# Lazy-init view context — populated on first access, not at module load,
# so importing this module doesn't require the DB to be reachable.
_last_viewed_goal: str = ""
_last_viewed_project: str = ""
_view_context_loaded: bool = False


def _ensure_view_context_loaded() -> None:
    """Lazy-load _last_viewed_* from app_config on first need."""
    global _last_viewed_goal, _last_viewed_project, _view_context_loaded
    if _view_context_loaded:
        return
    try:
        _last_viewed_goal, _last_viewed_project = _load_view_context()
    except Exception as exc:
        logger.warning("goals.store: could not load view context (%s); using empty", exc)
        _last_viewed_goal = ""
        _last_viewed_project = ""
    _view_context_loaded = True


def _resolve_rank(ref: str) -> str:
    """Resolve a rank reference (G4, P2, T5), entity name, or ID to an entity ID.

    Resolution order:
    1. Already a valid entity ID (g-xxx, p-xxx, t-xxx) → pass through.
    2. Rank reference (G4, P2, T5) → resolve by stack_rank with scoping.
    3. Name-based lookup → case-insensitive match across all entities.

    Scoping rules for ranks:
    - G# is globally unique — always resolves.
    - P# resolves within the last-viewed goal (set by get_goal_detail).
    - T# resolves within the last-viewed project (set by get_project_detail).
    - If no scope is available, falls back to global search.
    """
    ref = ref.strip()
    # Already a valid entity ID
    if re.match(r'^[gpt]-[a-f0-9]+$', ref):
        return ref

    # Lazy-load view context (needed for P# / T# scoped lookups below).
    _ensure_view_context_loaded()

    # Try to parse as a rank reference
    m = re.match(r'^([gpt])(\d+)$', ref.lower())
    if m:
        prefix = m.group(1)
        rank = int(m.group(2))

        if prefix == "g":
            for entity in _list_entities("g-"):
                if entity.get("stack_rank") == rank:
                    return entity["id"]
        elif prefix == "p":
            if _last_viewed_goal:
                for proj in _get_projects_for_goal(_last_viewed_goal):
                    if proj.get("stack_rank") == rank:
                        return proj["id"]
            for entity in _list_entities("p-"):
                if entity.get("stack_rank") == rank:
                    return entity["id"]
        elif prefix == "t":
            if _last_viewed_project:
                for task in _get_tasks_for_project(_last_viewed_project):
                    if task.get("stack_rank") == rank:
                        return task["id"]
        return ref  # rank not found

    # Fallback: name-based lookup (case-insensitive) across goals, projects, tasks
    ref_lower = ref.lower()
    for prefix in ("g-", "p-", "t-"):
        for entity in _list_entities(prefix):
            if entity.get("name", "").lower() == ref_lower:
                return entity["id"]

    return ref  # nothing matched, return as-is (will produce a clean error)


def get_goal_detail(goal_id: str) -> str:
    """Goal summary view: goal info + project list (no tasks).

    Use get_project_detail() when the user asks to see a specific project's tasks.
    """
    global _last_viewed_goal
    goal_id = _resolve_rank(goal_id)
    goal = _load_entity(goal_id)
    if not goal:
        return f"Error: Goal '{goal_id}' not found."

    _last_viewed_goal = goal_id
    _save_view_context(goal=goal_id)
    g_rank = goal.get("stack_rank", 0)
    lines = []
    lines.append(f"**G{g_rank} — Goal: {goal['name']}** [{goal['id']}]")
    lines.append(f"Status: {goal['status'].upper()}")
    lines.append(f"Owners: {', '.join(goal.get('owners', []))}")
    if goal.get("target_date"):
        lines.append(f"Target Date: {goal['target_date']}")

    # Notes excerpt
    notes = _load_notes(goal_id)
    if notes.strip():
        content_lines = [l for l in notes.strip().split("\n") if l.strip() and not l.startswith("#")]
        if content_lines:
            preview = "\n  ".join(content_lines[:3])
            lines.append(f"Notes: {preview}")
            if len(content_lines) > 3:
                lines.append(f"  ... ({len(content_lines)} lines total)")

    projects = _get_projects_for_goal(goal_id)
    projects.sort(key=lambda p: p.get("stack_rank", 0))
    lines.append(f"\n**Projects ({len(projects)}):**")

    for proj in projects:
        all_tasks = _get_tasks_for_project(proj["id"])
        done_count = sum(1 for t in all_tasks if t.get("status") == "done")
        total = len(all_tasks)
        progress = f"{done_count}/{total} tasks done" if total else "no tasks"

        status_icon = {"done": "✓", "in_progress": "►", "blocked": "✕",
                       "deferred": "⏸", "not_started": "○",
                       }.get(proj.get("status", "not_started"), "?")

        p_rank = proj.get("stack_rank", 0)
        due_tag = f" — due {proj['due_date']}" if proj.get("due_date") else ""
        trello_tag = " ↔ Trello" if proj.get("trello") else ""
        deps = proj.get("depends_on", [])
        dep_tag = ""
        if deps:
            dep_ranks = []
            for did in deps:
                d = _load_entity(did)
                if d:
                    dep_ranks.append(f"P{d.get('stack_rank', '?')}")
            if dep_ranks:
                dep_tag = f" (depends on {', '.join(dep_ranks)})"

        proj_text = (
            f"P{p_rank} {status_icon} **{proj['name']}** ({proj['id']})"
            f" — {proj['status'].upper()}, {proj.get('priority', 'medium')} priority"
            f"{due_tag} ({progress}){trello_tag}{dep_tag}"
        )
        if proj.get("status") == "done":
            lines.append(f"• ~~{proj_text}~~")
        else:
            lines.append(f"• {proj_text}")

    full_text = "\n".join(lines)
    return _direct_display(
        full_text,
        context_footer=(
            "[Already displayed to the user — do NOT repeat or reformat. "
            "When the user says 'P1', 'P2', etc., find the project ID (p-...) next to that P-rank above "
            "and call get_project_detail with it. Do NOT call get_goal_detail again.]"
        ),
    )


def _render_trello_task_detail(task: dict, lines: list[str]):
    """Fetch live Trello card data and render it for entity detail view.

    Uses 2 direct API calls (card + comments) instead of the heavier
    get_card_details → _find_card chain (4 calls) to keep MCP subprocess fast.
    """
    from trello_task_sync import (
        get_project_trello_config, derive_status_from_list,
        derive_assignee_from_list,
    )

    card_id = task.get("trello_card_id")
    project = _load_entity(task.get("project_id", ""))
    if not project:
        lines.append(f"Trello card: {card_id} (project not found)")
        return

    config = get_project_trello_config(project)
    if not config:
        lines.append(f"Trello card: {card_id} (project not Trello-linked)")
        return

    board = config["board"]

    try:
        from trello_client import _request, get_board_config, get_lists
        account = get_board_config(board)["account"]

        # Call 1: card data (no nested checklists — unreliable)
        full = _request(
            "GET", f"/cards/{card_id}", account,
            {"fields": "name,desc,due,dueComplete,closed,labels,url,idList,pos"}
        )

        # Call 2: checklists via dedicated endpoint (reliable)
        try:
            raw_cls = _request(
                "GET", f"/cards/{card_id}/checklists", account, {}
            )
        except Exception:
            raw_cls = []

        # Map list ID → name for status/assignee derivation
        lists = get_lists(board)
        list_map = {l["id"]: l["name"] for l in lists}
        list_name = list_map.get(full.get("idList", ""), "(unknown)")

        # Call 3: comments
        try:
            actions = _request(
                "GET", f"/cards/{card_id}/actions", account,
                {"filter": "commentCard", "fields": "data,date,memberCreator", "limit": "20"}
            )
        except Exception:
            actions = []

    except Exception as e:
        lines.append(f"Trello card: {card_id} (fetch failed: {e})")
        logger.warning("TRELLO_TASK: card detail fetch failed for %s: %s", card_id, e)
        return

    # Status from list
    status = derive_status_from_list(list_name, config)
    lines.append(f"Status: {status.upper()} | List: {list_name}")

    # Assignee from list
    assignee = derive_assignee_from_list(list_name, config)
    if assignee:
        lines.append(f"Assigned to: {assignee}")

    # Labels
    label_names = [lb.get("name", lb.get("color", "?")) for lb in full.get("labels", []) if lb.get("name")]
    if label_names:
        lines.append(f"Labels: {', '.join(label_names)}")

    # Due date
    if full.get("due"):
        due_str = full["due"][:10]
        done_tag = " ✓" if full.get("dueComplete") else ""
        lines.append(f"Due: {due_str}{done_tag}")

    # Parse checklists
    cl_data = [
        {
            "name": cl.get("name", "Checklist"),
            "items": [
                {"name": ci["name"], "state": ci.get("state", "incomplete")}
                for ci in cl.get("checkItems", [])
            ],
        }
        for cl in raw_cls
    ]
    total_items = sum(len(cl["items"]) for cl in cl_data)
    done_items = sum(1 for cl in cl_data for ci in cl["items"] if ci["state"] == "complete")
    if total_items > 0:
        pct = int(done_items / total_items * 100)
        lines.append(f"Completion: {done_items}/{total_items} ({pct}%)")

    # Trello URL
    if full.get("url"):
        lines.append(f"Trello: {full['url']}")

    # Checklists BEFORE description (more actionable, avoids truncation)
    for cl in cl_data:
        lines.append(f"\n**{cl['name']}:**")
        for ci in cl["items"]:
            check = "☑" if ci["state"] == "complete" else "☐"
            lines.append(f"  {check} {ci['name']}")

    # Description
    desc = full.get("desc", "").strip()
    if desc:
        lines.append(f"\n**Description:**")
        lines.append(desc)

    # Comments
    comments = [
        {
            "text": a.get("data", {}).get("text", ""),
            "date": a.get("date", ""),
            "author": a.get("memberCreator", {}).get("fullName", ""),
        }
        for a in actions
    ]
    if comments:
        lines.append(f"\n**Comments ({len(comments)}):**")
        for c in comments[:10]:
            lines.append(f"  [{c['date'][:10]}] {c['author']}: {c['text']}")
        if len(comments) > 10:
            lines.append(f"  ... ({len(comments) - 10} more)")


def _render_trello_project_view(project: dict, all_tasks: list[dict],
                                lines: list[str]):
    """Render a Trello-linked project view with live API data.

    Groups tasks by Trello list in left-to-right board order.
    Local (non-Trello) tasks shown at the end.
    """
    from trello_task_sync import (
        get_live_project_data, derive_status_from_list,
        derive_assignee_from_list,
    )

    config = project.get("trello", {})
    live = get_live_project_data(project)

    if isinstance(live, str):
        # API error — fall back to basic task list
        lines.append(f"⚠ Trello fetch failed: {live}")
        lines.append(f"Tasks: {len(all_tasks)} total")
        for t in sorted(all_tasks, key=lambda x: x.get("stack_rank", 0)):
            rank = t.get("stack_rank", "?")
            lines.append(f"  T{rank} ({t['id']}) {t['name']} — {t.get('status', '?').upper()}")
        return

    cards_by_list = live["cards_by_list"]
    list_order = live["list_order"]
    task_card_map = live["task_card_map"]

    # Build card_id → task lookup
    trello_tasks = {}
    local_tasks = []
    for t in all_tasks:
        cid = t.get("trello_card_id")
        if cid and t.get("trello_linked"):
            trello_tasks[cid] = t
        else:
            local_tasks.append(t)

    trello_count = len(trello_tasks)
    local_count = len(local_tasks)
    lines.append(f"Tasks: {len(all_tasks)} total ({trello_count} Trello-linked, {local_count} local)")

    # Compute completion % (done tasks / total tasks)
    done_count = 0
    done_list_name = config.get("done_list", "Done")
    for t in all_tasks:
        cid = t.get("trello_card_id")
        if cid and cid in task_card_map:
            card = task_card_map[cid]
            if card.get("list_name", "").strip().lower() == done_list_name.strip().lower():
                done_count += 1
        elif t.get("status") == "done":
            done_count += 1
    if all_tasks:
        pct = int(done_count / len(all_tasks) * 100)
        lines.append(f"Completion: {done_count}/{len(all_tasks)} ({pct}%)")

    # Assign stack ranks based on Trello card order across all lists
    rank_counter = 1
    ranked_card_ids = set()

    # Silent name sync + rank assignment in Trello list order
    for list_name in list_order:
        for card in cards_by_list.get(list_name, []):
            cid = card["id"]
            if cid in trello_tasks:
                task = trello_tasks[cid]
                # Silent name sync
                if task.get("name") != card["name"]:
                    task["name"] = card["name"]
                    _save_entity(task)
                # Update stack rank
                if task.get("stack_rank") != rank_counter:
                    task["stack_rank"] = rank_counter
                    _save_entity(task)
                ranked_card_ids.add(cid)
                rank_counter += 1

    # Rank local tasks after Trello tasks
    for t in sorted(local_tasks, key=lambda x: x.get("stack_rank", 0)):
        if t.get("stack_rank") != rank_counter:
            t["stack_rank"] = rank_counter
            _save_entity(t)
        rank_counter += 1

    # ── Render Trello list sections ──────────────────────────────────
    user_lists = config.get("user_lists", {})
    # Reverse lookup: list_name → username
    list_to_user = {}
    for user, ulist in user_lists.items():
        list_to_user[ulist.strip().lower()] = user

    for list_name in list_order:
        cards_in_list = cards_by_list.get(list_name, [])
        # Only show lists that have adopted cards
        adopted_in_list = [c for c in cards_in_list if c["id"] in trello_tasks]
        if not adopted_in_list:
            continue

        # Section header with user assignment
        user_tag = ""
        user = list_to_user.get(list_name.strip().lower())
        if user:
            user_tag = f" [{user}]"
        lines.append(f"\n--- Trello: {list_name}{user_tag} ---")

        for card in adopted_in_list:
            task = trello_tasks[card["id"]]
            rank = task.get("stack_rank", "?")

            # Checklist summary
            check_str = ""
            ct = card.get("check_total", 0)
            cd = card.get("check_done", 0)
            if ct > 0:
                check_str = f" (checklist: {cd}/{ct})"

            # Due date
            due_str = ""
            if card.get("due"):
                due_str = f"  [due {card['due'][:10]}]"

            lines.append(
                f"  T{rank} ({task['id']}) {card['name']}{check_str}{due_str}"
            )

    # ── Local tasks section ──────────────────────────────────────────
    if local_tasks:
        lines.append(f"\n--- Local tasks ---")
        for t in sorted(local_tasks, key=lambda x: x.get("stack_rank", 0)):
            rank = t.get("stack_rank", "?")
            status = t.get("status", "not_started").upper()
            due_str = ""
            if t.get("due_date"):
                due_str = f"  [due {t['due_date']}]"
            task_text = f"  T{rank} ({t['id']}) {t['name']} — {status}{due_str}"
            if t.get("status") == "done":
                lines.append(f"  ~~{task_text.strip()}~~")
            else:
                lines.append(task_text)

    # Auto-remove task skeletons whose Trello cards are archived/missing
    orphans = [
        (cid, task) for cid, task in trello_tasks.items()
        if cid not in task_card_map and cid not in ranked_card_ids
    ]
    for cid, task in orphans:
        task_name = task.get("name", "?")
        task_id = task["id"]
        # Remove from project's task list and delete skeleton
        proj_tasks = project.get("tasks", [])
        if task_id in proj_tasks:
            proj_tasks.remove(task_id)
            _save_entity(project)
        _delete_entity(task_id)
        try:
            from link_registry import delete_links_for_entity
            delete_links_for_entity(task_id)
        except Exception:
            pass
        lines.append(f"\n⚠ Removed {task_id} ({task_name}) — card archived/missing on Trello")
        logger.info("TRELLO_TASK: Auto-removed orphan task %s (%s) — card %s gone",
                     task_id, task_name, cid)


def get_project_detail(project_id: str) -> str:
    """Project detail view: project info + full task tree.

    Shows all milestones, subtasks, and uncategorized tasks with T-ranks.
    """
    global _last_viewed_project, _last_viewed_goal
    project_id = _resolve_rank(project_id)
    project = _load_entity(project_id)
    if not project:
        return f"Error: Project '{project_id}' not found."

    _last_viewed_project = project_id

    # Find parent goal and set scope for future P-rank resolution
    goal_name = ""
    for g in _list_entities("g-"):
        if project_id in g.get("projects", []):
            goal_name = g.get("name", "")
            _last_viewed_goal = g["id"]
            break

    _save_view_context(goal=_last_viewed_goal, project=project_id)

    p_rank = project.get("stack_rank", 0)
    lines = []
    if goal_name:
        lines.append(f"Goal: {goal_name}")
    lines.append(f"**P{p_rank} — Project: {project['name']}** ({project_id})")
    lines.append(f"Status: {project['status'].upper()} | Priority: {project.get('priority', 'medium')}")
    lines.append(f"Owners: {', '.join(project.get('owners', []))}")
    if project.get("due_date"):
        lines.append(f"Due: {project['due_date']}")
    if project.get("trello"):
        lines.append(f"Trello: {project['trello'].get('board', '?')}")

    # Nag info
    nag_config = project.get("auto_nag")
    if nag_config and nag_config.get("enabled"):
        nag_task = get_next_naggable_task(project_id)
        if nag_task:
            lines.append(f"Next actionable: T{nag_task.get('stack_rank', '?')} {nag_task['name']}")

    all_tasks = _get_tasks_for_project(project_id)

    # ── Trello-linked project: live API rendering ────────────────────
    trello_config = project.get("trello")
    if trello_config and trello_config.get("board"):
        _render_trello_project_view(project, all_tasks, lines)
    else:
        # ── Standard task tree rendering ─────────────────────────────
        top_tasks = [t for t in all_tasks if not t.get("parent_task_id")]
        top_tasks.sort(key=lambda t: t.get("stack_rank", 0))
        lines.append(f"Tasks: {len(all_tasks)} total, {len(top_tasks)} top-level")

        if top_tasks:
            _render_task_tree(top_tasks, lines, indent=0)
        else:
            lines.append("\n(no tasks)")

    full_text = "\n".join(lines)
    return _direct_display(
        full_text,
        context_footer=(
            "[Already displayed to the user — do NOT repeat or reformat. "
            "T-ranks auto-resolve: call get_entity_detail('T1') directly — do NOT call "
            "get_project_detail again to look up a T-rank. The ID is resolved automatically.]"
        ),
    )


def get_entity_detail(item_id: str) -> str:
    """Full record inspection for any goal, project, or task.

    Accepts entity IDs (g-xxx, p-xxx, t-xxx) OR rank references (G1, P2, T5).
    T-ranks auto-resolve — pass 'T1' directly, do NOT call get_project_detail first.

    Returns all fields, notes, history, artifacts, and linked entities.
    Use when the user asks for "details on X", "show me T5", "show me all the info on T5", etc.
    """
    item_id = _resolve_rank(item_id)
    entity = _load_entity(item_id)
    if not entity:
        return f"Error: Entity '{item_id}' not found."

    lines: list[str] = []
    etype = "Goal" if item_id.startswith("g-") else \
            "Project" if item_id.startswith("p-") else \
            "Task" if item_id.startswith("t-") else "Entity"

    # ── Header ────────────────────────────────────────────────────────
    lines.append(f"**{etype}: {entity['name']}** ({item_id})")

    # ── Core fields ───────────────────────────────────────────────────
    is_trello_linked = (
        item_id.startswith("t-")
        and entity.get("trello_linked")
        and entity.get("trello_card_id")
    )
    # Trello-linked tasks: status & assignment come from live card data
    if not is_trello_linked:
        lines.append(f"Status: {entity.get('status', '?').upper()}")
    if entity.get("priority"):
        lines.append(f"Priority: {entity['priority']}")
    if entity.get("owners"):
        lines.append(f"Owners: {', '.join(entity['owners'])}")
    if not is_trello_linked and entity.get("assigned_to"):
        lines.append(f"Assigned to: {', '.join(entity['assigned_to'])}")
    if entity.get("due_date"):
        lines.append(f"Due date: {entity['due_date']}")
    if entity.get("target_date"):
        lines.append(f"Target date: {entity['target_date']}")
    lines.append(f"Created: {entity.get('created_at', '?')[:16]} by {entity.get('created_by', '?')}")

    # ── Task-specific fields ──────────────────────────────────────────
    if item_id.startswith("t-"):
        lines.append(f"Stack rank: T{entity.get('stack_rank', '?')}")
        if entity.get("project_id"):
            proj = _load_entity(entity["project_id"])
            pname = proj["name"] if proj else entity["project_id"]
            lines.append(f"Project: {pname} ({entity['project_id']})")
        if entity.get("parent_task_id"):
            parent = _load_entity(entity["parent_task_id"])
            pname = parent["name"] if parent else entity["parent_task_id"]
            lines.append(f"Parent task: {pname} ({entity['parent_task_id']})")
        if entity.get("subtasks"):
            sub_names = []
            for sid in entity["subtasks"]:
                sub = _load_entity(sid)
                sub_names.append(f"T{sub.get('stack_rank', '?')} {sub['name']} ({sid})" if sub else sid)
            lines.append(f"Subtasks ({len(sub_names)}):")
            for sn in sub_names:
                lines.append(f"  • {sn}")
        if entity.get("depends_on"):
            dep_names = []
            for did in entity["depends_on"]:
                dep = _load_entity(did)
                dep_names.append(f"T{dep.get('stack_rank', '?')} {dep['name']} ({did})" if dep else did)
            lines.append(f"Dependencies: {', '.join(dep_names)}")

        # ── Trello-linked task: live card data ───────────────────────
        if entity.get("trello_linked") and entity.get("trello_card_id"):
            _render_trello_task_detail(entity, lines)
        else:
            if entity.get("trello_card_id"):
                lines.append(f"Trello card: {entity['trello_card_id']}")
            if entity.get("trello_list"):
                lines.append(f"Trello list: {entity['trello_list']}")

    # ── Project-specific fields ───────────────────────────────────────
    if item_id.startswith("p-"):
        if entity.get("goal_id"):
            goal = _load_entity(entity["goal_id"])
            gname = goal["name"] if goal else entity["goal_id"]
            lines.append(f"Goal: {gname} ({entity['goal_id']})")
        task_ids = entity.get("tasks", [])
        if task_ids:
            lines.append(f"Tasks: {len(task_ids)} total")
        nag = entity.get("auto_nag")
        if nag and nag.get("enabled"):
            nag_task = _load_entity(nag.get("current_task_id", ""))
            nag_name = nag_task["name"] if nag_task else nag.get("current_task_id", "none")
            lines.append(f"Auto-nag: enabled (current: {nag_name})")
        if entity.get("trello"):
            lines.append(f"Trello board: {entity['trello'].get('board', '?')}")

    # ── Goal-specific fields ──────────────────────────────────────────
    if item_id.startswith("g-"):
        proj_ids = entity.get("projects", [])
        if proj_ids:
            lines.append(f"Projects: {len(proj_ids)} total")

    # ── Artifacts ─────────────────────────────────────────────────────
    artifacts = entity.get("artifacts", [])
    if artifacts:
        from artifact_store import load_artifact
        lines.append(f"\n**Artifacts ({len(artifacts)}):**")
        for aid in artifacts:
            art = load_artifact(aid)
            if art:
                lines.append(f"• {art.get('filename', aid)} ({aid}) — {art.get('content_type', '?')}")
            else:
                lines.append(f"• {aid} (not found)")

    # ── Notes ─────────────────────────────────────────────────────────
    notes = _load_notes(item_id)
    if notes.strip():
        lines.append(f"\n**Notes:**")
        lines.append(notes.strip())

    # ── History ───────────────────────────────────────────────────────
    history = entity.get("history", [])
    if history:
        lines.append(f"\n**History ({len(history)} entries):**")
        for h in history[-10:]:
            lines.append(f"[{h.get('timestamp', '?')[:16]}] {h.get('by', '?')}: {h.get('note', '')}")
        if len(history) > 10:
            lines.append(f"... ({len(history) - 10} older entries not shown)")

    # ── Linked entities ───────────────────────────────────────────────
    try:
        from link_registry import get_links
        links = get_links(item_id)
        if links:
            lines.append(f"\n**Linked entities ({len(links)}):**")
            for lnk in links:
                other = lnk.get("target_id") if lnk.get("source_id") == item_id else lnk.get("source_id")
                other_ent = _load_entity(other) if other else None
                other_name = other_ent["name"] if other_ent else other
                lines.append(f"• {other_name} ({other}) — {lnk.get('relation', '?')}")
    except Exception:
        pass  # link_registry may not exist or have issues

    full_text = "\n".join(lines)

    # Trello-linked tasks use direct display to bypass LLM reformatting
    is_trello_task = (
        item_id.startswith("t-")
        and entity.get("trello_linked")
        and entity.get("trello_card_id")
    )
    if is_trello_task:
        return _direct_display(
            full_text,
            context_footer=(
                "[Already displayed to the user — do NOT repeat or reformat. "
                "Only answer follow-up questions. Use the entity ID above for any actions.]"
            ),
        )

    return full_text


def get_user_tasks(
    user_id: str,
    status_filter: str = "",
) -> str:
    """Get all tasks assigned to a user across all goals."""
    user = user_id.lower().strip()
    if not user:
        return "Error: user_id is required."

    status_f = status_filter.lower().strip() if status_filter else ""
    show_all = status_f == "all"

    # Build project→goal lookup
    projects = {p["id"]: p for p in _list_entities("p-")}
    goals = {g["id"]: g for g in _list_entities("g-")}

    all_tasks = []
    for task in _list_entities("t-"):
        if user in [a.lower() for a in task.get("assigned_to", [])]:
            task_status = task.get("status", "not_started")
            if status_f and not show_all and task_status != status_f:
                continue
            if not status_f and task_status == "done":
                continue
            proj = projects.get(task.get("project_id", ""), {})
            goal = goals.get(proj.get("goal_id", ""), {})
            all_tasks.append({
                "task": task,
                "project_name": proj.get("name", "?"),
                "project_id": proj.get("id", "?"),
                "goal_name": goal.get("name", "?"),
                "goal_id": goal.get("id", "?"),
            })

    if not all_tasks:
        msg = f"No tasks found for {user}"
        if status_f and not show_all:
            msg += f" with status '{status_f}'"
        elif not status_f:
            msg += " (excluding done)"
        return msg + "."

    lines = [f"Tasks for {user} ({len(all_tasks)} found):\n"]

    for status in ["blocked", "in_progress", "not_started", "deferred", "done"]:
        tasks_in_status = [t for t in all_tasks if t["task"].get("status") == status]
        if not tasks_in_status:
            continue
        lines.append(f"  {status.upper()} ({len(tasks_in_status)}):")
        for t in tasks_in_status:
            task = t["task"]
            rank = task.get("stack_rank", "?")
            due = f" (due: {task['due_date']})" if task.get("due_date") else ""
            pri = f" [{task.get('priority', 'medium')}]"
            trello_tag = f" [Trello: {task['trello_list']}]" if task.get("trello_list") else ""
            lines.append(f"    T{rank} [{task['id']}] {task['name']}{pri}{due}{trello_tag}")
            lines.append(f"      → {t['goal_name']} / {t['project_name']}")
        lines.append("")

    return "\n".join(lines)


def search_items(query: str) -> str:
    """Search across all goals, projects, and tasks by keyword.

    Searches names, notes, and history notes (case-insensitive).
    """
    q = query.lower().strip()
    if not q:
        return "Error: search query is required."

    results = {"goals": [], "projects": [], "tasks": []}

    goals = {g["id"]: g for g in _list_entities("g-")}
    projects = {p["id"]: p for p in _list_entities("p-")}

    for goal in goals.values():
        if _matches(goal, q):
            results["goals"].append(goal)

    for proj in projects.values():
        if _matches(proj, q):
            goal = goals.get(proj.get("goal_id", ""), {})
            results["projects"].append((proj, goal))

    for task in _list_entities("t-"):
        if _matches(task, q):
            proj = projects.get(task.get("project_id", ""), {})
            goal = goals.get(proj.get("goal_id", ""), {})
            results["tasks"].append((task, proj, goal))

    total = sum(len(v) for v in results.values())
    if total == 0:
        return f"No results found for '{query}'."

    lines = [f"Search results for '{query}' ({total} found):\n"]

    if results["goals"]:
        lines.append(f"  Goals ({len(results['goals'])}):")
        for g in results["goals"]:
            lines.append(f"    [{g['id']}] {g['name']} — {g['status'].upper()}")
        lines.append("")

    if results["projects"]:
        lines.append(f"  Projects ({len(results['projects'])}):")
        for proj, goal in results["projects"]:
            lines.append(
                f"    [{proj['id']}] {proj['name']} — {proj['status'].upper()}"
                f"  (goal: {goal.get('name', '?')})"
            )
        lines.append("")

    if results["tasks"]:
        lines.append(f"  Tasks ({len(results['tasks'])}):")
        for task, proj, goal in results["tasks"]:
            lines.append(
                f"    [{task['id']}] {task['name']} — {task['status'].upper()}"
                f"  (→ {goal.get('name', '?')} / {proj.get('name', '?')})"
            )
        lines.append("")

    return "\n".join(lines)


def set_due_date_reminder(
    item_id: str,
    user_id: str,
    days_before: int = 1,
    message: str = "",
) -> str:
    """Create a reminder for an entity's due/target date.

    Args:
        item_id: Entity ID with a due_date or target_date.
        user_id: Who to remind.
        days_before: How many days before the date to fire (default 1).
        message: Custom reminder message. Auto-generated if empty.

    Returns:
        Confirmation or error.
    """
    item = _find_item(item_id)
    if not item:
        return f"Error: Item '{item_id}' not found."

    date_key = "target_date" if item_id.startswith("g-") else "due_date"
    date_str = item.get(date_key, "")
    if not date_str:
        return f"Error: {_entity_type(item_id)} '{item_id}' has no {date_key.replace('_', ' ')} set."

    try:
        from datetime import timedelta
        from dateutil.parser import parse as parse_date
        from app_platform.reminders import create_reminder
        from link_registry import create_link

        due = parse_date(date_str)
        if due.tzinfo is None:
            due = due.replace(tzinfo=CENTRAL_TZ)

        remind_at = due - timedelta(days=days_before)
        remind_at = remind_at.replace(hour=9, minute=0, second=0)

        if not message:
            entity_type = _entity_type(item_id)
            message = f"{entity_type} due soon: {item.get('name', item_id)} (due {date_str})"

        reminder = create_reminder(
            user_id=user_id,
            message=message,
            remind_at=remind_at.isoformat(),
        )

        # Link the reminder to the entity
        create_link(
            source_id=reminder["id"],
            target_id=item_id,
            relation="reminds_about",
            created_by=user_id,
        )

        _add_history(item, user_id, f"Reminder {reminder['id']} set for {remind_at.strftime('%Y-%m-%d %H:%M')}")
        _save_entity(item)

        return (
            f"Reminder created (ID: {reminder['id']}) for {_entity_type(item_id)} '{item.get('name')}'.\n"
            f"  Fires: {remind_at.strftime('%Y-%m-%d %H:%M %Z')}\n"
            f"  Message: {message}\n"
            f"  Linked to: {item_id}"
        )
    except Exception as e:
        return f"Error creating due date reminder: {str(e)}"


def _matches(item: dict, query: str) -> bool:
    """Check if an item matches a search query."""
    searchable = item.get("name", "").lower()

    if query in searchable:
        return True

    # Check notes
    notes = _load_notes(item.get("id", "")).lower()
    if query in notes:
        return True

    for h in item.get("history", []):
        if query in h.get("note", "").lower():
            return True

    return False
