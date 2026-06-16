"""
Goal/Project/Task Tools - Manage hierarchical productivity tracking.
Goals → Projects → Tasks. All times use the configured TIMEZONE.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Ensure project root is importable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from apps.goals.store import (
    create_goal as _create_goal,
    create_project as _create_project,
    create_task as _create_task,
    update_item as _update_item,
    close_out_goal as _close_out_goal,
    update_notes as _update_notes,
    get_notes as _get_notes,
    get_goals_summary as _get_goals_summary,
    get_goal_detail as _get_goal_detail,
    get_project_detail as _get_project_detail,
    get_entity_detail as _get_entity_detail,
    get_user_tasks as _get_user_tasks,
    search_items as _search_items,
    set_due_date_reminder as _set_due_date_reminder,
    delete_item as _delete_item,
    get_next_naggable_task as _get_next_naggable_task,
    _load_entity,
    _save_entity,
    _get_tasks_for_project,
    _get_projects_for_goal,
    _add_history,
    _refresh_project_nag,
    _rerank_project,
    _rerank_goal,
    _rerank_goals,
    _resolve_rank,
)


def create_goal(
    name: str,
    created_by: str,
    owners: str = "",
    initial_notes: str = "",
    target_date: str = "",
) -> str:
    """Create a new goal.

    Args:
        name: Name of the goal.
        created_by: Who is creating this goal (person name, e.g. "alice").
        owners: Comma-separated list of people who own this goal.
                Defaults to created_by if empty.
        initial_notes: Optional initial content for the goal's notes document.
        target_date: Optional target completion date (e.g. "2026-06-01").

    Returns:
        Confirmation with goal ID.
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        owner_list = (
            [o.strip().lower() for o in owners.split(",") if o.strip()]
            if owners and owners.strip() else None
        )

        result = _create_goal(
            name=name.strip(),
            created_by=created_by.strip().lower(),
            description=initial_notes.strip() if initial_notes else "",
            owners=owner_list,
            target_date=target_date.strip() if target_date else "",
        )

        out = (
            f"Goal created (ID: {result['id']}).\n"
            f"  Name: {result['name']}\n"
            f"  Owners: {', '.join(result['owners'])}\n"
            f"  Status: {result['status']}\n"
        )
        if result.get("target_date"):
            out += f"  Target: {result['target_date']}\n"
        return out

    except Exception as e:
        return f"Error in create_goal: {str(e)}"


def create_project(
    goal_id: str,
    name: str,
    created_by: str,
    owners: str = "",
    initial_notes: str = "",
    due_date: str = "",
    priority: str = "medium",
) -> str:
    """Create a project under a goal.

    Args:
        goal_id: The parent goal ID (e.g. "g-a1b2c3d4").
        name: Name of the project.
        created_by: Who is creating this project (person name).
        owners: Comma-separated project owners. Defaults to created_by.
        initial_notes: Optional initial content for the project's notes document.
        due_date: Optional due date (e.g. "2026-03-15").
        priority: "low", "medium", or "high". Defaults to "medium".

    Returns:
        Confirmation with project ID.
    """
    try:
        if not goal_id or not goal_id.strip():
            return "Error: goal_id is required."
        if not name or not name.strip():
            return "Error: name is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        owner_list = (
            [o.strip().lower() for o in owners.split(",") if o.strip()]
            if owners and owners.strip() else None
        )

        result = _create_project(
            goal_id=goal_id.strip(),
            name=name.strip(),
            created_by=created_by.strip().lower(),
            description=initial_notes.strip() if initial_notes else "",
            owners=owner_list,
            due_date=due_date.strip() if due_date else "",
            priority=priority.strip().lower() if priority else "medium",
        )

        if isinstance(result, str):
            return result  # Error message

        out = (
            f"Project created (ID: {result['id']}) under goal {goal_id}.\n"
            f"  Name: {result['name']}\n"
            f"  Owners: {', '.join(result['owners'])}\n"
            f"  Priority: {result['priority']}\n"
            f"  Status: {result['status']}\n"
        )
        if result.get("due_date"):
            out += f"  Due: {result['due_date']}\n"
        return out

    except Exception as e:
        return f"Error in create_project: {str(e)}"


def create_task(
    project_id: str,
    name: str,
    created_by: str,
    assigned_to: str = "",
    due_date: str = "",
    priority: str = "medium",
    parent_task_id: str = "",
) -> str:
    """Create a task under a project, or a subtask under another task.

    Tasks form a tree: top-level tasks live under a project, subtasks live
    under a parent task. Subtasks inherit project_id from their root ancestor.
    Use this to build milestone → work-item hierarchies.

    Args:
        project_id: The parent project ID (e.g. "p-e5f6g7h8").
                    Required for top-level tasks. For subtasks, if omitted,
                    it is inherited from the parent task.
        name: Name/description of the task.
        created_by: Who is creating this task (person name).
        assigned_to: Comma-separated people assigned to this task.
                     Defaults to created_by if empty.
        due_date: Optional due date (e.g. "2026-02-14").
        priority: "low", "medium", or "high". Defaults to "medium".
        parent_task_id: Optional parent task ID (e.g. "t-abc123") to create
                        this as a subtask. The subtask will appear in the
                        parent's subtasks list and inherit its project_id.

    Returns:
        Confirmation with task ID.
    """
    try:
        if not parent_task_id or not parent_task_id.strip():
            parent_task_id_clean = None
            if not project_id or not project_id.strip():
                return "Error: project_id is required for top-level tasks."
        else:
            parent_task_id_clean = parent_task_id.strip()
        if not name or not name.strip():
            return "Error: name is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        assignee_list = (
            [a.strip().lower() for a in assigned_to.split(",") if a.strip()]
            if assigned_to and assigned_to.strip() else None
        )

        result = _create_task(
            project_id=project_id.strip() if project_id else "",
            name=name.strip(),
            created_by=created_by.strip().lower(),
            assigned_to=assignee_list,
            due_date=due_date.strip() if due_date else "",
            priority=priority.strip().lower() if priority else "medium",
            parent_task_id=parent_task_id_clean,
        )

        if isinstance(result, str):
            return result  # Error message

        if result.get("parent_task_id"):
            parent_label = f"subtask of {result['parent_task_id']}"
        else:
            parent_label = f"under project {result['project_id']}"

        out = (
            f"Task created (ID: {result['id']}) {parent_label}.\n"
            f"  Name: {result['name']}\n"
            f"  Assigned to: {', '.join(result['assigned_to'])}\n"
            f"  Priority: {result['priority']}\n"
            f"  Status: {result['status']}\n"
            f"  Stack rank: {result.get('stack_rank', '?')}\n"
        )
        if result.get("due_date"):
            out += f"  Due: {result['due_date']}\n"
        return out

    except Exception as e:
        return f"Error in create_task: {str(e)}"


