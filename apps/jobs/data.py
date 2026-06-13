"""Jobs — data layer (SQL CRUD + queue engine).

Owns reads + writes for the ``app_jobs.jobs`` and ``app_jobs.job_logs``
tables. Combines two source modules:

- ``data_layer/job_queue.py`` — atomic claim, progress, complete/fail,
  job logs (the queue-engine API used by the dispatcher).
- ``data_layer/jobs.py``     — simple save / get / list / delete
  (the API used by the friendlier ``job_store`` /
  ``apps.jobs.store``).

The standardized ``_row`` shape is the larger superset that includes
every column on ``app_jobs.jobs`` (status, queue, retry, output, etc.).

Ported from ``data_layer/job_queue.py`` + ``data_layer/jobs.py`` for
sub-chunk 9c-part-1. Functionally identical; only difference is
routing all queries through the ``*_in_schema`` helpers from
``app_platform.db`` so the jobs app's tables land in (and read from)
the ``app_jobs`` schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from psycopg2.extras import Json

from app_platform.db import (
    execute_in_schema,
    execute_returning_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)
from data_layer.links import ensure_edge  # platform infra — links live in public.*


logger = logging.getLogger(__name__)

SCHEMA = "app_jobs"


# ---------------------------------------------------------------------------
# Memory-digestion hint
# ---------------------------------------------------------------------------

_JOB_HINT = (
    "Focus on: the job's name, job_type, status (queued/running/completed/"
    "failed/cancelled), who submitted it, what command it ran, and whether "
    "it succeeded. Jobs are how chat answers 'did that backup actually run?'."
)


# ---------------------------------------------------------------------------
# Backfill registry
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES = [
    {
        "entity_type": "job",
        "list_fn": lambda: get_all_jobs(),
        "context_hint": _JOB_HINT,
    },
]


# =============================================================================
# Queue-engine API (ported from data_layer/job_queue.py)
# =============================================================================

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

    Returns the created job row (standardized shape).
    """
    import psycopg2.extras
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO jobs (
                    id, name, job_type, command, description,
                    schedule_expr, scheduled_for, notify_user, status,
                    created_by, created_at, progress, progress_pct,
                    cancelled, config, output, max_retries, parent_job_id
                ) VALUES (
                    %s, %s, %s, '', %s, %s, %s, %s, 'queued',
                    %s, now(), 'Queued', 0, FALSE, %s, '{}', %s, %s
                ) RETURNING *
                """,
                (
                    job_id, name, job_type, description,
                    Json(schedule_expr or {}),
                    scheduled_for, notify_user, created_by,
                    Json(config or {}), max_retries, parent_job_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row and parent_job_id:
        ensure_edge(job_id, parent_job_id, "child_of", "parent_of")
    return _row(row) if row else {}


def claim_queued_jobs(
    job_type: str = "",
    limit: int = 5,
    worker_id: str = "main",
) -> list[dict]:
    """Atomically claim queued jobs (status: queued → running).

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` for safe concurrent
    access. Returns claimed jobs.
    """
    type_filter = "AND job_type = %s" if job_type else ""
    params: list = []
    if job_type:
        params.append(job_type)
    params.extend([limit])

    import psycopg2.extras
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
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
                    last_progress_at = now(),
                    claimed_by = %s,
                    progress = 'Starting...',
                    progress_pct = 0
                FROM claimable
                WHERE jobs.id = claimable.id
                RETURNING jobs.*
                """,
                (*params, worker_id),
            )
            rows = cur.fetchall()
        conn.commit()
    return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Job logs
# ---------------------------------------------------------------------------

def append_log(job_id: str, level: str, message: str):
    """Append a log line to a job's log."""
    execute_in_schema(
        SCHEMA,
        "INSERT INTO job_logs (job_id, level, message) VALUES (%s, %s, %s)",
        (job_id, level, message[:4000]),
    )


def get_logs(job_id: str, limit: int = 500, after_id: int = 0) -> list[dict]:
    """Get log lines for a job, optionally after a given log ID (for polling)."""
    rows = fetch_all_in_schema(
        SCHEMA,
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
# Update progress / output
# ---------------------------------------------------------------------------

def update_progress(job_id: str, progress_pct: int, message: str = "") -> bool:
    """Update a running job's progress (0-100) and optional message."""
    pct = max(0, min(100, progress_pct))
    n = execute_in_schema(
        SCHEMA,
        "UPDATE jobs SET progress_pct = %s, progress = %s, last_progress_at = now() "
        "WHERE id = %s AND status = 'running'",
        (pct, message or f"{pct}% complete", job_id),
    )
    return n > 0


def update_output(job_id: str, output_updates: dict) -> bool:
    """Merge updates into a job's output JSONB field."""
    n = execute_in_schema(
        SCHEMA,
        "UPDATE jobs SET output = output || %s WHERE id = %s",
        (Json(output_updates), job_id),
    )
    return n > 0


# ---------------------------------------------------------------------------
# Complete / Fail
# ---------------------------------------------------------------------------

def complete_job(job_id: str, result: str = "", output: dict | None = None) -> dict | None:
    """Mark a job as completed."""
    row = execute_returning_in_schema(
        SCHEMA,
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
    job = get_job(job_id)
    if not job:
        return None

    if job["retry_count"] < job["max_retries"]:
        row = execute_returning_in_schema(
            SCHEMA,
            "UPDATE jobs SET status = 'queued', progress = 'Retrying...', "
            "progress_pct = 0, retry_count = retry_count + 1, "
            "error = %s, last_run_at = now(), run_count = run_count + 1 "
            "WHERE id = %s RETURNING *",
            (error[:500], job_id),
        )
    else:
        row = execute_returning_in_schema(
            SCHEMA,
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
    row = execute_returning_in_schema(
        SCHEMA,
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
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM jobs WHERE id = %s", (job_id,))
    return _row(row) if row else None


def is_cancelled(job_id: str) -> bool:
    """Check if a job has been cancelled (fast check for running handlers)."""
    row = fetch_one_in_schema(SCHEMA, "SELECT cancelled FROM jobs WHERE id = %s", (job_id,))
    return bool(row and row.get("cancelled"))


def list_jobs(
    status: str = "",
    job_type: str = "",
    limit: int = 50,
) -> list[dict]:
    """List jobs with optional filters."""
    clauses = []
    params: list = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if job_type:
        clauses.append("job_type = %s")
        params.append(job_type)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
    ]


def list_running() -> list[dict]:
    """List all currently running jobs."""
    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM jobs WHERE status = 'running' ORDER BY started_at",
        )
    ]


def fail_stale_running() -> int:
    """Mark all 'running' jobs as failed. Called at startup to recover
    from interrupted jobs."""
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = 'Agent restarted while job was running',
                    completed_at = now()
                WHERE status = 'running'
                RETURNING id
                """
            )
            rows = cur.fetchall()
            count = len(rows)
            if count:
                ids = [r[0] if isinstance(r, tuple) else r.get("id", r) for r in rows]
                logger.info("JOB_QUEUE: Marked %d stale running jobs as failed: %s", count, ids)
        conn.commit()
    return count


def fail_hung_jobs(minutes: int, exclude_ids: list[str] | None = None) -> list[str]:
    """Fail 'running' jobs with no progress in `minutes`, excluding the given ids.

    The dispatcher passes the ids it is actively running, so this only ever
    touches ORPHANED running rows (e.g. claimed by a worker that vanished) —
    never a live, slow-but-alive job in this process. Heartbeat is
    last_progress_at, falling back to started_at. Returns the failed ids.
    """
    if minutes is None or minutes <= 0:
        return []
    exclude = list(exclude_ids or [])
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = %s,
                    completed_at = now()
                WHERE status = 'running'
                  AND COALESCE(last_progress_at, started_at) < now() - make_interval(mins => %s)
                  AND NOT (id = ANY(%s))
                RETURNING id
                """,
                (f"No progress for over {minutes} minutes (auto-failed as hung)", minutes, exclude),
            )
            ids = [r[0] if isinstance(r, tuple) else r.get("id", r) for r in cur.fetchall()]
        conn.commit()
    if ids:
        logger.info("JOB_QUEUE: Auto-failed %d hung job(s): %s", len(ids), ids)
    return ids


def prune_job_logs(days: int) -> int:
    """Delete job_logs rows older than `days`. Returns the number deleted."""
    if days is None or days <= 0:
        return 0
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM job_logs WHERE created_at < now() - make_interval(days => %s)",
                (days,),
            )
            count = cur.rowcount
        conn.commit()
    if count:
        logger.info("JOB_QUEUE: Pruned %d job_log row(s) older than %dd", count, days)
    return count


def count_running(job_type: str = "") -> int:
    """Count running jobs, optionally by type."""
    if job_type:
        row = fetch_one_in_schema(
            SCHEMA,
            "SELECT COUNT(*) as cnt FROM jobs WHERE status = 'running' AND job_type = %s",
            (job_type,),
        )
    else:
        row = fetch_one_in_schema(
            SCHEMA,
            "SELECT COUNT(*) as cnt FROM jobs WHERE status = 'running'",
        )
    return row["cnt"] if row else 0


# =============================================================================
# Friendly CRUD (ported from data_layer/jobs.py)
# =============================================================================

def save_job(j: dict):
    """Insert or update a job (the friendlier upsert path)."""
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (id, name, job_type, command, description,
                                  scheduled_for, notify_user, status, created_by,
                                  created_at, last_run_at, last_result, run_count,
                                  progress, cancelled, config, output)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    job_type = EXCLUDED.job_type,
                    command = EXCLUDED.command,
                    description = EXCLUDED.description,
                    scheduled_for = EXCLUDED.scheduled_for,
                    notify_user = EXCLUDED.notify_user,
                    status = EXCLUDED.status,
                    last_run_at = EXCLUDED.last_run_at,
                    last_result = EXCLUDED.last_result,
                    run_count = EXCLUDED.run_count,
                    progress = EXCLUDED.progress,
                    cancelled = EXCLUDED.cancelled,
                    config = EXCLUDED.config,
                    output = EXCLUDED.output
                """,
                (
                    j["id"], j["name"], j.get("job_type", "shell"),
                    j.get("command", ""), j.get("description", ""),
                    j.get("scheduled_for", ""),
                    j.get("notify_user", ""), j.get("status", "active"),
                    j.get("created_by", ""),
                    j.get("created_at", datetime.now(timezone.utc).isoformat()),
                    j.get("last_run_at") or None,
                    j.get("last_result", ""), j.get("run_count", 0),
                    j.get("progress", ""), j.get("cancelled", False),
                    Json(j.get("config") or {}), Json(j.get("output") or {}),
                ),
            )
        conn.commit()


def get_all_jobs() -> list[dict]:
    """List all jobs ordered by created_at (no filtering)."""
    return [
        _row(r)
        for r in fetch_all_in_schema(SCHEMA, "SELECT * FROM jobs ORDER BY created_at")
    ]


def get_active_jobs() -> list[dict]:
    """List jobs in active/queued/running status (not cancelled)."""
    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM jobs WHERE status IN ('active', 'queued', 'running') "
            "AND cancelled = FALSE ORDER BY created_at",
        )
    ]


def delete_job(job_id: str) -> bool:
    """Hard-delete a job row."""
    return execute_in_schema(SCHEMA, "DELETE FROM jobs WHERE id = %s", (job_id,)) > 0


def save_all_jobs(jobs: list[dict]):
    """Bulk save — used by job_store's _save_jobs pattern."""
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            for j in jobs:
                cur.execute(
                    """
                    INSERT INTO jobs (id, name, job_type, command, description,
                                      scheduled_for, notify_user, status, created_by,
                                      created_at, last_run_at, last_result, run_count,
                                      progress, cancelled, config, output)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, status = EXCLUDED.status,
                        last_run_at = EXCLUDED.last_run_at, last_result = EXCLUDED.last_result,
                        run_count = EXCLUDED.run_count, progress = EXCLUDED.progress,
                        cancelled = EXCLUDED.cancelled, config = EXCLUDED.config,
                        output = EXCLUDED.output
                    """,
                    (
                        j["id"], j["name"], j.get("job_type", "shell"),
                        j.get("command", ""), j.get("description", ""),
                        j.get("scheduled_for", ""),
                        j.get("notify_user", ""), j.get("status", "active"),
                        j.get("created_by", ""),
                        j.get("created_at", datetime.now(timezone.utc).isoformat()),
                        j.get("last_run_at") or None,
                        j.get("last_result", ""), j.get("run_count", 0),
                        j.get("progress", ""), j.get("cancelled", False),
                        Json(j.get("config") or {}), Json(j.get("output") or {}),
                    ),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# Row mapper — superset of all jobs.* columns
# ---------------------------------------------------------------------------

def _row(row: dict) -> dict:
    """Convert a DB row to a clean dict (standardized shape)."""
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
