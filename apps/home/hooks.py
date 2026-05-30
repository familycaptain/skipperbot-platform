"""Home App — Platform Hooks
==============================
Registers backlog providers, activity checkers, and nag providers with
the platform so the platform has no hard dependency on this app.

Called by the app loader during startup.
"""

import asyncio
import logging
from datetime import date

logger = logging.getLogger(__name__)


def register_hooks():
    """Register all platform hooks for the Home app."""
    from apps.prioritize.data import register_backlog_provider, register_activity_checker
    from nag_registry import register_nag_provider

    register_backlog_provider("home_tasks", _home_maintenance_backlog)
    register_activity_checker("home_task", _home_task_is_active)
    register_nag_provider("home_maintenance_nag", _home_maintenance_nag_provider)


# ---------------------------------------------------------------------------
# Backlog provider
# ---------------------------------------------------------------------------

def _home_maintenance_backlog(user_id: str) -> list[dict]:
    """Return overdue and due-soon home maintenance tasks for the Prioritize backlog."""
    try:
        from apps.home import data as _dl
        tasks = _dl.get_due_tasks(days_ahead=7)
        today = date.today()
        result = []
        for t in tasks:
            due_str = t.get("next_due_at") or ""
            overdue = False
            detail = ""
            if due_str:
                due_date = date.fromisoformat(due_str)
                if due_date < today:
                    overdue = True
                    delta = (today - due_date).days
                    detail = f"{delta}d overdue" if delta > 0 else "overdue"
                else:
                    delta = (due_date - today).days
                    detail = "today" if delta == 0 else f"due in {delta}d"
            result.append({
                "source_type": "home_task",
                "source_id": t["id"],
                "title": t["name"],
                "category": t.get("category") or "General",
                "detail": detail,
                "overdue": overdue,
                "next_due": due_str,
                "task_type": t.get("task_type") or "recurring",
            })
        return result
    except Exception as e:
        logger.error("HOME: maintenance backlog provider failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Activity checker
# ---------------------------------------------------------------------------

def _home_task_is_active(task_id: str) -> bool:
    """Activity checker: home_task source_type."""
    try:
        from apps.home import data as _dl
        task = _dl.get_task(task_id)
        return bool(task and task.get("active"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Nag provider
# ---------------------------------------------------------------------------

def _get_admin_users() -> list[str]:
    """Return usernames of all admin users."""
    from data_layer.users import get_users_with_any_role
    return [user["name"] for user in get_users_with_any_role("admin")]


def _build_nag_message(overdue: list[dict]) -> str:
    """Format a consolidated nag message listing all overdue tasks."""
    today = date.today()
    lines = [f"🏠 Home Maintenance — {len(overdue)} overdue task(s):\n"]
    for t in overdue:
        due_str = t.get("next_due_at") or ""
        days_str = ""
        if due_str:
            delta = (today - date.fromisoformat(due_str)).days
            days_str = f" — {delta}d overdue"
        category = t.get("category") or "General"
        lines.append(f"  • {t['name']} [{category}]{days_str}")
    return "\n".join(lines)


async def _home_maintenance_nag_provider() -> list[dict]:
    """Check for overdue home maintenance tasks and nag admin users.

    Returns one nag item per admin user if any tasks are overdue.
    """
    try:
        from apps.home import data as _dl
        tasks = await asyncio.to_thread(_dl.get_due_tasks, 0)
    except Exception as e:
        logger.error("HOME NAG: failed to fetch due tasks: %s", e)
        return []

    today = date.today()
    overdue = [t for t in tasks if t.get("next_due_at") and date.fromisoformat(t["next_due_at"]) < today]
    if not overdue:
        return []

    try:
        admin_users = await asyncio.to_thread(_get_admin_users)
    except Exception as e:
        logger.error("HOME NAG: failed to fetch admin users: %s", e)
        return []

    if not admin_users:
        return []

    message = _build_nag_message(overdue)
    return [
        {
            "recipient": user,
            "message": message,
            "source_type": "home_maintenance_nag",
            "source_id": user,
        }
        for user in admin_users
    ]