def update_item(
    item_id: str,
    updated_by: str,
    status: str = "",
    history_note: str = "",
    fields_json: str = "",
) -> str:
    """Update any goal (g-xxx), project (p-xxx), or task (t-xxx).
    YOU MUST CALL THIS TOOL to change any goal, project, or task.
    Also use this to add comments to an entity's HISTORY LOG or change status.
    Only provide fields you want to change.
    IMPORTANT: history_note adds to the HISTORY LOG (timestamped activity feed).
    To update the NOTES DOCUMENT (stable project description), use update_entity_notes instead.
    Accepts rank references: "G3", "P2", "T5" — auto-resolved.

    The output is the ACTUAL SAVED STATE read back from disk after writing.
    You MUST report these values exactly as shown — do not paraphrase or infer.

    Args:
        item_id: Entity ID or rank reference (e.g. "t-i9j0k1l2", "G3", "P2", "T5").
        updated_by: Who is making this update (person name).
        status: New status: "not_started", "in_progress", "done",
                "blocked", "deferred", "cancelled". Leave empty to keep current.
        history_note: A timestamped comment added to the entity's HISTORY LOG.
                      Use this for incremental updates, findings, and directives.
                      This does NOT touch the notes document.
        fields_json: Optional JSON string of other fields to change.
                     Examples:
                       '{"name": "New task name"}'
                       '{"priority": "high", "due_date": "2026-03-01"}'
                       '{"assigned_to": "carol,alice"}'
                       '{"owners": "alice"}'
                       '{"definition_of_done": "All tests pass and PR approved"}'
                       '{"pm_cadence_minutes": 1440}'  (projects only — PM check-in interval in minutes, null to reset to default)

    Returns:
        VERIFIED saved state. Report these values exactly.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        _goal_prefixes = ("g-", "p-", "t-")
        _item_id_clean = item_id.strip()
        if not any(_item_id_clean.startswith(p) for p in _goal_prefixes) and not _item_id_clean[0].isupper():
            # Entity belongs to a different app — redirect rather than silently failing
            _hint_map = {
                "vis-": "update_vehicle_issue",
                "veh-": "update_vehicle",
                "svc-": "(no update tool — use the Auto app UI)",
                "sch-": "(schedules have no direct update tool — use the Schedules API)",
                "re-": "(use the Recipes app)",
                "tp-": "(use the Timeline app)",
                "ml-": "(use the Meals app)",
            }
            _hint = next((v for k, v in _hint_map.items() if _item_id_clean.startswith(k)), None)
            _redirect = f" Use {_hint} instead." if _hint else ""
            return (
                f"Error: '{_item_id_clean}' is not a goal, project, or task ID "
                f"(those start with g-, p-, or t-).{_redirect}"
            )

        fields = None
        if fields_json and fields_json.strip():
            import json
            try:
                fields = json.loads(fields_json.strip())
            except json.JSONDecodeError as e:
                return f"Error: Invalid fields_json: {str(e)}"

        resolved_id = _resolve_rank(item_id.strip())
        return _update_item(
            item_id=resolved_id,
            updated_by=updated_by.strip().lower(),
            status=status.strip() if status else "",
            history_note=history_note.strip() if history_note else "",
            fields=fields,
        )

    except Exception as e:
        return f"Error in update_item: {str(e)}"


def stop_onboarding(requested_by: str) -> str:
    """Stop / close out the first-run onboarding ("Get started with Skipper").

    Call this when the primary user asks to stop, end, skip, or be done with the
    onboarding — AFTER you have confirmed they want to set it aside (see the
    proactive reply guide). This durably closes the onboarding goal out: it marks
    the onboarding goal and all its still-open projects/tasks as cancelled,
    disables the goal's thinking domain, and clears its pending PM nudges, so
    Skipper stops reaching out about onboarding. This is the correct action — do
    NOT just record a memory, which leaves the onboarding running.

    The onboarding goal is resolved internally from the platform's seed config;
    this tool deliberately takes NO goal id, so it can only ever close onboarding.
    Onboarding can be brought back later by reopening that goal.

    Args:
        requested_by: Who asked to stop onboarding (person name).

    Returns:
        Confirmation string, or a note that there's nothing to stop.
    """
    try:
        if not requested_by or not requested_by.strip():
            return "Error: requested_by is required."

        from app_platform import config as platform_config
        seeded = platform_config.get("onboarding_seeded", scope="app:goals") or {}
        goal_id = seeded.get("goal_id")
        if not goal_id:
            return ("There's nothing to stop — onboarding isn't set up "
                    "(no onboarding goal exists).")

        return _close_out_goal(
            goal_id,
            by=requested_by.strip().lower(),
            status="cancelled",
            reason="User asked to stop onboarding — closing it out.",
        )
    except Exception as e:
        return f"Error in stop_onboarding: {str(e)}"


def get_goals_summary(user_id: str) -> str:
    """Get an overview of the user's goals with progress percentages.

    ALWAYS pass the requesting user's name as user_id — never leave it empty.

    Args:
        user_id: The person's name (e.g. "alice"). Required — filters to goals
                 this person owns or has tasks in.

    Returns:
        Formatted summary of goals and task progress.
    """
    try:
        return _get_goals_summary(user_id=user_id.strip() if user_id else "")
    except Exception as e:
        return f"Error in get_goals_summary: {str(e)}"


def get_goal_detail(goal_id: str) -> str:
    """Get a goal summary: goal info + project list with progress.

    Shows each project's name, status, priority, due date, and task completion
    count. Does NOT show individual tasks — use get_project_detail for that.

    Accepts G-rank references: pass "G3" or "g3" and the tool resolves it.

    Args:
        goal_id: Goal ID ("g-a1b2c3d4") OR G-rank ("G3", "g3"). NOT P-rank.

    Returns:
        Goal summary with project list.
    """
    try:
        if not goal_id or not goal_id.strip():
            return "Error: goal_id is required."
        return _get_goal_detail(goal_id.strip())
    except Exception as e:
        return f"Error in get_goal_detail: {str(e)}"


def get_project_detail(project_id: str) -> str:
    """Get a project's full task tree: project info + all milestones, subtasks,
    and uncategorized tasks with T-ranks.

    Use this when the user asks to see a specific project or its tasks.
    Accepts P-rank references: pass "P2" or "p2" and the tool resolves it
    within the last-viewed goal. Or pass the project ID directly.

    Args:
        project_id: Project ID ("p-a1b2c3d4") OR P-rank ("P2", "p2").

    Returns:
        Project detail view with task tree.
    """
    try:
        if not project_id or not project_id.strip():
            return "Error: project_id is required."
        return _get_project_detail(project_id.strip())
    except Exception as e:
        return f"Error in get_project_detail: {str(e)}"


def get_entity_detail(item_id: str) -> str:
    """Get the full record for any goal, project, or task — all fields, notes,
    history, artifacts, and linked entities.

    Use this when the user asks for "details on X", "show me all the info on T5",
    "what are the details of this project", etc.
    Accepts rank references: "G3", "P2", "T5" — resolved within the
    last-viewed goal (for P-ranks) or project (for T-ranks).

    Args:
        item_id: Entity ID ("g-xxx", "p-xxx", "t-xxx") OR rank ("G3", "P2", "T5").

    Returns:
        Full record dump with all fields and metadata.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        return _get_entity_detail(item_id.strip())
    except Exception as e:
        return f"Error in get_entity_detail: {str(e)}"


