"""Data layer for user-customizable behavior rules.

Behaviors are if/then rules stored in the database and injected
unconditionally into every chat system prompt for the relevant user.
Unlike memories (semantic injection), behaviors are ALWAYS present —
making them reliable for automation-style rules.
"""

import uuid

from data_layer.db import get_conn, fetch_one, fetch_all, execute


def _row_to_dict(row: dict) -> dict:
    """Normalize a DB row to a serializable behavior dict."""
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
) -> dict:
    """Insert a new behavior rule and return the created row."""
    behavior_id = f"beh-{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
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
            columns = [d[0] for d in cur.description]
            row = dict(zip(columns, cur.fetchone()))
        conn.commit()
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
    rows = fetch_all(
        f"SELECT * FROM behaviors {where} ORDER BY scope DESC, created_at ASC",
        tuple(params) if params else None,
    )
    return [_row_to_dict(r) for r in rows]


def get_behavior(behavior_id: str) -> dict | None:
    """Fetch a single behavior by ID."""
    row = fetch_one("SELECT * FROM behaviors WHERE id = %s", (behavior_id,))
    return _row_to_dict(row) if row else None


def update_behavior(
    behavior_id: str,
    trigger_description: str | None = None,
    action_description: str | None = None,
    scope: str | None = None,
    notes: str | None = None,
) -> dict | None:
    """Update a behavior's fields. Only non-None values are changed."""
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

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE behaviors SET {', '.join(updates)} "
                f"WHERE id = %s RETURNING *",
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            columns = [d[0] for d in cur.description]
            result = dict(zip(columns, row))
        conn.commit()
    return _row_to_dict(result)


def toggle_behavior(behavior_id: str) -> dict | None:
    """Flip the enabled flag of a behavior. Returns updated row."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE behaviors SET enabled = NOT enabled, updated_at = now() "
                "WHERE id = %s RETURNING *",
                (behavior_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            columns = [d[0] for d in cur.description]
            result = dict(zip(columns, row))
        conn.commit()
    return _row_to_dict(result)


def delete_behavior(behavior_id: str) -> bool:
    """Delete a behavior permanently. Returns True if a row was deleted."""
    affected = execute(
        "DELETE FROM behaviors WHERE id = %s",
        (behavior_id,),
    )
    return bool(affected and affected > 0)


def get_active_behaviors_for_user(user_id: str) -> list[dict]:
    """Return all enabled behaviors for a user (own personal + all system).

    Called by the chat domain on every chat turn to inject behaviors into
    the system prompt unconditionally.
    """
    return list_behaviors(user_id=user_id, enabled_only=True)
