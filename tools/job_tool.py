"""
Job Tools - Create and manage scheduled/on-demand jobs.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from job_store import (
    create_job as _create_job,
    get_job as _get_job,
    list_jobs as _list_jobs,
    update_job as _update_job,
    record_run as _record_run,
    delete_job as _delete_job,
    format_jobs as _format_jobs,
)


def create_job(
    name: str,
    command: str,
    created_by: str,
    schedule: str = "",
    notify_user: str = "",
    description: str = "",
) -> str:
    """Create a new scheduled or on-demand job.

    Args:
        name: Human-readable job name (e.g. "Backup database").
        command: Shell command or script path to execute.
        created_by: Who is creating this job (person name).
        schedule: Optional schedule (cron or RRULE). Empty = manual only.
        notify_user: Who to notify on completion. Defaults to created_by.
        description: Optional description.

    Returns:
        Confirmation with job ID.
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
            schedule=schedule.strip() if schedule else "",
            notify_user=notify_user.strip().lower() if notify_user else "",
            description=description.strip() if description else "",
        )

        out = f"Job created (ID: {result['id']}).\n"
        out += f"  Name: {result['name']}\n"
        out += f"  Command: {result['command']}\n"
        out += f"  Schedule: {result.get('schedule') or 'manual'}\n"
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
        command: New command.
        schedule: New schedule (empty string to clear).
        notify_user: New notification recipient.

    Returns:
        Confirmation with changes.
    """
    try:
        if not job_id or not job_id.strip():
            return "Error: job_id is required."
        return _update_job(
            job_id=job_id.strip(),
            updated_by=updated_by.strip().lower() if updated_by else "",
            status=status.strip() if status else "",
            name=name.strip() if name else "",
            command=command.strip() if command else "",
            schedule=schedule,
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
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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
