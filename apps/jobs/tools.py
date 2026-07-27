"""Jobs — MCP tools.

Two tools used by the chat agent:

- ``get_jobs(status_filter="", created_by="")`` — list jobs
- ``update_job(job_id, ...)`` — modify a job (status / name / notify_user;
  ``schedule`` arg is deprecated and a no-op)

**Shell jobs were removed.** ``create_job`` and ``run_job`` used to create a job carrying a
free-form ``command`` string and execute it with ``shell=True``. The feature was unreachable
from end to end — the tools were chat-disabled, there was no REST or UI path to create one,
and ``shell`` had no dispatcher handler, so a shell job would have sat queued forever. What
remained was a latent arbitrary-execution surface and a bug that reported success for a
command it had never stored. Background work is submitted through ``app_platform.jobs``
``submit_job`` against a registered handler instead.

The legacy ``schedule=`` parameter is a deprecated no-op — the column was dropped in legacy
migration 063, and recurring work runs through the Schedules app.
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
    list_jobs as _list_jobs,
    update_job as _update_job,
    format_jobs as _format_jobs,
)


_logger = logging.getLogger(__name__)


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
    schedule: str = "",
    notify_user: str = "",
) -> str:
    """Update a job definition.

    Args:
        job_id: The job ID (e.g. "j-abc12345").
        updated_by: Who is making the update.
        status: New status: "active", "paused", "completed", "failed".
        name: New name.
        schedule: **Deprecated.** No-op — recurring work lives in the Schedules app.
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
            notify_user=notify_user.strip() if notify_user else "",
        )
    except Exception as e:
        return f"Error in update_job: {str(e)}"
