"""Behaviors — data layer.

Low-level CRUD for the ``app_behaviors.behaviors`` table. All queries
are schema-scoped through ``app_platform.db``'s helpers so
``search_path`` is reset to ``app_behaviors, public`` for every
statement (no cross-schema leakage).

Public surface — re-exported via ``app_platform.behaviors``:

- ``create_behavior(trigger, action, created_by, scope='user', notes='', actor=None)``
- ``get_behavior(behavior_id)``
- ``list_behaviors(user_id=None, scope=None, enabled_only=False)``
- ``update_behavior(behavior_id, ..., actor=None)``
- ``toggle_behavior(behavior_id, actor=None)``
- ``delete_behavior(behavior_id, actor=None)``
- ``get_active_behaviors_for_user(user_id)``

Writes that touch a ``scope='system'`` rule require an admin ``actor`` and raise
``SystemScopeDenied`` otherwise — see ``_guard_system_scope``.
"""

from __future__ import annotations

import uuid

from app_platform.db import (
    execute_returning_in_schema,
    execute_in_schema,
    fetch_one_in_schema,
    fetch_all_in_schema,
)

SCHEMA = "app_behaviors"


class SystemScopeDenied(PermissionError):
    """A non-admin tried to create, edit, disable or delete a scope='system' rule."""


def _actor_is_admin(actor: str | None) -> bool:
    """Whether `actor` names a user holding the admin role. Unknown or empty → False."""
    # Imported lazily: this is a data layer, and the app package is imported by
    # app_platform.behaviors during platform load.
    from data_layer.users import get_user, has_role
    u = get_user((actor or "").lower().strip())
    return bool(u and has_role(u, "admin"))


def _guard_system_scope(actor: str | None, scope: str | None, action: str) -> None:
    """Raise unless `actor` may act on a scope='system' behavior.

    A system-scoped rule is concatenated verbatim into the chat system prompt of EVERY
    member on EVERY turn, so writing one steers what Skipper says to people who never saw
    it. That makes it an admin action — the guide has always said so; nothing enforced it.
    Scope='user' rules are untouched here: any member may write their own, whatever role
    they hold.

    Enforced in the data layer rather than at each route so a new caller cannot forget it,
    and it fails CLOSED: an actor we cannot resolve to an admin is refused.
    """
    if scope != "system":
        return
    if not _actor_is_admin(actor):
        raise SystemScopeDenied(
            f"Only an admin can {action} a system-wide behavior. "
            f"Personal behaviors (scope='user') are open to everyone."
        )


def _row_to_dict(row: dict | None) -> dict | None:
    """Normalize a DB row to a serializable behavior dict."""
    if row is None:
        return None
    r = dict(row)
    for k in ("created_at", "updated_at"):
        if r.get(k) and not isinstance(r[k], str):
            r[k] = r[k].isoformat()
    return r


def create_behavior(
    trigger_description: str,
    action_description: str,
    created_by: str,
    scope: str = "user",
    notes: str = "",
    actor: str | None = None,
) -> dict:
    """Insert a new behavior rule and return the created row.

    `actor` is the VERIFIED acting user, and is what the scope='system' check reads —
    `created_by` is a label and may be client-supplied. Raises SystemScopeDenied.
    """
    _guard_system_scope(actor, scope, "create")
    behavior_id = f"beh-{uuid.uuid4().hex[:8]}"
    row = execute_returning_in_schema(
        SCHEMA,
        """
        INSERT INTO behaviors
            (id, trigger_description, action_description, scope,
             enabled, created_by, notes, created_at, updated_at)
        VALUES (%s, %s, %s, %s, TRUE, %s, %s, now(), now())
        RETURNING *
        """,
        (behavior_id, trigger_description, action_description,
         scope, created_by, notes),
    )
    return _row_to_dict(row)


