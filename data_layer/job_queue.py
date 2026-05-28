"""Job Queue — Efficient SQL-based job queue operations.

Provides atomic claim, update, cancel, and query operations for the
unified job system. All operations use direct SQL — no load-all/save-all.
"""

import json
import logging
from datetime import datetime, timezone

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_job(
    job_id: str,
    name: str,
    job_type: str,
    created_by: str = "",
    description: str = "",
    schedule_expr: dict | None = None,
    scheduled_for: str = "",
    notify_user: str = "",
    config: dict | None = None,
    parent_job_id: str = "",
    max_retries: int = 0,
) -> dict:
    """Create a new job in the queue.

    Returns the created job row.
    """
    import psycopg2.extras
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO jobs (
                    id, name, job_type, command, description,
                    schedule_expr, scheduled_for, notify_user, status,
                    created_by, created_at, progress, progress_pct,
                    cancelled, config, output, max_retries, parent_job_id
                ) VALUES (
                    %s, %s, %s, '', %s, %s, %s, %s, 'queued',
                    %s, now(), 'Queued', 0, FALSE, %s, '{}', %s, %s
                ) RETURNING *
            """, (
                job_id, name, job_type, description,
                Json(schedule_expr or {}),
                scheduled_for, notify_user, created_by,
                Json(config or {}), max_retries, parent_job_id,
            ))
            row = cur.fetchone()
        conn.commit()
    if row and parent_job_id:
        ensure_edge(job_id, parent_job_id, "child_of", "parent_of")
    return _row(row) if row else {}


# ---------------------------------------------------------------------------
# Claim (atomic: queued → running)
# ---------------------------------------------------------------------------

def claim_queued_jobs(job_type: str = "", limit: int = 5,
                      worker_id: str = "main") -> list[dict]:
    """Atomically claim queued jobs (status: queued → running).

    Uses SELECT ... FOR UPDATE SKIP LOCKED for safe concurrent access.
    Returns claimed jobs.
    """
    type_filter = "AND job_type = %s" if job_type else ""
    params = []
    if job_type:
        params.append(job_type)
    params.extend([limit])

    import psycopg2.extras
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                WITH claimable AS (
                    SELECT id FROM jobs
                    WHERE status = 'queued'
                      AND cancelled = FALSE
                      {type_filter}
                    ORDER BY created_at
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE jobs SET
                    status = 'running',
                    started_at = now(),
                    claimed_by = %s,
                    progress = 'Starting...',
                    progress_pct = 0
                FROM claimable
                WHERE jobs.id = claimable.id
                RETURNING jobs.*
            """, (*params, worker_id))
            rows = cur.fetchall()
        conn.commit()
    return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Job logs
# ---------------------------------------------------------------------------

def append_log(job_id: str, level: str, message: str):
    """Append a log line to a job's log."""
    execute(
        "INSERT INTO job_logs (job_id, level, message) VALUES (%s, %s, %s)",
        (job_id, level, message[:4000]),
    )


def get_logs(job_id: str, limit: int = 500, after_id: int = 0) -> list[dict]:
    """Get log lines for a job, optionally after a given log ID (for polling)."""
    rows = fetch_all(
        "SELECT id, created_at, level, message FROM job_logs "
        "WHERE job_id = %s AND id > %s ORDER BY id LIMIT %s",
        (job_id, after_id, limit),
    )
    return [{
        "id": r["id"],
        "ts": r["created_at"].isoformat() if r.get("created_at") else "",
        "level": r.get("level", "INFO"),
        "message": r.get("message", ""),
    } for r in rows]


# ---------------------------------------------------------------------------
# Update progress
# ---------------------------------------------------------------------------

def update_progress(job_id: str, progress_pct: int, message: str = "") -> bool:
    """Update a running job's progress (0-100) and optional message."""
    pct = max(0, min(100, progress_pct))
    n = execute(
        "UPDATE jobs SET progress_pct = %s, progress = %s "
        "WHERE id = %s AND status = 'running'",
        (pct, message or f"{pct}% complete", job_id),
    )
    return n > 0


def update_output(job_id: str, output_updates: dict) -> bool:
    """Merge updates into a job's output JSONB field."""
    n = execute(
        "UPDATE jobs SET output = output || %s WHERE id = %s",
        (Json(output_updates), job_id),
    )
    return n > 0


# ---------------------------------------------------------------------------
# Complete / Fail
# ---------------------------------------------------------------------------

def complete_job(job_id: str, result: str = "", output: dict | None = None) -> dict | None:
    """Mark a job as completed."""
    row = execute_returning(
        "UPDATE jobs SET status = 'completed', progress_pct = 100, "
        "progress = 'Done', completed_at = now(), last_run_at = now(), "
        "last_result = %s, run_count = run_count + 1, "
        "output = CASE WHEN %s::jsonb != '{}'::jsonb THEN %s::jsonb ELSE output END "
        "WHERE id = %s RETURNING *",
        (result[:500], Json(output or {}), Json(output or {}), job_id),
    )
    return _row(row) if row else None


