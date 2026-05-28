"""Job Store
==========
Scheduled process execution (j-* IDs).
A job is a command or script that runs on a schedule or on-demand,
and emits a notification on completion.

Backed by Postgres via data_layer.job_queue (direct SQL).
"""

import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE
from auto_memory import log_entity_change
import data_layer.job_queue as _q

CENTRAL_TZ = ZoneInfo(TIMEZONE)

VALID_STATUSES = {"active", "paused", "completed", "failed", "queued", "running", "cancelled"}
VALID_JOB_TYPES = {"shell", "research", "print", "refine", "pm", "investment", "rebalance"}


def _now_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_job(
    name: str,
    command: str,
    created_by: str,
    notify_user: str = "",
    description: str = "",
) -> dict:
    """Create a new job definition."""
    job = _q.create_job(
        job_id=f"j-{uuid.uuid4().hex[:8]}",
        name=name,
        job_type="shell",
        created_by=created_by.lower().strip(),
        description=description.strip() if description else "",
        notify_user=notify_user.lower().strip() if notify_user else created_by.lower().strip(),
        config={"command": command},
    )
    # Keep 'command' at top level for backward compat
    job["command"] = command
    log_entity_change("created", job["id"], "job",
                      f"{name}: {command[:80]}", by=created_by)
    return job


def get_job(job_id: str) -> dict | None:
    """Get a job by ID."""
    return _q.get_job(job_id)


def list_jobs(status_filter: str = "", created_by: str = "") -> list[dict]:
    """List jobs with optional filters."""
    jobs = _q.list_jobs(status=status_filter.lower().strip() if status_filter else "")
    if created_by:
        cb = created_by.lower().strip()
        jobs = [j for j in jobs if j.get("created_by") == cb]
    return jobs


def update_job(
    job_id: str,
    updated_by: str = "",
    status: str = "",
    name: str = "",
    command: str = "",
    notify_user: str = "",
) -> str:
    """Update a job definition."""
    from data_layer.db import execute
    job = _q.get_job(job_id)
    if not job:
        return f"Job '{job_id}' not found."

    changes = []
    sets = []
    params = []

    if status and status.strip().lower() in VALID_STATUSES:
        old = job["status"]
        sets.append("status = %s")
        params.append(status.strip().lower())
        changes.append(f"status: {old} → {status.strip().lower()}")
    if name and name.strip():
        sets.append("name = %s")
        params.append(name.strip())
        changes.append(f"name → {name.strip()}")
    if notify_user and notify_user.strip():
        sets.append("notify_user = %s")
        params.append(notify_user.strip().lower())
        changes.append(f"notify_user → {notify_user.strip().lower()}")

    if not changes:
        return f"No changes to job {job_id}."

    params.append(job_id)
    execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", tuple(params))
    log_entity_change("updated", job_id, "job",
                      "; ".join(changes), by=updated_by)
    return f"Job {job_id} updated: {'; '.join(changes)}"


def record_run(job_id: str, result: str, success: bool = True) -> str:
    """Record the result of a job execution."""
    if success:
        _q.complete_job(job_id, result=result[:500])
    else:
        _q.fail_job(job_id, error=result[:500])

    log_entity_change("executed", job_id, "job",
                      f"{'OK' if success else 'FAILED'}: {result[:80]}")

    # Emit notification
    job = _q.get_job(job_id)
    if job:
        try:
            from notification_store import create_notification
            status_label = "completed" if success else "FAILED"
            create_notification(
                recipient=job.get("notify_user") or job.get("created_by", ""),
                message=f"Job '{job['name']}' {status_label}: {result[:200]}",
                source_type="job",
                source_id=job_id,
                channel="discord",
                delivered=True,
            )
        except Exception as e:
            logger.error("JOB [%s]: Failed to create notification: %s", job_id, e)

    return f"Job {job_id} recorded ({'OK' if success else 'FAILED'})."


# ---------------------------------------------------------------------------
# Research jobs
# ---------------------------------------------------------------------------

def create_research_job(
    query: str,
    requested_by: str,
    num_sources: int = 5,
    scheduled_for: str = "",
    related_entity_id: str = "",
    notify_user: str = "",
    tags: list[str] | None = None,
    spec_doc_id: str = "",
) -> dict:
    """Create a background research job."""
    num_sources = max(1, min(20, num_sources))

    job = _q.create_job(
        job_id=f"j-{uuid.uuid4().hex[:8]}",
        name=f"Research: {query[:60]}",
        job_type="research",
        created_by=requested_by.lower().strip(),
        description=f"Background research on: {query}",
        scheduled_for=scheduled_for.strip() if scheduled_for else "",
        notify_user=(notify_user or requested_by).lower().strip(),
        config={
            "query": query,
            "num_sources": num_sources,
            "related_entity_id": related_entity_id.strip() if related_entity_id else "",
            "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
            "spec_doc_id": spec_doc_id.strip() if spec_doc_id else "",
        },
    )
    log_entity_change("created", job["id"], "job",
                      f"Research: {query[:80]}", by=requested_by)
    return job