def list_behaviors(
    user_id: str | None = None,
    scope: str | None = None,
    enabled_only: bool = False,
) -> list[dict]:
    """List behaviors with optional filters.

    - user_id only: returns that user's own behaviors + all system behaviors.
    - scope='system': system-wide behaviors only.
    - scope='user' + user_id: that user's personal behaviors only.
    - enabled_only=True: skip disabled behaviors.
    """
    conditions: list[str] = []
    params: list = []

    if scope:
        conditions.append("scope = %s")
        params.append(scope)
        if scope == "user" and user_id:
            conditions.append("created_by = %s")
            params.append(user_id)
    elif user_id:
        conditions.append(
            "(scope = 'system' OR (scope = 'user' AND created_by = %s))"
        )
        params.append(user_id)

    if enabled_only:
        conditions.append("enabled = TRUE")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fetch_all_in_schema(
        SCHEMA,
        f"SELECT * FROM behaviors {where} ORDER BY scope DESC, created_at ASC",
        tuple(params),
    )
    return [_row_to_dict(r) for r in rows]


def get_behavior(behavior_id: str) -> dict | None:
    """Fetch a single behavior by ID."""
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM behaviors WHERE id = %s", (behavior_id,),
    )
    return _row_to_dict(row)


def update_behavior(
    behavior_id: str,
    trigger_description: str | None = None,
    action_description: str | None = None,
    scope: str | None = None,
    notes: str | None = None,
    actor: str | None = None,
) -> dict | None:
    """Update a behavior's fields. Only non-None values are changed.

    Both directions are gated: editing a rule that IS system-scoped (rewriting what every
    member's prompt says) and retargeting a personal rule INTO system scope (the
    escalation path — write it as your own, then promote it). Raises SystemScopeDenied.
    """
    existing = get_behavior(behavior_id)
    if existing:
        _guard_system_scope(actor, existing.get("scope"), "edit")
    _guard_system_scope(actor, scope, "promote a behavior to")

    updates: list[str] = []
    params: list = []

    if trigger_description is not None:
        updates.append("trigger_description = %s")
        params.append(trigger_description)
    if action_description is not None:
        updates.append("action_description = %s")
        params.append(action_description)
    if scope is not None:
        updates.append("scope = %s")
        params.append(scope)
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes)

    if not updates:
        return get_behavior(behavior_id)

    updates.append("updated_at = now()")
    params.append(behavior_id)

    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE behaviors SET {', '.join(updates)} "
        f"WHERE id = %s RETURNING *",
        tuple(params),
    )
    return _row_to_dict(row)


def toggle_behavior(behavior_id: str, actor: str | None = None) -> dict | None:
    """Flip the enabled flag of a behavior. Returns updated row.

    Gated for system-scoped rules too: silently disabling one removes a rule everybody was
    relying on, and re-enabling one restores text into everybody's prompt. Same lever as
    editing it. Raises SystemScopeDenied.
    """
    existing = get_behavior(behavior_id)
    if existing:
        _guard_system_scope(actor, existing.get("scope"), "enable or disable")
    row = execute_returning_in_schema(
        SCHEMA,
        "UPDATE behaviors SET enabled = NOT enabled, updated_at = now() "
        "WHERE id = %s RETURNING *",
        (behavior_id,),
    )
    return _row_to_dict(row)


def delete_behavior(behavior_id: str, actor: str | None = None) -> bool:
    """Delete a behavior permanently. Returns True if a row was deleted.

    Raises SystemScopeDenied for a system-scoped rule unless the actor is an admin.
    """
    existing = get_behavior(behavior_id)
    if existing:
        _guard_system_scope(actor, existing.get("scope"), "delete")
    affected = execute_in_schema(
        SCHEMA, "DELETE FROM behaviors WHERE id = %s", (behavior_id,),
    )
    return bool(affected and affected > 0)


def get_active_behaviors_for_user(user_id: str) -> list[dict]:
    """Return all enabled behaviors for a user (own personal + all system).

    Called by the chat domain on every chat turn to inject behaviors into
    the system prompt unconditionally.
    """
    return list_behaviors(user_id=user_id, enabled_only=True)