def get_my_tasks(user_id: str, status_filter: str = "") -> str:
    """Get all tasks assigned to a person across all goals and projects.

    Args:
        user_id: Whose tasks to show (e.g. "alice", "carol").
        status_filter: Optional. A specific status like "in_progress" or "blocked".
                       Default shows all tasks except 'done'.
                       Use "all" to include done tasks too.

    Returns:
        Formatted list of tasks grouped by status.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        return _get_user_tasks(
            user_id=user_id.strip(),
            status_filter=status_filter.strip() if status_filter else "",
        )
    except Exception as e:
        return f"Error in get_my_tasks: {str(e)}"


def search_goals(query: str) -> str:
    """Search across all goals, projects, and tasks by keyword.
    Searches names, notes, and history.

    Args:
        query: Search term (case-insensitive).

    Returns:
        Matching items grouped by type (goals, projects, tasks).
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."
        return _search_items(query.strip())
    except Exception as e:
        return f"Error in search_goals: {str(e)}"


def update_entity_notes(
    item_id: str,
    content: str,
    updated_by: str = "",
) -> str:
    """Update the NOTES DOCUMENT (stable description) for a goal, project, or task.

    Each entity has a notes.md file — a stable description document.
    Use this for the project/task description, scope, key decisions, and design context.
    Do NOT use this for incremental status updates — use update_item(history_note=...) instead.
    This REPLACES the entire notes content; read it first if you need to preserve existing text.
    Accepts rank references: "G3", "P2", "T5" — auto-resolved.

    Args:
        item_id: Entity ID or rank reference (e.g. "g-a1b2c3d4", "G3", "P2", "T5").
        content: Full markdown content for the notes file.
        updated_by: Who is making this update (person name).

    Returns:
        Confirmation.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not content:
            return "Error: content is required."
        resolved_id = _resolve_rank(item_id.strip())
        return _update_notes(
            item_id=resolved_id,
            content=content,
            updated_by=updated_by.strip().lower() if updated_by else "",
        )
    except Exception as e:
        return f"Error in update_entity_notes: {str(e)}"


def get_entity_notes(item_id: str) -> str:
    """Read the notes document for a goal, project, or task.
    Accepts rank references: "G3", "P2", "T5" — auto-resolved.

    Args:
        item_id: Entity ID or rank reference (e.g. "g-a1b2c3d4", "G3", "P2", "T5").

    Returns:
        The markdown content of the entity's notes, or a message if empty.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        return _get_notes(_resolve_rank(item_id.strip()))
    except Exception as e:
        return f"Error in get_entity_notes: {str(e)}"


