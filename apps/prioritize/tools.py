"""Prioritize — MCP tools.

Five tools used by the chat agent to manage user focus slots and
view the cross-app backlog:

- ``list_focus(user_id)``
- ``promote_focus(user_id, source_type, source_id)``
- ``clear_focus(user_id, source_id)``
- ``get_backlog_summary(user_id)``
- ``get_family_focus()``
"""

from __future__ import annotations

import apps.prioritize.data as _dl


def list_focus(user_id: str) -> str:
    """Show the current focus slots for a user.

    Ack: Checking focus priorities...

    Args:
        user_id: Canonical user name (e.g. "alice").

    Returns:
        Formatted list of the user's focus slots (up to 3).
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        uid = user_id.strip().lower()
        _dl.cleanup_stale_focus(uid)
        slots = _dl.get_focus_slots(uid)
        if not slots:
            return f"{uid} has no focus items set. They should pick up to 3 priorities!"
        lines = [f"**{uid}'s Focus Priorities** ({len(slots)}/3):\n"]
        for s in slots:
            title = _resolve_title(s["source_type"], s["source_id"])
            lines.append(f"  {s['slot_number']}. [{s['source_type']}] {title}  (id: {s['source_id']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_focus: {e}"


def promote_focus(user_id: str, source_type: str, source_id: str) -> str:
    """Promote an item to the user's focus (next available slot 1-3).

    Ack: Adding to focus...

    Args:
        user_id: Canonical user name.
        source_type: One of 'goal', 'project', 'task', 'reminder', 'nag', 'auto_issue'.
        source_id: The ID of the item from its source app (e.g. "g-abc123").

    Returns:
        Confirmation or error.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        if not source_type or not source_type.strip():
            return "Error: source_type is required (goal, project, task, reminder, nag, auto_issue)."
        if not source_id or not source_id.strip():
            return "Error: source_id is required."
        uid = user_id.strip().lower()
        st = source_type.strip().lower()
        sid = source_id.strip()
        result = _dl.promote_to_focus(uid, st, sid)
        if result is None:
            return f"All 3 focus slots are full for {uid}. Clear one first with clear_focus."
        title = _resolve_title(st, sid)
        return f"Promoted **{title}** to focus slot #{result['slot_number']} for {uid}."
    except Exception as e:
        return f"Error in promote_focus: {e}"


def clear_focus(user_id: str, source_id: str) -> str:
    """Remove an item from the user's focus by its source ID.

    Ack: Removing from focus...

    Args:
        user_id: Canonical user name.
        source_id: The source item ID to remove from focus (e.g. "g-abc123").

    Returns:
        Confirmation or error.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        if not source_id or not source_id.strip():
            return "Error: source_id is required."
        uid = user_id.strip().lower()
        sid = source_id.strip()
        ok = _dl.clear_focus_by_source(uid, sid)
        if ok:
            return f"Removed {sid} from {uid}'s focus."
        return f"{sid} was not in {uid}'s focus."
    except Exception as e:
        return f"Error in clear_focus: {e}"


def get_backlog_summary(user_id: str) -> str:
    """Get a summary of all actionable backlog items for a user.

    Ack: Loading backlog...

    Args:
        user_id: Canonical user name.

    Returns:
        Formatted backlog summary grouped by source type.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        uid = user_id.strip().lower()
        backlog = _dl.get_backlog(uid)

        lines = [f"**{uid}'s Backlog:**\n"]

        # Goals tree
        tree = backlog.get("goals_tree", [])
        if tree:
            goal_count = 0
            proj_count = 0
            task_count = 0
            for g in tree:
                goal_count += 1
                for p in g.get("projects", []):
                    proj_count += 1
                    task_count += len(p.get("tasks", []))
            lines.append(f"**Goals:** {goal_count} goals, {proj_count} projects, {task_count} tasks")
            for g in tree:
                lines.append(f"  🎯 {g['title']}  (id: {g['source_id']})")
                for p in g.get("projects", []):
                    lines.append(f"    📁 {p['title']}  (id: {p['source_id']})")
                    for t in p.get("tasks", []):
                        pri = f" [{t.get('priority', '')}]" if t.get("priority") else ""
                        lines.append(f"      ✅ {t['title']}{pri}  (id: {t['source_id']})")

        # Reminders
        reminders = backlog.get("reminders", [])
        if reminders:
            lines.append(f"\n**Reminders:** {len(reminders)}")
            for r in reminders[:10]:
                lines.append(f"  🔔 {r['title']}  (id: {r['source_id']})")
            if len(reminders) > 10:
                lines.append(f"  ... and {len(reminders) - 10} more")

        # Nags
        nags = backlog.get("nags", [])
        if nags:
            lines.append(f"\n**Nags:** {len(nags)}")
            for n in nags[:10]:
                lines.append(f"  ⚡ {n['title']}  (id: {n['source_id']})")
            if len(nags) > 10:
                lines.append(f"  ... and {len(nags) - 10} more")

        # Auto issues (or any other registered backlog provider)
        issues = backlog.get("auto_issues", [])
        if issues:
            lines.append(f"\n**Auto Issues:** {len(issues)}")
            for i in issues[:10]:
                sev = f" [{i.get('severity', '')}]" if i.get("severity") else ""
                lines.append(f"  🚗 {i['title']}{sev}  (id: {i['source_id']})")
            if len(issues) > 10:
                lines.append(f"  ... and {len(issues) - 10} more")

        if len(lines) == 1:
            return f"{uid} has no actionable backlog items. Nice work! 🎉"

        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_backlog_summary: {e}"


def get_family_focus() -> str:
    """Show the focus priorities for all family members.

    Ack: Loading family priorities...

    Returns:
        Formatted list of each family member's focus slots.
    """
    try:
        import data_layer.users as _dl_users
        users = _dl_users.get_all_users()
        lines = ["**Family Focus Priorities:**\n"]
        for u in users:
            uid = u["name"]
            display = u.get("display_name") or uid
            _dl.cleanup_stale_focus(uid)
            slots = _dl.get_focus_slots(uid)
            if not slots:
                lines.append(f"**{display}**: No focus items set")
            else:
                slot_strs = []
                for s in slots:
                    title = _resolve_title(s["source_type"], s["source_id"])
                    slot_strs.append(f"{s['slot_number']}. {title}")
                lines.append(f"**{display}**:")
                for ss in slot_strs:
                    lines.append(f"  {ss}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_family_focus: {e}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_title(source_type: str, source_id: str) -> str:
    """Best-effort title lookup for a source item.

    Goals/projects/tasks still in public.*. Reminders go through the
    reminders shim; vehicle issues through their qualified app schema
    (the auto app isn't packaged yet).
    """
    try:
        if source_type in ("goal", "project", "task"):
            from data_layer.db import fetch_one
            table = {"goal": "goals", "project": "projects", "task": "tasks"}[source_type]
            row = fetch_one(f"SELECT name FROM public.{table} WHERE id = %s", (source_id,))
            return row["name"] if row else source_id
        if source_type in ("reminder", "nag"):
            from app_platform.reminders import get_reminder
            r = get_reminder(source_id)
            return r["message"] if r and r.get("message") else source_id
        if source_type == "auto_issue":
            from data_layer.db import fetch_one
            row = fetch_one("SELECT description FROM app_auto.vehicle_issues WHERE id = %s", (source_id,))
            return row["description"] if row else source_id
    except Exception:
        pass
    return source_id
