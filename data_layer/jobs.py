"""Jobs — Postgres CRUD
=======================
Drop-in replacement for job_store.py's flat-file persistence.
"""

import logging
from datetime import datetime, timezone

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)


def save_job(j: dict):
    """Insert or update a job."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (
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
            ))
        conn.commit()


def get_job(job_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM jobs WHERE id = %s", (job_id,))
    return _row(row) if row else None


def get_all_jobs() -> list[dict]:
    return [_row(r) for r in fetch_all("SELECT * FROM jobs ORDER BY created_at")]


def get_active_jobs() -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM jobs WHERE status IN ('active', 'queued', 'running') AND cancelled = FALSE "
        "ORDER BY created_at"
    )]


def delete_job(job_id: str) -> bool:
    return execute("DELETE FROM jobs WHERE id = %s", (job_id,)) > 0


def save_all_jobs(jobs: list[dict]):
    """Bulk save — used by job_store's _save_jobs pattern."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for j in jobs:
                cur.execute("""
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
                """, (
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
                ))
        conn.commit()


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "job_type": row.get("job_type") or "shell",
        "command": row.get("command") or "",
        "description": row.get("description") or "",
        "scheduled_for": row.get("scheduled_for") or "",
        "notify_user": row.get("notify_user") or "",
        "status": row.get("status") or "active",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "last_run_at": row["last_run_at"].isoformat() if row.get("last_run_at") else "",
        "last_result": row.get("last_result") or "",
        "run_count": row.get("run_count", 0),
        "progress": row.get("progress") or "",
        "cancelled": row.get("cancelled", False),
        "config": row.get("config") or {},
        "output": row.get("output") or {},
    }