def append_entity_note(
    item_id: str,
    note: str,
    author: str = "",
) -> str:
    """Append text to a goal/project/task's NOTES DOCUMENT (stable description).

    This modifies the NOTES DOCUMENT, not the history log.
    For incremental status updates and comments, prefer update_item(history_note=...) instead.
    Unlike update_entity_notes, this NEVER overwrites — it atomically appends.
    Accepts rank references: "G3", "P2", "T5" — auto-resolved.

    Args:
        item_id: Entity ID or rank reference (e.g. "g-a1b2c3d4", "G3", "P2", "T5").
        note: The note text to append (markdown supported).
        author: Who is writing this note (e.g. "PM Review", "alice").

    Returns:
        Confirmation.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not note or not note.strip():
            return "Error: note content is required."
        resolved_id = _resolve_rank(item_id.strip())
        from datetime import datetime
        from app_platform.time import get_timezone
        timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M")
        label = f"**{author.strip()}**" if author and author.strip() else "**Note**"
        entry = f"\n\n---\n{label} ({timestamp}): {note.strip()}\n"
        from apps.goals.data import append_note
        append_note(resolved_id, entry)
        return f"Note appended to {resolved_id}."
    except Exception as e:
        return f"Error in append_entity_note: {str(e)}"


def set_due_reminder(
    item_id: str,
    user_id: str,
    days_before: int = 1,
    message: str = "",
) -> str:
    """Set a reminder for a goal/project/task's due date.

    Automatically creates a reminder that fires before the due date
    and links it to the entity. The entity must have a due_date or target_date set.
    Accepts rank references: "G3", "P2", "T5" — auto-resolved.

    Args:
        item_id: Entity ID or rank reference (e.g. "g-xxx", "G3", "P2", "T5").
        user_id: Who to remind (person name).
        days_before: How many days before the due date to fire. Default 1.
        message: Custom message. Auto-generated if empty.

    Returns:
        Confirmation with reminder details.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        return _set_due_date_reminder(
            item_id=_resolve_rank(item_id.strip()),
            user_id=user_id.strip().lower(),
            days_before=days_before,
            message=message.strip() if message else "",
        )
    except Exception as e:
        return f"Error in set_due_reminder: {str(e)}"


