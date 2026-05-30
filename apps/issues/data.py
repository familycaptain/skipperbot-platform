"""Issues App — Data Layer (Postgres CRUD)

Schema-aware queries targeting app_issues schema.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    scoped_conn,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_issues"

_ISSUE_HINT = (
    "Focus on: issue title, type (bug/feature/improvement), status (open/in_progress/resolved/closed), "
    "reporter, assignee, description of the problem or request, and resolution if resolved."
)


# Convenience wrappers
def _fetch_one(query, params=()):
    return fetch_one_in_schema(SCHEMA, query, params)


def _fetch_all(query, params=()):
    return fetch_all_in_schema(SCHEMA, query, params)


def _execute(query, params=()):
    return execute_in_schema(SCHEMA, query, params)


def _new_id() -> str:
    return f"iss-{uuid.uuid4().hex[:8]}"


def _row_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row.get("title", ""),
        "description": row.get("description", ""),
        "resolution": row.get("resolution", ""),
        "type": row.get("type", "bug"),
        "status": row.get("status", "open"),
        "reported_by": row.get("reported_by", ""),
        "assigned_to": row.get("assigned_to", "user"),
        "screenshots": row.get("screenshots") or [],
        "created_at": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else str(row.get("created_at", "")),
        "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else str(row.get("updated_at", "")),
    }


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_issue(issue: dict):
    """Insert or update an issue."""
    is_new = load_issue(issue["id"]) is None
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO issues (id, title, description, resolution, type, status,
                                    reported_by, assigned_to, screenshots, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    resolution = EXCLUDED.resolution,
                    type = EXCLUDED.type,
                    status = EXCLUDED.status,
                    reported_by = EXCLUDED.reported_by,
                    assigned_to = EXCLUDED.assigned_to,
                    screenshots = EXCLUDED.screenshots,
                    updated_at = EXCLUDED.updated_at
            """, (
                issue["id"],
                issue["title"],
                issue.get("description", ""),
                issue.get("resolution", ""),
                issue.get("type", "bug"),
                issue.get("status", "open"),
                issue.get("reported_by", ""),
                issue.get("assigned_to", "user"),
                issue.get("screenshots", []),
                issue.get("created_at", datetime.now(timezone.utc).isoformat()),
                issue.get("updated_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()
    saved = load_issue(issue["id"])
    if saved:
        digest_record(app_id="issues", entity_type="issue",
                      action="created" if is_new else "updated",
                      entity_id=issue["id"], record=saved,
                      by=issue.get("reported_by", ""), context_hint=_ISSUE_HINT)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_issue(issue_id: str) -> Optional[dict]:
    """Load a single issue by ID."""
    row = _fetch_one("SELECT * FROM issues WHERE id = %s", (issue_id,))
    return _row_to_dict(row) if row else None


def list_issues(
    status: Optional[str] = None,
    reported_by: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """List issues with optional filters. Open issues first, newest on top."""
    clauses = []
    params = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if reported_by:
        clauses.append("reported_by = %s")
        params.append(reported_by.lower().strip())

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = _fetch_all(f"""
        SELECT * FROM issues
        {where}
        ORDER BY
            CASE WHEN status IN ('open', 'in_progress') THEN 0 ELSE 1 END,
            created_at DESC
        LIMIT %s
    """, tuple(params))
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_issue(issue_id: str) -> bool:
    """Delete an issue by ID. Returns True if deleted."""
    issue = load_issue(issue_id)
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM issues WHERE id = %s", (issue_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    if deleted and issue:
        digest_record(app_id="issues", entity_type="issue", action="deleted",
                      entity_id=issue_id, record=issue, by="")
    return deleted


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "issue",
     "list_fn": lambda: list_issues(limit=5000),
     "context_hint": _ISSUE_HINT},
]
