"""Evolution Feed — CRUD for evolution_items and evolution_threads.

Supports the Evolve thinking domain's self-improvement tracking:
findings, proposals, questions, goals, work items, and status updates
with per-item conversation threads.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)


def _new_item_id() -> str:
    return f"ev-{uuid.uuid4().hex[:8]}"


def _new_thread_id() -> str:
    return f"et-{uuid.uuid4().hex[:8]}"


def _item_row(row: dict) -> dict:
    """Convert a DB row to an evolution_items dict."""
    if not row:
        return {}
    return {
        "id": row["id"],
        "type": row.get("type", ""),
        "status": row.get("status", "new"),
        "title": row.get("title", ""),
        "body": row.get("body", ""),
        "impact": row.get("impact"),
        "effort": row.get("effort"),
        "category": row.get("category"),
        "created_by": row.get("created_by"),
        "cycle_id": row.get("cycle_id"),
        "cycle_job_id": row.get("cycle_job_id"),
        "parent_id": row.get("parent_id"),
        "phase_origin": row.get("phase_origin"),
        "priority": row.get("priority"),
        "priority_pin": row.get("priority_pin"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "reviewed_at": _iso(row.get("reviewed_at")),
        "deferred_until": _iso(row.get("deferred_until")),
        "meta": row.get("meta") or {},
    }


def _thread_row(row: dict) -> dict:
    """Convert a DB row to an evolution_threads dict."""
    if not row:
        return {}
    return {
        "id": row["id"],
        "item_id": row.get("item_id", ""),
        "author": row.get("author", ""),
        "body": row.get("body", ""),
        "created_at": _iso(row.get("created_at")),
    }


def _iso(val) -> str:
    """Convert a datetime to ISO string, or empty string if None."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# Evolution Items — Create
# ---------------------------------------------------------------------------

def create_item(
    item_type: str,
    title: str,
    body: str,
    impact: Optional[str] = None,
    effort: Optional[str] = None,
    category: Optional[str] = None,
    created_by: Optional[str] = None,
    cycle_id: Optional[str] = None,
    cycle_job_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    phase_origin: Optional[str] = None,
    meta: Optional[dict] = None,
    item_id: Optional[str] = None,
) -> dict:
    """Create a new evolution item. Returns the created item dict."""
    item_id = item_id or _new_item_id()
    row = execute_returning("""
        INSERT INTO evolution_items (
            id, type, status, title, body, impact, effort, category,
            created_by, cycle_id, cycle_job_id, parent_id, phase_origin, meta
        ) VALUES (
            %s, %s, 'new', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) RETURNING *
    """, (
        item_id, item_type, title, body, impact, effort, category,
        created_by, cycle_id, cycle_job_id, parent_id, phase_origin, Json(meta or {}),
    ))

    if parent_id:
        ensure_edge(item_id, parent_id, "child_of", "parent_of")

    logger.info("EVOLUTION: Created %s item %s: %s", item_type, item_id, title)
    return _item_row(row) if row else {}


# ---------------------------------------------------------------------------
# Evolution Items — Read
# ---------------------------------------------------------------------------

def get_item(item_id: str) -> Optional[dict]:
    """Get a single evolution item by ID."""
    row = fetch_one("SELECT * FROM evolution_items WHERE id = %s", (item_id,))
    return _item_row(row) if row else None


def list_items(
    status: Optional[str] = None,
    item_type: Optional[str] = None,
    category: Optional[str] = None,
    parent_id: Optional[str] = None,
    include_completed: bool = False,
    limit: int = 100,
) -> list[dict]:
    """List evolution items with optional filters. Newest first."""
    clauses = []
    params = []

    if status:
        clauses.append("status = %s")
        params.append(status)
    elif not include_completed:
        clauses.append("status NOT IN ('completed', 'dismissed', 'rejected')")

    if item_type:
        clauses.append("type = %s")
        params.append(item_type)

    if category:
        clauses.append("category = %s")
        params.append(category)

    if parent_id:
        clauses.append("parent_id = %s")
        params.append(parent_id)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = fetch_all(f"""
        SELECT * FROM evolution_items
        {where}
        ORDER BY
            CASE WHEN status IN ('new', 'in_progress', 'approved') THEN 0 ELSE 1 END,
            priority NULLS LAST,
            created_at DESC
        LIMIT %s
    """, tuple(params))
    return [_item_row(r) for r in rows]


def list_items_with_unread_threads(limit: int = 50) -> list[dict]:
    """List evolution items that have thread messages newer than reviewed_at.

    Used by Phase 0 (Feedback Check) to find items with Alice's replies.
    """
    rows = fetch_all("""
        SELECT DISTINCT ei.* FROM evolution_items ei
        JOIN evolution_threads et ON et.item_id = ei.id
        WHERE ei.status NOT IN ('completed', 'dismissed', 'rejected')
          AND (
            ei.reviewed_at IS NULL
            OR et.created_at > ei.reviewed_at
          )
          AND et.author != 'skipper'
        ORDER BY ei.created_at DESC
        LIMIT %s
    """, (limit,))
    return [_item_row(r) for r in rows]