def get_pending_research_jobs() -> list[dict]:
    """Get research jobs that are ready to run (queued + due)."""
    return _q.list_jobs(status="queued", job_type="research")


def update_job_progress(job_id: str, progress: str, status: str = "",
                        output_updates: dict | None = None) -> bool:
    """Update a job's progress message and optionally status/output."""
    from data_layer.db import execute
    sets = ["progress = %s"]
    params = [progress]
    if status and status in VALID_STATUSES:
        sets.append("status = %s")
        params.append(status)
    params.append(job_id)
    n = execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", tuple(params))
    if output_updates:
        _q.update_output(job_id, output_updates)
    return n > 0


def create_print_job(
    doc_id: str,
    requested_by: str,
    copies: int = 1,
    notify_user: str = "",
) -> dict:
    """Create a background print job for a document."""
    copies = max(1, min(10, copies))
    job = _q.create_job(
        job_id=f"j-{uuid.uuid4().hex[:8]}",
        name=f"Print: {doc_id}",
        job_type="print",
        created_by=requested_by.lower().strip(),
        description=f"Print document {doc_id} ({copies} {'copy' if copies == 1 else 'copies'})",
        notify_user=(notify_user or requested_by).lower().strip(),
        config={"doc_id": doc_id.strip(), "copies": copies},
    )
    log_entity_change("created", job["id"], "job",
                      f"Print: {doc_id} ({copies} copies)", by=requested_by)
    return job


def create_recipe_print_job(
    recipe_id: str,
    requested_by: str,
    copies: int = 1,
    notify_user: str = "",
) -> dict:
    """Create a background print job for a recipe."""
    copies = max(1, min(10, copies))
    job = _q.create_job(
        job_id=f"j-{uuid.uuid4().hex[:8]}",
        name=f"Print: {recipe_id}",
        job_type="print",
        created_by=requested_by.lower().strip(),
        description=f"Print recipe {recipe_id} ({copies} {'copy' if copies == 1 else 'copies'})",
        notify_user=(notify_user or requested_by).lower().strip(),
        config={"recipe_id": recipe_id.strip(), "copies": copies},
    )
    log_entity_change("created", job["id"], "job",
                      f"Print: {recipe_id} ({copies} copies)", by=requested_by)
    return job


def get_pending_print_jobs() -> list[dict]:
    """Get print jobs that are ready to run (queued)."""
    return _q.list_jobs(status="queued", job_type="print")


def create_refine_job(
    doc_id: str,
    instructions: str,
    requested_by: str,
    num_sources: int = 3,
    notify_user: str = "",
) -> dict:
    """Create a background refinement job for an existing research document."""
    num_sources = max(1, min(20, num_sources))
    job = _q.create_job(
        job_id=f"j-{uuid.uuid4().hex[:8]}",
        name=f"Refine: {doc_id}",
        job_type="refine",
        created_by=requested_by.lower().strip(),
        description=f"Refine document {doc_id}: {instructions[:100]}",
        notify_user=(notify_user or requested_by).lower().strip(),
        config={
            "doc_id": doc_id.strip(),
            "instructions": instructions.strip(),
            "num_sources": num_sources,
        },
    )
    log_entity_change("created", job["id"], "job",
                      f"Refine: {doc_id} — {instructions[:80]}",
                      by=requested_by,
                      related_entities=[doc_id])
    return job


def get_pending_refine_jobs() -> list[dict]:
    """Get refine jobs that are ready to run (queued)."""
    return _q.list_jobs(status="queued", job_type="refine")


def cancel_job(job_id: str, cancelled_by: str = "") -> str:
    """Cancel a queued or running job."""
    job = _q.get_job(job_id)
    if not job:
        return f"Job '{job_id}' not found."
    if job.get("status") in ("completed", "failed", "cancelled"):
        return f"Job {job_id} is already {job['status']}."
    _q.cancel_job(job_id, cancelled_by=cancelled_by)
    log_entity_change("cancelled", job_id, "job",
                      f"{job.get('name', '?')}", by=cancelled_by)
    return f"Job {job_id} cancelled."


def delete_job(job_id: str) -> bool:
    """Delete a job."""
    from data_layer.db import execute
    n = execute("DELETE FROM jobs WHERE id = %s", (job_id,))
    if n:
        log_entity_change("deleted", job_id, "job", "Job removed")
    return n > 0


def format_jobs(jobs: list[dict]) -> str:
    """Format jobs for display."""
    if not jobs:
        return "No jobs found."

    lines = [f"Jobs ({len(jobs)}):"]
    for j in jobs:
        sched = " [manual]"
        last = f" (last: {j['last_run_at'][:16]})" if j.get("last_run_at") else ""
        runs = f" runs: {j.get('run_count', 0)}"
        lines.append(f"  [{j['id']}] {j['name']} — {j['status'].upper()}{sched}{last}{runs}")
        lines.append(f"    cmd: {j['command'][:60]}  notify: {j.get('notify_user', '?')}")
    return "\n".join(lines)