def delete_item(
    item_id: str,
    deleted_by: str,
) -> str:
    """Permanently delete a goal, project, or task.

    Deleting is recursive:
    - Deleting a goal also deletes all its projects and their tasks.
    - Deleting a project also deletes all its tasks.
    - Deleting a task only removes that task.

    Parent references and links are cleaned up automatically.
    Accepts rank references: "G3", "P2", "T5" — auto-resolved.

    Args:
        item_id: Entity ID or rank reference (e.g. "g-xxx", "G3", "P2", "T5").
        deleted_by: Who is performing the deletion (person name).

    Returns:
        Confirmation of what was deleted.
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."
        if not deleted_by or not deleted_by.strip():
            return "Error: deleted_by is required."
        return _delete_item(
            item_id=_resolve_rank(item_id.strip()),
            deleted_by=deleted_by.strip().lower(),
        )
    except Exception as e:
        return f"Error in delete_item: {str(e)}"


def set_task_order(
    project_id: str,
    task_ids: str,
    updated_by: str,
) -> str:
    """Set the stack-rank order of tasks in a project.

    Provide task IDs in priority order (first = highest priority, nagged first).
    Tasks not listed keep their current rank but are pushed after listed ones.

    Args:
        project_id: The project ID (e.g. "p-abc123").
        task_ids: Comma-separated task IDs in desired order, highest priority first.
                  Example: "t-aaa,t-bbb,t-ccc"
        updated_by: Who is reordering (person name).

    Returns:
        Confirmation with new ordering.

    Ack: Reordering tasks...
    """
    try:
        if not project_id or not project_id.strip():
            return "Error: project_id is required."
        if not task_ids or not task_ids.strip():
            return "Error: task_ids is required (comma-separated)."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        project = _load_entity(project_id.strip())
        if not project or not project_id.strip().startswith("p-"):
            return f"Error: Project '{project_id}' not found."

        ordered = [tid.strip() for tid in task_ids.split(",") if tid.strip()]
        all_tasks = _get_tasks_for_project(project_id.strip())
        task_map = {t["id"]: t for t in all_tasks}

        # Validate all provided IDs
        for tid in ordered:
            if tid not in task_map:
                return f"Error: Task '{tid}' not found in project '{project_id}'."

        # Assign ranks: listed tasks get 1, 2, 3...; unlisted get pushed after
        rank = 1
        updated = []
        for tid in ordered:
            task = task_map[tid]
            task["stack_rank"] = rank
            _add_history(task, updated_by.strip().lower(), f"Stack rank set to {rank}")
            _save_entity(task)
            updated.append(f"  T{rank} {task['name']} ({tid})")
            rank += 1

        # Unlisted tasks get ranks after the listed ones
        for task in all_tasks:
            if task["id"] not in ordered:
                task["stack_rank"] = rank
                _save_entity(task)
                updated.append(f"  T{rank} {task['name']} ({task['id']}) [unchanged]")
                rank += 1

        _refresh_project_nag(project_id.strip(), reason="task reorder")
        return f"Task order set for {project_id}:\n" + "\n".join(updated)

    except Exception as e:
        return f"Error in set_task_order: {str(e)}"


def set_task_dependency(
    task_id: str,
    depends_on: str,
    updated_by: str,
) -> str:
    """Set dependencies on a task — which other tasks must complete first.

    If a task has unfinished dependencies, it is considered blocked and will be
    skipped by the auto-nag system. When all dependencies complete, the task is
    automatically unblocked.

    Args:
        task_id: The task to set dependencies on (e.g. "t-abc123").
        depends_on: Comma-separated task IDs this task depends on.
                    Example: "t-xxx,t-yyy". Use empty string to clear dependencies.
        updated_by: Who is making this change (person name).

    Returns:
        Confirmation with dependency list.

    Ack: Setting task dependencies...
    """
    try:
        if not task_id or not task_id.strip():
            return "Error: task_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        task = _load_entity(task_id.strip())
        if not task or not task_id.strip().startswith("t-"):
            return f"Error: Task '{task_id}' not found."

        dep_ids = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []

        # Validate dependency IDs
        for dep_id in dep_ids:
            dep = _load_entity(dep_id)
            if not dep or not dep_id.startswith("t-"):
                return f"Error: Dependency '{dep_id}' is not a valid task."
            if dep_id == task_id.strip():
                return "Error: A task cannot depend on itself."

        old_deps = task.get("depends_on", [])
        task["depends_on"] = dep_ids
        _add_history(task, updated_by.strip().lower(),
                     f"Dependencies set: {dep_ids}" if dep_ids else "Dependencies cleared")
        _save_entity(task)

        # Re-rank (deps affect topological order) & re-evaluate nag
        proj_id = task.get("project_id")
        if proj_id:
            _rerank_project(proj_id)
            _refresh_project_nag(proj_id, reason=f"dependency change on {task_id}")

        if dep_ids:
            dep_names = []
            for did in dep_ids:
                d = _load_entity(did)
                dep_names.append(f"  {did}: {d['name']} ({d.get('status', '?')})")
            return (
                f"Task '{task['name']}' ({task_id}) now depends on:\n"
                + "\n".join(dep_names)
            )
        else:
            return f"Dependencies cleared for task '{task['name']}' ({task_id})."

    except Exception as e:
        return f"Error in set_task_dependency: {str(e)}"


def enable_project_nag(
    project_id: str,
    user_id: str,
) -> str:
    """Enable auto-nagging on a project.

    Creates a daily nag reminder that automatically advances through the project's
    tasks in stack-rank order. When a task is completed, the nag updates to the
    next actionable (non-blocked, non-done) task. Tasks with unfinished dependencies
    are skipped.

    Only one auto-nag per project. Use set_task_order to control which task is
    nagged first, and set_task_dependency to mark blockers.

    Args:
        project_id: The project to nag about (e.g. "p-abc123").
        user_id: Who to nag (e.g. "alice").

    Returns:
        Confirmation with the current nag task.

    Ack: Enabling auto-nag on project...
    """
    try:
        if not project_id or not project_id.strip():
            return "Error: project_id is required."
        if not user_id or not user_id.strip():
            return "Error: user_id is required."

        project = _load_entity(project_id.strip())
        if not project or not project_id.strip().startswith("p-"):
            return f"Error: Project '{project_id}' not found."

        # Check if already enabled
        if project.get("auto_nag") and project["auto_nag"].get("enabled"):
            nag_id = project["auto_nag"].get("nag_id", "?")
            return (
                f"Auto-nag already enabled on '{project['name']}' "
                f"(nag: {nag_id}). Disable first to reconfigure."
            )

        # Find the first naggable task
        next_task = _get_next_naggable_task(project_id.strip())
        if not next_task:
            return f"No actionable tasks in project '{project['name']}'. Add tasks first."

        # Create the nag
        from app_platform.reminders import create_nag
        nag_message = f"[{project['name']}] Next up: {next_task['name']} ({next_task['id']})"
        nag = create_nag(
            user_id=user_id.strip().lower(),
            message=nag_message,
        )

        # Store nag config on project
        project["auto_nag"] = {
            "enabled": True,
            "user_id": user_id.strip().lower(),
            "nag_id": nag["id"],
            "current_task_id": next_task["id"],
        }
        _add_history(project, user_id.strip().lower(),
                     f"Auto-nag enabled (nag: {nag['id']}, first task: {next_task['id']})")
        _save_entity(project)

        return (
            f"Auto-nag enabled on '{project['name']}'.\n"
            f"  Nag ID: {nag['id']}\n"
            f"  Nagging: {user_id.strip()}\n"
            f"  Current task: {next_task['name']} ({next_task['id']})\n"
            f"  Will advance to next task automatically on completion."
        )

    except Exception as e:
        return f"Error in enable_project_nag: {str(e)}"


def disable_project_nag(
    project_id: str,
    updated_by: str,
) -> str:
    """Disable auto-nagging on a project.

    Cancels the nag reminder and removes the auto-nag config from the project.
    The tasks and their ordering are not affected.

    Args:
        project_id: The project to stop nagging about (e.g. "p-abc123").
        updated_by: Who is disabling (person name).

    Returns:
        Confirmation.

    Ack: Disabling auto-nag...
    """
    try:
        if not project_id or not project_id.strip():
            return "Error: project_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        project = _load_entity(project_id.strip())
        if not project or not project_id.strip().startswith("p-"):
            return f"Error: Project '{project_id}' not found."

        nag_config = project.get("auto_nag")
        if not nag_config or not nag_config.get("enabled"):
            return f"Auto-nag is not enabled on '{project['name']}'."

        # Cancel the nag reminder
        nag_id = nag_config.get("nag_id")
        if nag_id:
            from app_platform.reminders import cancel_reminder
            cancel_reminder(nag_id)

        project["auto_nag"] = None
        _add_history(project, updated_by.strip().lower(), "Auto-nag disabled")
        _save_entity(project)

        return f"Auto-nag disabled on '{project['name']}'. Nag '{nag_id}' cancelled."

    except Exception as e:
        return f"Error in disable_project_nag: {str(e)}"


def set_task_parent(
    task_id: str,
    parent_task_id: str,
    updated_by: str,
    confirm_migrate: str = "",
) -> str:
    """Move a task to be a subtask of another task (reparent).

    Removes the task from its current parent (project or task) and adds it
    as a child of the new parent task. project_id is updated to match the
    new parent's project_id.

    To make a subtask a top-level task again, use parent_task_id="" (empty).

    IMPORTANT: If the new parent is in a DIFFERENT project, you MUST first
    confirm with the user and then pass confirm_migrate="yes". Without it
    the tool will reject the move.

    Args:
        task_id: The task to move (e.g. "t-abc123").
        parent_task_id: New parent task ID (e.g. "t-xyz789"), or empty string
                        to make it a top-level project task.
        updated_by: Who is making this change (person name).
        confirm_migrate: Set to "yes" ONLY after the user has explicitly
                         confirmed a cross-project move. Leave empty for
                         same-project reparenting.

    Returns:
        Confirmation of reparenting.

    Ack: Moving task...
    """
    try:
        if not task_id or not task_id.strip():
            return "Error: task_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        task = _load_entity(task_id.strip())
        if not task or not task_id.strip().startswith("t-"):
            return f"Error: Task '{task_id}' not found."

        new_parent_id = parent_task_id.strip() if parent_task_id and parent_task_id.strip() else None

        if new_parent_id and new_parent_id == task_id.strip():
            return "Error: A task cannot be its own parent."

        # --- Cross-project move guard ---
        if new_parent_id:
            new_parent_check = _load_entity(new_parent_id)
            if new_parent_check:
                old_proj = task.get("project_id", "")
                new_proj = new_parent_check.get("project_id", "")
                if old_proj and new_proj and old_proj != new_proj:
                    if confirm_migrate.strip().lower() != "yes":
                        old_p = _load_entity(old_proj)
                        new_p = _load_entity(new_proj)
                        old_name = old_p["name"] if old_p else old_proj
                        new_name = new_p["name"] if new_p else new_proj
                        return (
                            f"BLOCKED: This would migrate task '{task['name']}' "
                            f"from project '{old_name}' to project '{new_name}'. "
                            f"Cross-project moves require user confirmation. "
                            f"Ask the user to confirm, then re-call with confirm_migrate=\"yes\"."
                        )

        # --- Remove from old parent ---
        old_parent_task_id = task.get("parent_task_id")
        old_project_id = task.get("project_id")

        if old_parent_task_id:
            old_parent = _load_entity(old_parent_task_id)
            if old_parent:
                subs = old_parent.get("subtasks", [])
                if task_id.strip() in subs:
                    subs.remove(task_id.strip())
                    _save_entity(old_parent)
        else:
            # Was top-level — remove from project's tasks list
            if old_project_id:
                project = _load_entity(old_project_id)
                if project:
                    tlist = project.get("tasks", [])
                    if task_id.strip() in tlist:
                        tlist.remove(task_id.strip())
                        _save_entity(project)

        # --- Attach to new parent ---
        if new_parent_id:
            new_parent = _load_entity(new_parent_id)
            if not new_parent or not new_parent_id.startswith("t-"):
                return f"Error: Parent task '{new_parent_id}' not found."

            new_parent.setdefault("subtasks", []).append(task_id.strip())
            _save_entity(new_parent)

            task["parent_task_id"] = new_parent_id
            task["project_id"] = new_parent.get("project_id", old_project_id)
            _add_history(task, updated_by.strip().lower(),
                         f"Reparented under task {new_parent_id}")
            _save_entity(task)

            # Re-rank & re-evaluate nags on affected projects
            _rerank_project(task["project_id"])
            _refresh_project_nag(task["project_id"], reason=f"reparent {task_id}")
            if old_project_id and old_project_id != task["project_id"]:
                _rerank_project(old_project_id)
                _refresh_project_nag(old_project_id, reason=f"reparent {task_id}")

            new_rank = task.get("stack_rank", "?")
            return (
                f"Task '{task['name']}' ({task_id}) moved under "
                f"'{new_parent['name']}' ({new_parent_id}). "
                f"Now ranked T{new_rank}. (All T-ranks updated.)"
            )
        else:
            # Make top-level again
            project = _load_entity(old_project_id)
            if not project:
                return f"Error: Project '{old_project_id}' not found."

            project.setdefault("tasks", []).append(task_id.strip())
            _save_entity(project)

            task["parent_task_id"] = None
            _add_history(task, updated_by.strip().lower(),
                         f"Made top-level task under project {old_project_id}")
            _save_entity(task)

            _rerank_project(old_project_id)
            _refresh_project_nag(old_project_id, reason=f"reparent {task_id}")

            new_rank = task.get("stack_rank", "?")
            return (
                f"Task '{task['name']}' ({task_id}) is now a top-level task "
                f"under project '{project['name']}' ({old_project_id}). "
                f"Now ranked T{new_rank}. (All T-ranks updated.)"
            )

    except Exception as e:
        return f"Error in set_task_parent: {str(e)}"


def link_project_to_trello(
    project_id: str,
    board_name: str,
    backlog_list: str = "Backlog",
    done_list: str = "Done",
    user_lists_json: str = "",
    linked_by: str = "",
) -> str:
    """Link a Skipper project to a Trello board for live Task ↔ Card integration.

    Once linked, Trello-linked tasks can be created under this project.
    Trello is the live source of truth — Skipper stores only a task skeleton
    and fetches card data (description, checklists, status, labels) via
    live API calls.

    Args:
        project_id: The Skipper project ID (p-xxx).
        board_name: The Trello board name (e.g. "project-alpha").
        backlog_list: Trello list for new/unassigned cards. Default "Backlog".
        done_list: Trello list for completed cards. Default "Done".
        user_lists_json: Optional. DO NOT guess or fabricate this value.
                         If omitted, user lists are auto-detected by matching
                         board list names to known family members (e.g. a list
                         named "Bob TODO" is automatically mapped to user bob).
                         Only provide this if the user explicitly specifies
                         custom mappings. Format: JSON object mapping usernames
                         to exact Trello list names.
        linked_by: Who is performing the link.

    Returns:
        Confirmation with board details, or error.

    Ack: Linking project to Trello board...
    """
    try:
        from trello_task_sync import link_project_to_trello as _link
        return _link(project_id, board_name, backlog_list, done_list,
                     user_lists_json, linked_by)
    except Exception as e:
        return f"Error in link_project_to_trello: {str(e)}"


def unlink_project_from_trello(
    project_id: str,
    unlinked_by: str = "",
) -> str:
    """Remove a Trello board link from a Skipper project.

    Existing task skeletons are preserved but no longer live-linked to
    Trello cards.

    Args:
        project_id: The Skipper project ID (p-xxx).
        unlinked_by: Who is performing the unlink.

    Returns:
        Confirmation or error.

    Ack: Unlinking project from Trello...
    """
    try:
        from trello_task_sync import unlink_project_from_trello as _unlink
        return _unlink(project_id, unlinked_by)
    except Exception as e:
        return f"Error in unlink_project_from_trello: {str(e)}"


def create_trello_task(
    project_id: str,
    name: str,
    created_by: str,
    description: str = "",
    checklist_items: str = "",
    assigned_to: str = "",
) -> str:
    """Create a Trello-linked task under a project.

    Creates a Trello card AND a thin task skeleton in Skipper linked to
    that card. If assigned_to is provided, the card is placed on the
    assignee's TODO list; otherwise it goes to the Backlog list.
    The card is the live source of truth for description, checklists,
    status, labels, and due date.

    Args:
        project_id: The Skipper project ID (p-xxx). Must be Trello-linked.
        name: Task/card title.
        created_by: Who is creating it.
        description: Optional initial card description.
        checklist_items: Optional JSON array of checklist item strings,
                         e.g. '["Design UI", "Build API", "Write tests"]'.
        assigned_to: Optional person to assign the task to. When set,
                     the Trello card is placed on their TODO list.

    Returns:
        Confirmation with task ID and card link, or error.

    Ack: Creating Trello-linked task...
    """
    try:
        import json
        from trello_task_sync import create_trello_task as _create

        items = None
        if checklist_items and checklist_items.strip():
            try:
                items = json.loads(checklist_items.strip())
            except json.JSONDecodeError as e:
                return f"Error: Invalid checklist_items JSON: {e}"

        result = _create(project_id, name, created_by, description, items,
                        assigned_to=assigned_to)

        if isinstance(result, str):
            return result

        task = result
        rank = task.get("stack_rank", "?")
        assignee_str = ', '.join(task.get('assigned_to', []))
        return (
            f"Created Trello-linked task T{rank} '{task['name']}' ({task['id']}).\n"
            f"  Card ID: {task['trello_card_id']}\n"
            f"  Assigned to: {assignee_str}\n"
            f"  Status: not_started"
        )
    except Exception as e:
        return f"Error in create_trello_task: {str(e)}"


def adopt_trello_card(
    project_id: str,
    board_name: str,
    created_by: str,
    card_title: str = "",
    card_id: str = "",
) -> str:
    """Adopt an existing Trello card into a Skipper project as a linked task.

    The card is NOT moved — it stays on whatever list it's currently on.
    Skipper creates a task skeleton linked to it and starts tracking it.

    Use this when a card already exists on the Trello board and you want
    Skipper to start managing it as a task.

    Args:
        project_id: The Skipper project ID (p-xxx). Must be Trello-linked.
        board_name: The Trello board name.
        created_by: Who is adopting it.
        card_title: Title of the existing card (fuzzy matched). Provide
                    this OR card_id.
        card_id: Direct Trello card ID (alternative to title).

    Returns:
        Confirmation with task ID and current card status, or error.

    Ack: Adopting Trello card as task...
    """
    try:
        from trello_task_sync import adopt_trello_card as _adopt

        result = _adopt(project_id, board_name, created_by, card_title, card_id)

        if isinstance(result, str):
            return result

        task = result
        rank = task.get("stack_rank", "?")
        return (
            f"Adopted card '{task['name']}' as task T{rank} ({task['id']}).\n"
            f"  Card ID: {task['trello_card_id']}\n"
            f"  Assigned to: {', '.join(task.get('assigned_to', []))}"
        )
    except Exception as e:
        return f"Error in adopt_trello_card: {str(e)}"


def check_trello_item(
    item_id: str,
    item_number: int,
    checked: str = "true",
) -> str:
    """Check or uncheck a checklist item on a Trello-linked task.

    Accepts T-rank references (T1, T2) — auto-resolves to task ID.
    Item numbers match the ☐/☑ display from get_entity_detail.

    Args:
        item_id: Task ID (t-xxx) or T-rank reference (T1, T5).
        item_number: 1-based checklist item number (matches display order).
        checked: 'true' to check (default), 'false' to uncheck.

    Returns:
        Confirmation with the item name and new state.

    Ack: Updating checklist...
    """
    try:
        resolved_id = _resolve_rank(item_id)
        is_checked = checked.strip().lower() in ("true", "yes", "1")

        from trello_task_sync import check_trello_item as _check
        return _check(resolved_id, int(item_number), checked=is_checked)
    except Exception as e:
        return f"Error in check_trello_item: {str(e)}"


# ---------------------------------------------------------------------------
# Project & Goal ordering tools
# ---------------------------------------------------------------------------

def set_project_order(
    goal_id: str,
    project_ids: str,
    updated_by: str,
) -> str:
    """Set the stack-rank order of projects in a goal.

    Provide project IDs in priority order (first = P1, highest priority).
    Projects not listed keep their current rank but are pushed after listed ones.

    Args:
        goal_id: The goal ID (e.g. "g-abc123").
        project_ids: Comma-separated project IDs in desired order, highest priority first.
                     Example: "p-aaa,p-bbb,p-ccc"
        updated_by: Who is reordering (person name).

    Returns:
        Confirmation with new ordering.

    Ack: Reordering projects...
    """
    try:
        if not goal_id or not goal_id.strip():
            return "Error: goal_id is required."
        if not project_ids or not project_ids.strip():
            return "Error: project_ids is required (comma-separated)."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        goal = _load_entity(goal_id.strip())
        if not goal or not goal_id.strip().startswith("g-"):
            return f"Error: Goal '{goal_id}' not found."

        ordered = [pid.strip() for pid in project_ids.split(",") if pid.strip()]
        all_projects = _get_projects_for_goal(goal_id.strip())
        proj_map = {p["id"]: p for p in all_projects}

        # Validate all provided IDs
        for pid in ordered:
            if pid not in proj_map:
                return f"Error: Project '{pid}' not found in goal '{goal_id}'."

        # Assign ranks: listed projects get 1, 2, 3...; unlisted pushed after
        rank = 1
        updated = []
        for pid in ordered:
            proj = proj_map[pid]
            proj["stack_rank"] = rank
            _add_history(proj, updated_by.strip().lower(), f"Stack rank set to P{rank}")
            _save_entity(proj)
            updated.append(f"  P{rank} {proj['name']} ({pid})")
            rank += 1

        # Unlisted projects get ranks after the listed ones
        for proj in sorted(all_projects, key=lambda p: p.get("stack_rank", 0)):
            if proj["id"] not in ordered:
                proj["stack_rank"] = rank
                _save_entity(proj)
                updated.append(f"  P{rank} {proj['name']} ({proj['id']}) [unchanged]")
                rank += 1

        return f"Project order set for {goal_id}:\n" + "\n".join(updated)

    except Exception as e:
        return f"Error in set_project_order: {str(e)}"


def set_project_dependency(
    project_id: str,
    depends_on: str,
    updated_by: str,
) -> str:
    """Set dependencies on a project — which other projects must complete first.

    Dependencies affect the project's P-rank ordering within its goal.

    Args:
        project_id: The project to set dependencies on (e.g. "p-abc123").
        depends_on: Comma-separated project IDs this project depends on.
                    Example: "p-xxx,p-yyy". Use empty string to clear dependencies.
        updated_by: Who is making this change (person name).

    Returns:
        Confirmation with dependency list.

    Ack: Setting project dependencies...
    """
    try:
        if not project_id or not project_id.strip():
            return "Error: project_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        project = _load_entity(project_id.strip())
        if not project or not project_id.strip().startswith("p-"):
            return f"Error: Project '{project_id}' not found."

        dep_ids = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []

        # Validate dependency IDs
        for dep_id in dep_ids:
            dep = _load_entity(dep_id)
            if not dep or not dep_id.startswith("p-"):
                return f"Error: Dependency '{dep_id}' is not a valid project."
            if dep_id == project_id.strip():
                return "Error: A project cannot depend on itself."

        project["depends_on"] = dep_ids
        _add_history(project, updated_by.strip().lower(),
                     f"Dependencies set: {dep_ids}" if dep_ids else "Dependencies cleared")
        _save_entity(project)

        # Re-rank projects within the goal
        goal_id = project.get("goal_id")
        if goal_id:
            _rerank_goal(goal_id)

        if dep_ids:
            dep_names = []
            for did in dep_ids:
                d = _load_entity(did)
                dep_names.append(f"  {did}: {d['name']} ({d.get('status', '?')})")
            return (
                f"Project '{project['name']}' ({project_id}) now depends on:\n"
                + "\n".join(dep_names)
            )
        else:
            return f"Dependencies cleared for project '{project['name']}' ({project_id})."

    except Exception as e:
        return f"Error in set_project_dependency: {str(e)}"


def set_goal_order(
    goal_ids: str,
    updated_by: str,
) -> str:
    """Set the stack-rank order of goals globally.

    Provide goal IDs in priority order (first = G1, highest priority).
    Goals not listed keep their current rank but are pushed after listed ones.

    Args:
        goal_ids: Comma-separated goal IDs in desired order, highest priority first.
                  Example: "g-aaa,g-bbb,g-ccc"
        updated_by: Who is reordering (person name).

    Returns:
        Confirmation with new ordering.

    Ack: Reordering goals...
    """
    try:
        if not goal_ids or not goal_ids.strip():
            return "Error: goal_ids is required (comma-separated)."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        from apps.goals.store import _list_entities

        ordered = [gid.strip() for gid in goal_ids.split(",") if gid.strip()]
        all_goals = _list_entities("g-")
        goal_map = {g["id"]: g for g in all_goals}

        # Validate all provided IDs
        for gid in ordered:
            if gid not in goal_map:
                return f"Error: Goal '{gid}' not found."

        # Assign ranks: listed goals get 1, 2, 3...; unlisted pushed after
        rank = 1
        updated = []
        for gid in ordered:
            goal = goal_map[gid]
            goal["stack_rank"] = rank
            _add_history(goal, updated_by.strip().lower(), f"Stack rank set to G{rank}")
            _save_entity(goal)
            updated.append(f"  G{rank} {goal['name']} ({gid})")
            rank += 1

        # Unlisted goals get ranks after the listed ones
        for goal in sorted(all_goals, key=lambda g: g.get("stack_rank", 0)):
            if goal["id"] not in ordered:
                goal["stack_rank"] = rank
                _save_entity(goal)
                updated.append(f"  G{rank} {goal['name']} ({goal['id']}) [unchanged]")
                rank += 1

        return f"Goal order set:\n" + "\n".join(updated)

    except Exception as e:
        return f"Error in set_goal_order: {str(e)}"


def set_goal_dependency(
    goal_id: str,
    depends_on: str,
    updated_by: str,
) -> str:
    """Set dependencies on a goal — which other goals must complete first.

    Dependencies affect the goal's G-rank ordering.

    Args:
        goal_id: The goal to set dependencies on (e.g. "g-abc123").
        depends_on: Comma-separated goal IDs this goal depends on.
                    Example: "g-xxx,g-yyy". Use empty string to clear dependencies.
        updated_by: Who is making this change (person name).

    Returns:
        Confirmation with dependency list.

    Ack: Setting goal dependencies...
    """
    try:
        if not goal_id or not goal_id.strip():
            return "Error: goal_id is required."
        if not updated_by or not updated_by.strip():
            return "Error: updated_by is required."

        goal = _load_entity(goal_id.strip())
        if not goal or not goal_id.strip().startswith("g-"):
            return f"Error: Goal '{goal_id}' not found."

        dep_ids = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []

        # Validate dependency IDs
        for dep_id in dep_ids:
            dep = _load_entity(dep_id)
            if not dep or not dep_id.startswith("g-"):
                return f"Error: Dependency '{dep_id}' is not a valid goal."
            if dep_id == goal_id.strip():
                return "Error: A goal cannot depend on itself."

        goal["depends_on"] = dep_ids
        _add_history(goal, updated_by.strip().lower(),
                     f"Dependencies set: {dep_ids}" if dep_ids else "Dependencies cleared")
        _save_entity(goal)

        _rerank_goals()

        if dep_ids:
            dep_names = []
            for did in dep_ids:
                d = _load_entity(did)
                dep_names.append(f"  {did}: {d['name']} ({d.get('status', '?')})")
            return (
                f"Goal '{goal['name']}' ({goal_id}) now depends on:\n"
                + "\n".join(dep_names)
            )
        else:
            return f"Dependencies cleared for goal '{goal['name']}' ({goal_id})."

    except Exception as e:
        return f"Error in set_goal_dependency: {str(e)}"
