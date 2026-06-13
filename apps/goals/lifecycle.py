"""
Goal Domain Lifecycle
=====================
Auto-create / enable / disable thinking domains when goals are
assigned to or unassigned from Skipper.

Skipper can own things at any level:
  - Goal owner → domain created
  - Project owner under a goal → domain created for that goal
  - Task assignee under a goal → domain created for that goal

Call ``sync_goal_domain(goal_id)`` after any goal mutation, or
``sync_entity_domain(entity_id)`` for any entity — it resolves to the
parent goal automatically.  Both are idempotent.
"""

import logging

from config import NAG_WAKE_HOUR, NAG_SLEEP_HOUR
from data_layer.thinking_domains import get_domain, create_domain, update_domain
from apps.goals.data import load_entity, get_top_level_tasks, get_subtasks

logger = logging.getLogger(__name__)

# Statuses that mean the goal is "finished" (no thinking needed)
_INACTIVE_STATUSES = {"done", "deferred", "archived", "cancelled"}

# Default cadence for goal thinking domains. Active hours track the household's
# notification waking window so goal work doesn't run/reach out overnight.
_DEFAULT_CADENCE = {
    "active_hours": [NAG_WAKE_HOUR, NAG_SLEEP_HOUR],
    "interval_minutes": 30,
}


def sync_entity_domain(entity_id: str) -> str | None:
    """Resolve *entity_id* to its parent goal and sync the domain.

    Works for goals (g-*), projects (p-*), and tasks (t-*).
    """
    goal_id = _resolve_goal_id(entity_id)
    if not goal_id:
        return None
    return sync_goal_domain(goal_id)


def sync_goal_domain(goal_id: str) -> str | None:
    """Ensure the thinking domain for *goal_id* matches reality.

    Creates/enables the domain for any active goal.  The handler itself
    decides whether to spend tokens (it checks Skipper ownership).
    Disables the domain when the goal becomes inactive.

    Returns a short status string for logging, or None if no change.
    """
    if not goal_id or not goal_id.startswith("g-"):
        return None

    goal = load_entity(goal_id)
    if not goal:
        return None

    status = (goal.get("status") or "").lower()
    goal_active = status not in _INACTIVE_STATUSES

    domain = get_domain(goal_id)

    if goal_active:
        if domain:
            if not domain.get("enabled"):
                update_domain(goal_id, enabled=True)
                logger.info("GOAL_LIFECYCLE: Re-enabled domain for %s", goal_id)
                return "re-enabled"
            return None  # already exists and enabled
        else:
            goal_name = goal.get("name", goal_id)
            create_domain(
                name=goal_id,
                description=f"Goal: {goal_name}",
                observe_tool="observe_goal",
                evaluate_tool="evaluate_goal",
                act_tool="act_goal",
                knowledge_refs={"goal_id": goal_id},
                cadence=_DEFAULT_CADENCE,
                budget_priority="standard",
                created_by="system",
            )
            logger.info("GOAL_LIFECYCLE: Created domain for %s (%s)", goal_id, goal_name)
            return "created"
    else:
        # Goal inactive — disable if exists
        if domain and domain.get("enabled"):
            update_domain(goal_id, enabled=False)
            logger.info("GOAL_LIFECYCLE: Disabled domain for %s (goal inactive)", goal_id)
            return "disabled"
        return None


def _skipper_owns_anything_in_goal(goal: dict) -> bool:
    """Check if Skipper owns the goal, any project, or any task under it."""
    # Goal-level
    if "skipper" in [o.lower() for o in (goal.get("owners") or [])]:
        return True

    # Walk projects and tasks
    for pid in goal.get("projects", []):
        proj = load_entity(pid)
        if not proj:
            continue
        if "skipper" in [o.lower() for o in (proj.get("owners") or [])]:
            return True
        for task in get_top_level_tasks(pid):
            if "skipper" in [a.lower() for a in (task.get("assigned_to") or [])]:
                return True
            for sub in get_subtasks(task["id"]):
                if "skipper" in [a.lower() for a in (sub.get("assigned_to") or [])]:
                    return True

    return False


def _resolve_goal_id(entity_id: str) -> str | None:
    """Walk up the entity tree to find the root goal ID."""
    if not entity_id:
        return None
    if entity_id.startswith("g-"):
        return entity_id

    entity = load_entity(entity_id)
    if not entity:
        return None

    if entity_id.startswith("p-"):
        return entity.get("goal_id") or None

    if entity_id.startswith("t-"):
        # Task → project → goal
        project_id = entity.get("project_id")
        if not project_id:
            return None
        proj = load_entity(project_id)
        return proj.get("goal_id") if proj else None

    return None
