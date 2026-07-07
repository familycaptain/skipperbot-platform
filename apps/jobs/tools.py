"""Jobs — MCP tools.

Four tools used by the chat agent:

- ``create_job(name, command, created_by, ...)`` — create a shell-style job
- ``get_jobs(status_filter="", created_by="")`` — list jobs
- ``update_job(job_id, ...)`` — modify a job (status / name / notify_user;
  ``schedule`` arg is deprecated — see note in update_job docstring)
- ``run_job(job_id, run_by="")`` — execute a job synchronously and
  record the result

Ported from ``tools/job_tool.py`` for sub-chunk 9e. Three changes:

1. Imports remapped to ``apps.jobs.store``.
2. The legacy ``schedule=`` parameter on ``create_job`` and
   ``update_job`` is now a deprecated no-op — the ``schedule`` column
   was dropped in legacy migration 063 (all recurring jobs run via
   the Schedules app instead). The tool keeps the parameter for
   backward compatibility but logs a deprecation warning when it's
   supplied.
3. ``run_job``'s cwd computation is updated for the new file location
   (apps/jobs/tools.py → up 3 directories to reach platform root).
"""

from __future__ import annotations

import logging
import os
import sys

# Make sure the platform root is on sys.path so this module is importable
# both as ``apps.jobs.tools`` and (rarely) directly.
APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from apps.jobs.store import (
    create_job as _create_job,
    get_job as _get_job,
    list_jobs as _list_jobs,
    update_job as _update_job,
    record_run as _record_run,
    format_jobs as _format_jobs,
)


_logger = logging.getLogger(__name__)


def create_job(
    name: str,
    command: str,
    created_by: str,
    schedule: str = "",
    notify_user: str = "",
    description: str = "",
) -> str:
    """Create a job. A job runs ONCE (on demand / when claimed) — it does NOT
    recur on its own.

    To run something on a cadence, do NOT expect this to schedule it: create a
    **Schedules** entry (the Schedules app / create_schedule) linked to this
    job's type — the schedule submits a fresh one-shot job each time it's due.

    Args:
        name: Human-readable job name (e.g. "Backup database").
        command: Shell command or script path to execute.
        created_by: Who is creating this job (person name).
        schedule: **Ignored — a job cannot self-schedule.** Passing it does NOT
                  make the job recurring (this was a silent footgun; the backing
                  column is gone). Create a Schedules entry to recur.
        notify_user: Who to notify on completion. Defaults to created_by.
        description: Optional description.

    Returns:
        Confirmation with job ID (and a warning if a schedule was passed).
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        if not command or not command.strip():
            return "Error: command is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        result = _create_job(
            name=name.strip(),
            command=command.strip(),
            created_by=created_by.strip().lower(),
            notify_user=notify_user.strip().lower() if notify_user else "",
            description=description.strip() if description else "",
        )

        out = ""
        if schedule and schedule.strip():
            out += ("⚠ 'schedule' was IGNORED — a job runs once and cannot "
                    "self-schedule. To make this recurring, create a Schedules "
                    "entry linked to this job.\n")
        out += f"Job created (ID: {result['id']}) — runs ONCE.\n"
        out += f"  Name: {result['name']}\n"
        out += f"  Command: {result['command']}\n"
        out += "  Recurrence: none (use the Schedules app to run it on a cadence)\n"
        out += f"  Notify: {result.get('notify_user')}\n"
        return out
    except Exception as e:
        return f"Error in create_job: {str(e)}"


def get_jobs(
    status_filter: str = "",
    created_by: str = "",
) -> str:
    """List all jobs with optional filters.

    Args:
        status_filter: Filter by status: "active", "paused", "completed", "failed".
        created_by: Filter by creator.

    Returns:
        Formatted job list.
    """
    try:
        jobs = _list_jobs(
            status_filter=status_filter.strip() if status_filter else "",
            created_by=created_by.strip().lower() if created_by else "",
        )
        return _format_jobs(jobs)
    except Exception as e:
        return f"Error in get_jobs: {str(e)}"


def update_job(
    job_id: str,
    updated_by: str = "",
    status: str = "",
    name: str = "",
    command: str = "",
    schedule: str = "",
    notify_user: str = "",
) -> str:
    """Update a job definition.

    Args:
        job_id: The job ID (e.g. "j-abc12345").
        updated_by: Who is making the update.
        status: New status: "active", "paused", "completed", "failed".
        name: New name.
        command: New command (note: the store layer's update_job does NOT
                 currently apply this — it only updates status / name /
                 notify_user. Kept here for forward compatibility.).
        schedule: **Deprecated.** No-op — see create_job docstring.
        notify_user: New notification recipient.

    Returns:
        Confirmation with changes.
    """
    try:
        if not job_id or not job_id.strip():
            return "Error: job_id is required."
        if schedule and schedule.strip():
            _logger.warning(
                "update_job: 'schedule' parameter is deprecated — link this "
                "job to a Schedules entry instead."
            )
        return _update_job(
            job_id=job_id.strip(),
            updated_by=updated_by.strip().lower() if updated_by else "",
            status=status.strip() if status else "",
            name=name.strip() if name else "",
            command=command.strip() if command else "",
            notify_user=notify_user.strip() if notify_user else "",
        )
    except Exception as e:
        return f"Error in update_job: {str(e)}"


def run_job(job_id: str, run_by: str = "") -> str:
    """Execute a job manually and record the result.

    Args:
        job_id: The job ID to run.
        run_by: Who triggered this run.

    Returns:
        Job output and status.
    """
    try:
        if not job_id or not job_id.strip():
            return "Error: job_id is required."

        job = _get_job(job_id.strip())
        if not job:
            return f"Error: Job '{job_id}' not found."

        import subprocess
        try:
            proc = subprocess.run(
                job["command"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=APP_ROOT,  # platform root, computed above
            )
            output = proc.stdout.strip() or proc.stderr.strip() or "(no output)"
            success = proc.returncode == 0
            result_msg = _record_run(job_id.strip(), output[:500], success)
            return f"{result_msg}\nReturn code: {proc.returncode}\nOutput:\n{output[:1000]}"
        except subprocess.TimeoutExpired:
            result_msg = _record_run(job_id.strip(), "Timed out (300s)", success=False)
            return f"{result_msg}\nJob timed out after 300 seconds."
        except Exception as e:
            result_msg = _record_run(job_id.strip(), str(e), success=False)
            return f"{result_msg}\nExecution error: {str(e)}"
    except Exception as e:
        return f"Error in run_job: {str(e)}"