def fail_job(job_id: str, error: str = "") -> dict | None:
    """Mark a job as failed. Will re-queue if retries remain."""
    # Check retry
    job = get_job(job_id)
    if not job:
        return None

    if job["retry_count"] < job["max_retries"]:
        row = execute_returning(
            "UPDATE jobs SET status = 'queued', progress = 'Retrying...', "
            "progress_pct = 0, retry_count = retry_count + 1, "
            "error = %s, last_run_at = now(), run_count = run_count + 1 "
            "WHERE id = %s RETURNING *",
            (error[:500], job_id),
        )
    else:
        row = execute_returning(
            "UPDATE jobs SET status = 'failed', progress = 'Failed', "
            "completed_at = now(), last_run_at = now(), "
            "last_result = %s, error = %s, run_count = run_count + 1 "
            "WHERE id = %s RETURNING *",
            (error[:500], error[:500], job_id),
        )
    return _row(row) if row else None


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def cancel_job(job_id: str, cancelled_by: str = "") -> dict | None:
    """Cancel a job. Works on queued or running jobs."""
    msg = f"Cancelled by {cancelled_by}" if cancelled_by else "Cancelled"
    row = execute_returning(
        "UPDATE jobs SET status = 'cancelled', cancelled = TRUE, "
        "progress = %s, completed_at = now() "
        "WHERE id = %s AND status IN ('queued', 'running') RETURNING *",
        (msg, job_id),
    )
    return _row(row) if row else None


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_job(job_id: str) -> dict | None:
    """Get a single job by ID."""
    row = fetch_one("SELECT * FROM jobs WHERE id = %s", (job_id,))
    return _row(row) if row else None


def is_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled (fast check for running handlers)."""
    row = fetch_one("SELECT cancelled FROM jobs WHERE id = %s", (job_id,))
    return bool(row and row.get("cancelled"))


def list_jobs(
    status: str = "",
    job_type: str = "",
    limit: int = 50,
) -> list[dict]:
    """List jobs with optional filters."""
    clauses = []
    params = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if job_type:
        clauses.append("job_type = %s")
        params.append(job_type)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    return [_row(r) for r in fetch_all(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT %s",
        tuple(params),
    )]


def list_running() -> list[dict]:
    """List all currently running jobs."""
    return [_row(r) for r in fetch_all(
        "SELECT * FROM jobs WHERE status = 'running' ORDER BY started_at"
    )]


def fail_stale_running() -> int:
    """Mark all 'running' jobs as failed, and clean up orphaned
    investment snapshots. Call at startup to recover from interrupted jobs."""
    # Job cleanup — separate transaction so investment errors can't roll it back
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jobs
                SET status = 'failed',
                    error = 'Agent restarted while job was running',
                    completed_at = now()
                WHERE status = 'running'
                RETURNING id
            """)
            rows = cur.fetchall()
            count = len(rows)
            if count:
                ids = [r[0] if isinstance(r, tuple) else r.get("id", r) for r in rows]
                logger.info("JOB_QUEUE: Marked %d stale running jobs as failed: %s", count, ids)
        conn.commit()

    return count


def count_running(job_type: str = "") -> int:
    """Count running jobs, optionally by type."""
    if job_type:
        row = fetch_one(
            "SELECT COUNT(*) as cnt FROM jobs WHERE status = 'running' AND job_type = %s",
            (job_type,),
        )
    else:
        row = fetch_one("SELECT COUNT(*) as cnt FROM jobs WHERE status = 'running'")
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Row mapper
# ---------------------------------------------------------------------------

def _row(row: dict) -> dict:
    """Convert a DB row to a clean dict."""
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "job_type": row.get("job_type") or "shell",
        "command": row.get("command") or "",
        "description": row.get("description") or "",
        "schedule_expr": row.get("schedule_expr") or {},
        "scheduled_for": row.get("scheduled_for") or "",
        "notify_user": row.get("notify_user") or "",
        "status": row.get("status") or "queued",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "started_at": row["started_at"].isoformat() if row.get("started_at") else "",
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else "",
        "last_run_at": row["last_run_at"].isoformat() if row.get("last_run_at") else "",
        "last_result": row.get("last_result") or "",
        "run_count": row.get("run_count", 0),
        "progress": row.get("progress") or "",
        "progress_pct": row.get("progress_pct", 0),
        "cancelled": row.get("cancelled", False),
        "claimed_by": row.get("claimed_by") or "",
        "config": row.get("config") or {},
        "output": row.get("output") or {},
        "error": row.get("error") or "",
        "max_retries": row.get("max_retries", 0),
        "retry_count": row.get("retry_count", 0),
        "parent_job_id": row.get("parent_job_id") or "",
    }
