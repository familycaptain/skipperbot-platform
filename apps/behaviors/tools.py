"""Behaviors — MCP tools.

Five tools used by the chat agent to manage user-customizable if/then
behavior rules:

- ``add_behavior(user_id, trigger_description, action_description, ...)``
- ``list_behaviors(user_id, scope="")``
- ``update_behavior(behavior_id, ...)``
- ``remove_behavior(behavior_id)``
- ``toggle_behavior(behavior_id)``

Behaviors are unconditionally injected into every chat system prompt
(see ``chat_domain.py``) — call ``add_behavior`` immediately when a
user teaches you a new rule. See ``apps/behaviors/guide.md`` for the
full teaching-moment workflow.
"""

from __future__ import annotations

from app_platform.memory import digest_record
from apps.behaviors.data import (
    create_behavior as _create,
    get_behavior as _get,
    list_behaviors as _list,
    update_behavior as _update,
    delete_behavior as _delete,
    toggle_behavior as _toggle,
)


def add_behavior(
    user_id: str,
    trigger_description: str,
    action_description: str,
    scope: str = "user",
    notes: str = "",
) -> str:
    """Create a new behavior rule that is always injected into the chat system prompt.

    Behaviors are if/then rules — when the trigger condition is detected,
    Skipper will automatically perform the action. Unlike memories (semantic
    injection only when relevant), behaviors are unconditionally present on
    every chat turn, making them reliable for automation-style rules.

    Call this immediately when a user teaches you a new behavioral rule.
    Do NOT ask for confirmation — just create it and confirm in your response.

    Args:
        user_id: The user this behavior belongs to (e.g. "alice").
        trigger_description: When to apply this behavior. Natural language
            description of the condition (e.g. "When the user says they did
            something or completed an activity").
        action_description: What to do when triggered. Natural language
            description of the action (e.g. "Search the to-do list, goals
            tasks, and home app for matching items and mark them as complete").
        scope: 'user' (personal, default) or 'system' (applies to all users).
        notes: Optional context about why this behavior was created.

    Returns:
        Confirmation with the new behavior ID and a summary.
    """
    behavior = _create(
        trigger_description=trigger_description,
        action_description=action_description,
        created_by=user_id,
        scope=scope,
        notes=notes,
    )
    try:
        digest_record("behaviors", "behavior", "created", behavior["id"], behavior, by=user_id)
    except Exception:
        pass
    return (
        f"Behavior created: {behavior['id']}\n"
        f"Trigger: {behavior['trigger_description']}\n"
        f"Action:  {behavior['action_description']}\n"
        f"Scope: {behavior['scope']} | Enabled: {behavior['enabled']}"
    )


def list_behaviors(user_id: str, scope: str = "") -> str:
    """List all behavior rules for a user.

    Returns the user's own behaviors plus all system-wide behaviors by default.

    Args:
        user_id: The user whose behaviors to list (e.g. "alice").
        scope: Optional filter — 'user' (personal only), 'system' (global only),
               or '' (both, default).

    Returns:
        Formatted list of behaviors with IDs, trigger/action, scope, and status.
    """
    behaviors = _list(user_id=user_id, scope=scope if scope else None)
    if not behaviors:
        return "No behaviors found."

    lines = [f"Found {len(behaviors)} behavior(s):\n"]
    for b in behaviors:
        status = "enabled" if b["enabled"] else "disabled"
        tag = f"[{b['scope']}]"
        lines.append(
            f"**{b['id']}** {tag} ({status})\n"
            f"  Trigger: {b['trigger_description']}\n"
            f"  Action:  {b['action_description']}"
        )
        if b.get("notes"):
            lines.append(f"  Notes:   {b['notes']}")
        lines.append("")
    return "\n".join(lines)


def update_behavior(
    behavior_id: str,
    trigger_description: str = "",
    action_description: str = "",
    notes: str = "",
) -> str:
    """Update an existing behavior rule's trigger, action, or notes.

    Only the fields you provide (non-empty strings) will be changed.

    Args:
        behavior_id: The behavior ID to update (e.g. "beh-abc12345").
        trigger_description: New trigger description, or empty to leave unchanged.
        action_description: New action description, or empty to leave unchanged.
        notes: New notes, or empty to leave unchanged.

    Returns:
        Confirmation of what was updated.
    """
    updated = _update(
        behavior_id=behavior_id,
        trigger_description=trigger_description or None,
        action_description=action_description or None,
        notes=notes or None,
    )
    if not updated:
        return f"Behavior {behavior_id} not found."
    try:
        digest_record("behaviors", "behavior", "updated", behavior_id, updated, by=updated.get("created_by", ""))
    except Exception:
        pass
    return (
        f"Behavior {behavior_id} updated.\n"
        f"Trigger: {updated['trigger_description']}\n"
        f"Action:  {updated['action_description']}"
    )


def remove_behavior(behavior_id: str) -> str:
    """Permanently delete a behavior rule.

    This cannot be undone. Use toggle_behavior to temporarily disable instead.

    Args:
        behavior_id: The behavior ID to delete (e.g. "beh-abc12345").

    Returns:
        Confirmation message.
    """
    record = _get(behavior_id) or {"id": behavior_id}
    deleted = _delete(behavior_id)
    if deleted:
        try:
            digest_record("behaviors", "behavior", "deleted", behavior_id, record, by=record.get("created_by", ""))
        except Exception:
            pass
        return f"Behavior {behavior_id} deleted."
    return f"Behavior {behavior_id} not found."


def toggle_behavior(behavior_id: str) -> str:
    """Toggle a behavior on or off without deleting it.

    Useful for temporarily suspending a rule without losing it.

    Args:
        behavior_id: The behavior ID to toggle (e.g. "beh-abc12345").

    Returns:
        The new enabled state.
    """
    result = _toggle(behavior_id)
    if not result:
        return f"Behavior {behavior_id} not found."
    try:
        digest_record("behaviors", "behavior", "updated", behavior_id, result, by=result.get("created_by", ""))
    except Exception:
        pass
    status = "enabled" if result["enabled"] else "disabled"
    return f"Behavior {behavior_id} is now {status}."
