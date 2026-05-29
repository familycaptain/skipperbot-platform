"""Backups — data layer.

Schema-scoped CRUD for ``app_backups.backups``. The runner calls these
helpers; the platform shim ``app_platform.backups`` re-exports them
for cross-app callers (the system app's "Run backup now" button,
the daily ``backup_check`` job).
"""

from __future__ import annotations

import logging
from psycopg2.extras import Json

from app_platform.db import (
    execute_in_schema,
    execute_returning_in_schema,
    fetch_one_in_schema,
    fetch_all_in_schema,
)
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)

SCHEMA = "app_backups"


def create_backup(backup_id: str, job_id: str = "", created_by: str = "system") -> dict:
    """Create a new backup record (status=running)."""
    row = execute_returning_in_schema(
        SCHEMA,
        """
        INSERT INTO backups (id, job_id, started_at, status, created_by)
        VALUES (%s, %s, now(), 'running', %s)
        RETURNING *
        """,
        (backup_id, job_id or None, created_by),
    )
    if row and job_id:
        ensure_edge(backup_id, job_id, "created_by_job", "produced")
    return _row(row) if row else {}


def complete_backup(
    backup_id: str,
    pg_dump_size: int = 0,
    zip_size: int = 0,
    network_path: str = "",
    files_created: list | None = None,
    table_counts: dict | None = None,
    duration_secs: float = 0.0,
) -> dict:
    """Mark a backup as completed with final metadata."""
    row = execute_returning_in_schema(
        SCHEMA,
        """UPDATE backups SET
            status = 'completed',
            completed_at = now(),
            pg_dump_size = %s,
            zip_size = %s,
            network_path = %s,
            files_created = %s,
            table_counts = %s,
            duration_secs = %s
        WHERE id = %s RETURNING *""",
        (
            pg_dump_size, zip_size, network_path,
            Json(files_created or []),
            Json(table_counts or {}),
            duration_secs,
            backup_id,
        ),
    )
    return _row(row) if row else {}


def skip_backup(backup_id: str, reason: str = "Backups disabled") -> dict:
    """Mark a backup as skipped (master switch off / no destinations / etc.)."""
    row = execute_returning_in_schema(
        SCHEMA,
        """UPDATE backups SET
            status = 'skipped',
            completed_at = now(),
            duration_secs = 0,
            error = %s
        WHERE id = %s RETURNING *""",
        (reason[:2000], backup_id),
    )
    return _row(row) if row else {}


def fail_backup(backup_id: str, error: str = "") -> dict:
    """Mark a backup as failed."""
    row = execute_returning_in_schema(
        SCHEMA,
        """UPDATE backups SET
            status = 'failed',
            completed_at = now(),
            error = %s
        WHERE id = %s RETURNING *""",
        (error[:2000], backup_id),
    )
    return _row(row) if row else {}


def get_backup(backup_id: str) -> dict | None:
    """Get a single backup by ID."""
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM backups WHERE id = %s", (backup_id,))
    return _row(row) if row else None


def list_backups(limit: int = 20) -> list[dict]:
    """List all backups, most recent first."""
    return [_row(r) for r in fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM backups ORDER BY started_at DESC LIMIT %s",
        (limit,),
    )]


def delete_backup(backup_id: str) -> bool:
    """Delete a backup record."""
    n = execute_in_schema(SCHEMA, "DELETE FROM backups WHERE id = %s", (backup_id,))
    return n > 0


def prune_old_records(keep: int = 5) -> int:
    """Delete backup records beyond the retention count (oldest first).
    Only prunes completed backups. Returns number deleted."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT id FROM backups WHERE status = 'completed' ORDER BY started_at DESC",
        (),
    )
    if len(rows) <= keep:
        return 0
    to_delete = [r["id"] for r in rows[keep:]]
    n = execute_in_schema(
        SCHEMA, "DELETE FROM backups WHERE id = ANY(%s)", (to_delete,),
    )
    return n


def list_today(tz: str) -> list[dict]:
    """Return today's backup records (in the given timezone), most recent first.

    Used by the daily ``backup_check`` job to decide whether to nag.
    """
    from datetime import date
    today = date.today()
    rows = fetch_all_in_schema(
        SCHEMA,
        """
        SELECT id, status, error, started_at
        FROM backups
        WHERE (started_at AT TIME ZONE %s)::date = %s
        ORDER BY started_at DESC
        """,
        (tz, today),
    )
    # Light coercion — the check handler only reads id/status/error/started_at.
    return [
        {
            "id": r["id"],
            "status": r.get("status") or "running",
            "error": r.get("error") or "",
            "started_at": r["started_at"].isoformat() if r.get("started_at") else "",
        }
        for r in rows
    ]


def _row(row: dict) -> dict:
    """Convert a DB row to a clean dict."""
    if not row:
        return {}
    return {
        "id": row["id"],
        "job_id": row.get("job_id") or "",
        "started_at": row["started_at"].isoformat() if row.get("started_at") else "",
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else "",
        "status": row.get("status") or "running",
        "pg_dump_size": row.get("pg_dump_size") or 0,
        "zip_size": row.get("zip_size") or 0,
        "network_path": row.get("network_path") or "",
        "files_created": row.get("files_created") or [],
        "table_counts": row.get("table_counts") or {},
        "duration_secs": row.get("duration_secs") or 0.0,
        "error": row.get("error") or "",
        "created_by": row.get("created_by") or "system",
    }