def get_children(parent_id: str) -> list[dict]:
    """Get all child items of a parent evolution item."""
    rows = fetch_all(
        "SELECT * FROM evolution_items WHERE parent_id = %s ORDER BY created_at",
        (parent_id,),
    )
    return [_item_row(r) for r in rows]


def get_item_with_thread(item_id: str) -> Optional[dict]:
    """Get an evolution item with its full conversation thread."""
    item = get_item(item_id)
    if not item:
        return None
    item["thread"] = get_thread(item_id)
    item["children"] = get_children(item_id)
    return item


# ---------------------------------------------------------------------------
# Evolution Items — Update
# ---------------------------------------------------------------------------

def update_item(item_id: str, **kwargs) -> Optional[dict]:
    """Update specific fields on an evolution item.

    Allowed fields: status, title, body, impact, effort, category,
    parent_id, deferred_until, reviewed_at, meta.
    """
    allowed = {
        "status", "title", "body", "impact", "effort", "category",
        "parent_id", "deferred_until", "reviewed_at", "meta", "priority",
        "priority_pin",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_item(item_id)

    # Always bump updated_at
    set_clauses = ["updated_at = now()"]
    params = []

    for key, val in updates.items():
        if key == "meta":
            set_clauses.append("meta = meta || %s")
            params.append(Json(val))
        else:
            set_clauses.append(f"{key} = %s")
            params.append(val)

    params.append(item_id)
    row = execute_returning(
        f"UPDATE evolution_items SET {', '.join(set_clauses)} WHERE id = %s RETURNING *",
        tuple(params),
    )
    return _item_row(row) if row else None


def set_status(item_id: str, status: str) -> Optional[dict]:
    """Update an item's status. Sets reviewed_at on first review."""
    kwargs = {"status": status}
    if status in ("reviewed", "approved", "redirected", "deferred", "rejected", "dismissed"):
        item = get_item(item_id)
        if item and not item["reviewed_at"]:
            kwargs["reviewed_at"] = datetime.now(timezone.utc)
    return update_item(item_id, **kwargs)


def defer_item(item_id: str, until: datetime) -> Optional[dict]:
    """Defer an item until a specific datetime."""
    return update_item(item_id, status="deferred", deferred_until=until)


def get_deferred_ready() -> list[dict]:
    """Get deferred items whose deferred_until has passed."""
    rows = fetch_all("""
        SELECT * FROM evolution_items
        WHERE status = 'deferred'
          AND deferred_until IS NOT NULL
          AND deferred_until <= now()
        ORDER BY deferred_until
    """)
    return [_item_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Evolution Items — Delete
# ---------------------------------------------------------------------------

def delete_item(item_id: str) -> bool:
    """Delete an evolution item and its threads (via CASCADE)."""
    n = execute("DELETE FROM evolution_items WHERE id = %s", (item_id,))
    return n > 0


# ---------------------------------------------------------------------------
# Evolution Threads — Create
# ---------------------------------------------------------------------------

def add_thread_message(
    item_id: str,
    author: str,
    body: str,
    thread_id: Optional[str] = None,
) -> dict:
    """Add a message to an evolution item's conversation thread."""
    thread_id = thread_id or _new_thread_id()
    row = execute_returning("""
        INSERT INTO evolution_threads (id, item_id, author, body)
        VALUES (%s, %s, %s, %s) RETURNING *
    """, (thread_id, item_id, author, body))

    # Bump the item's updated_at
    execute(
        "UPDATE evolution_items SET updated_at = now() WHERE id = %s",
        (item_id,),
    )

    logger.info("EVOLUTION: Thread message %s on %s by %s", thread_id, item_id, author)
    return _thread_row(row) if row else {}


# ---------------------------------------------------------------------------
# Evolution Threads — Read
# ---------------------------------------------------------------------------

def get_thread(item_id: str) -> list[dict]:
    """Get all messages in an evolution item's thread, oldest first."""
    rows = fetch_all(
        "SELECT * FROM evolution_threads WHERE item_id = %s ORDER BY created_at",
        (item_id,),
    )
    return [_thread_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Stats / Dashboard
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    """Get summary statistics for the Evolution Feed dashboard."""
    row = fetch_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'new') AS new_count,
            COUNT(*) FILTER (WHERE status = 'approved') AS approved_count,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
            COUNT(*) FILTER (WHERE status = 'deferred') AS deferred_count,
            COUNT(*) FILTER (WHERE status NOT IN ('completed', 'dismissed', 'rejected')) AS active_count,
            COUNT(*) AS total_count
        FROM evolution_items
    """)
    if not row:
        return {}
    return {
        "new": row.get("new_count", 0),
        "approved": row.get("approved_count", 0),
        "in_progress": row.get("in_progress_count", 0),
        "completed": row.get("completed_count", 0),
        "deferred": row.get("deferred_count", 0),
        "active": row.get("active_count", 0),
        "total": row.get("total_count", 0),
    }
