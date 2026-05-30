"""
Data layer for skipper_state — Skipper's persistent mind.

CRUD operations for state entries (focus, working_memory, pending_action,
observation, note, process_position).
"""

import uuid
from datetime import datetime

from app_platform.time import get_timezone
from data_layer.db import fetch_one, fetch_all, execute

VALID_STATE_TYPES = frozenset([
    "focus", "working_memory", "pending_action",
    "observation", "note", "process_position",
])

VALID_STATUSES = frozenset(["active", "resolved", "deferred", "expired"])
VALID_PRIORITIES = frozenset(["high", "medium", "low"])


def _new_id() -> str:
    return f"ss-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(get_timezone())


def _row_to_dict(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    for ts_col in ("created_at", "updated_at", "resolved_at", "due_at"):
        if isinstance(d.get(ts_col), datetime):
            d[ts_col] = d[ts_col].isoformat()
    return d


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_state(
    domain: str,
    state_type: str,
    subject_id: str,
    subject_type: str,
    content: str,
    priority: str | None = None,
    status: str = "active",
    due_at: str | None = None,
) -> dict:
    """Create a new skipper_state entry.

    Returns the created row as a dict.
    """
    state_id = _new_id()
    now = _now()

    execute("""
        INSERT INTO skipper_state
            (id, domain, state_type, subject_id, subject_type,
             content, priority, status, due_at, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        state_id, domain, state_type, subject_id, subject_type,
        content, priority, status,
        due_at, now, now,
    ))

    # Register edge: state → subject
    try:
        from data_layer.links import ensure_edge
        ensure_edge(state_id, subject_id, "anchored_to", "anchor_of")
    except Exception:
        pass

    return get_state(state_id)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_state(state_id: str) -> dict | None:
    """Get a single state entry by ID."""
    row = fetch_one("SELECT * FROM skipper_state WHERE id = %s", (state_id,))
    return _row_to_dict(row)


def list_states(
    domain: str | None = None,
    state_type: str | None = None,
    status: str | None = "active",
    subject_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query state entries with optional filters."""
    clauses = []
    params: list = []

    if domain:
        clauses.append("domain = %s")
        params.append(domain)
    if state_type:
        clauses.append("state_type = %s")
        params.append(state_type)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if subject_id:
        clauses.append("subject_id = %s")
        params.append(subject_id)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([limit, offset])

    rows = fetch_all(f"""
        SELECT * FROM skipper_state
        {where}
        ORDER BY
            CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
            updated_at DESC
        LIMIT %s OFFSET %s
    """, tuple(params))
    return [_row_to_dict(r) for r in rows]


def get_due_actions(
    domain: str | None = None,
    before: datetime | None = None,
) -> list[dict]:
    """Get active pending_action entries that are due (due_at <= cutoff)."""
    cutoff = before or _now()
    params: list = [cutoff]
    domain_clause = ""
    if domain:
        domain_clause = "AND domain = %s"
        params.append(domain)

    rows = fetch_all(f"""
        SELECT * FROM skipper_state
        WHERE state_type = 'pending_action'
          AND status = 'active'
          AND due_at IS NOT NULL
          AND due_at <= %s
          {domain_clause}
        ORDER BY due_at ASC
    """, tuple(params))
    return [_row_to_dict(r) for r in rows]


def get_working_memory(domain: str, subject_id: str | None = None) -> list[dict]:
    """Get active working_memory entries for a domain, optionally filtered by subject."""
    params: list = [domain]
    subject_clause = ""
    if subject_id:
        subject_clause = "AND subject_id = %s"
        params.append(subject_id)

    rows = fetch_all(f"""
        SELECT * FROM skipper_state
        WHERE domain = %s
          AND state_type = 'working_memory'
          AND status = 'active'
          {subject_clause}
        ORDER BY updated_at DESC
    """, tuple(params))
    return [_row_to_dict(r) for r in rows]


def count_states(
    domain: str | None = None,
    state_type: str | None = None,
    status: str = "active",
) -> int:
    """Count state entries matching filters."""
    clauses = ["status = %s"]
    params: list = [status]
    if domain:
        clauses.append("domain = %s")
        params.append(domain)
    if state_type:
        clauses.append("state_type = %s")
        params.append(state_type)

    where = " AND ".join(clauses)
    row = fetch_one(f"SELECT COUNT(*) as cnt FROM skipper_state WHERE {where}", tuple(params))
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_state(state_id: str, **kwargs) -> dict | None:
    """Update fields on a state entry. Supported kwargs: content, priority,
    status, due_at. Setting status to 'resolved' auto-sets resolved_at."""
    allowed = {"content", "priority", "status", "due_at", "subject_id", "subject_type"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return get_state(state_id)

    now = _now()
    updates["updated_at"] = now

    # Auto-set resolved_at when resolving
    if updates.get("status") in ("resolved", "expired"):
        updates["resolved_at"] = now

    set_parts = [f"{k} = %s" for k in updates]
    params = list(updates.values())
    params.append(state_id)

    execute(
        f"UPDATE skipper_state SET {', '.join(set_parts)} WHERE id = %s",
        tuple(params),
    )
    return get_state(state_id)


def resolve_state(state_id: str) -> dict | None:
    """Mark a state entry as resolved."""
    return update_state(state_id, status="resolved")


def expire_state(state_id: str) -> dict | None:
    """Mark a state entry as expired."""
    return update_state(state_id, status="expired")


# ---------------------------------------------------------------------------
# Upsert working memory — update if exists for same domain+subject, else create
# ---------------------------------------------------------------------------

def upsert_working_memory(
    domain: str,
    subject_id: str,
    subject_type: str,
    content: str,
    priority: str | None = None,
) -> dict:
    """Create or update a working_memory entry for a domain + subject pair.

    If an active working_memory already exists for this domain + subject_id,
    update its content and timestamp. Otherwise create a new one.
    """
    existing = fetch_one("""
        SELECT id FROM skipper_state
        WHERE domain = %s AND state_type = 'working_memory'
          AND subject_id = %s AND status = 'active'
    """, (domain, subject_id))

    if existing:
        return update_state(existing["id"], content=content, priority=priority)
    else:
        return create_state(
            domain=domain,
            state_type="working_memory",
            subject_id=subject_id,
            subject_type=subject_type,
            content=content,
            priority=priority,
        )


# ---------------------------------------------------------------------------
# Upsert focus — one per domain, shows what the domain is currently working on
# ---------------------------------------------------------------------------

def upsert_focus(
    domain: str,
    subject_id: str,
    subject_type: str,
    content: str,
) -> dict:
    """Create or update the single focus entry for a domain.

    Each domain gets exactly one focus entry — upserted each cycle
    to reflect what Skipper's mind is currently working on.
    """
    existing = fetch_one("""
        SELECT id FROM skipper_state
        WHERE domain = %s AND state_type = 'focus' AND status = 'active'
    """, (domain,))

    if existing:
        return update_state(existing["id"], content=content,
                            subject_id=subject_id, subject_type=subject_type)
    else:
        return create_state(
            domain=domain,
            state_type="focus",
            subject_id=subject_id,
            subject_type=subject_type,
            content=content,
        )


# ---------------------------------------------------------------------------
# Delete (soft — prefer resolve/expire; hard delete for cleanup only)
# ---------------------------------------------------------------------------

def delete_state(state_id: str) -> bool:
    """Hard-delete a state entry. Prefer resolve_state/expire_state."""
    execute("DELETE FROM skipper_state WHERE id = %s", (state_id,))
    return True
