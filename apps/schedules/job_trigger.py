"""Schedules — job-trigger loop.

When a schedule's ``next_due`` arrives and its ``linked_entity_type``
is ``"job"``, this loop submits the job to the job dispatcher and
completes the schedule (advancing ``next_due``).

Bridges Schedules and Jobs without either knowing about the other.
A schedule with ``linked_entity_type='job'`` stores the job_type in
``linked_entity_id``; ``job_config`` (jsonb) carries any per-occurrence
parameters.

Called from the job_runner loop (~30s, same cadence as the schedules
notifier).

Ported from ``schedule_job_trigger.py`` for sub-chunk 8e. Only change
is the data-layer import path: ``data_layer.schedules`` →
``apps.schedules.data``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE

CENTRAL_TZ = ZoneInfo(TIMEZONE)


async def check_schedule_jobs():
    """Check for due job-linked schedules and submit jobs for each."""
    try:
        from apps.schedules.data import get_due_schedules
        schedules = await asyncio.to_thread(
            get_due_schedules, days_ahead=0, exclude_reminder_backed=True,
        )
    except Exception as e:
        logger.error("SCHED_JOB: Failed to query due schedules: %s", e)
        return

    # Filter to job-linked schedules only
    job_schedules = [s for s in schedules if s.get("linked_entity_type") == "job"]
    if not job_schedules:
        return

    from job_dispatcher import submit_job, get_active_job_ids
    from apps.schedules.data import complete_schedule
    from data_layer.job_queue import count_running

    active_ids = get_active_job_ids()

    for sch in job_schedules:
        schedule_id = sch["id"]
        job_type = sch.get("linked_entity_id", "")
        title = sch.get("title", "")
        assigned_to = sch.get("assigned_to", "")

        if not job_type:
            logger.warning(
                "SCHED_JOB: Schedule %s has linked_entity_type='job' but no job_type in linked_entity_id",
                schedule_id,
            )
            continue

        # Dedup: skip if a job of this type is already running
        try:
            running = await asyncio.to_thread(count_running, job_type)
            if running > 0:
                logger.debug(
                    "SCHED_JOB: Skipping %s — %d %s job(s) already running",
                    schedule_id, running, job_type,
                )
                continue
        except Exception:
            pass

        # Submit the job (pass job_config if the schedule carries one)
        job_config = sch.get("job_config") or {}
        try:
            job = submit_job(
                job_type=job_type,
                name=f"Scheduled: {title or job_type}",
                created_by="scheduler",
                description=f"Auto-triggered by schedule {schedule_id}",
                config=job_config if job_config else None,
            )
            logger.info(
                "SCHED_JOB: Submitted %s job %s from schedule %s (%s)",
                job_type, job["id"], schedule_id, title,
            )
        except Exception as e:
            logger.error(
                "SCHED_JOB: Failed to submit %s job for schedule %s: %s",
                job_type, schedule_id, e,
            )
            continue

        # Complete the schedule (advances next_due)
        try:
            await asyncio.to_thread(
                complete_schedule, schedule_id,
                completed_by="scheduler",
                notes=f"Triggered job {job['id']}",
            )
            logger.info(
                "SCHED_JOB: Completed schedule %s, advanced to next occurrence",
                schedule_id,
            )
        except Exception as e:
            logger.error("SCHED_JOB: Failed to complete schedule %s: %s", schedule_id, e)
