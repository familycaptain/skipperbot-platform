"""Jobs — runner loop.

Polls per-runner handlers (research, print, refine, schedule-driven)
every ~30 seconds. This is separate from the dispatcher loop (which
handles registered job_types via ``register_handler``) — the runner
exists for legacy job types whose modules still expose a
``check_and_run_*`` async function.

Ported from ``job_runner.py`` for sub-chunk 9e. Only change is the
schedules-side import path (``schedule_job_trigger`` already moved
to ``apps.schedules.job_trigger`` in Chunk 8).
"""

from __future__ import annotations

import asyncio
from config import logger


# How often to check for pending jobs (seconds)
CHECK_INTERVAL = 30


async def check_and_run_jobs():
    """Single pass: check all job types for pending work."""

    # Research jobs
    try:
        from research_runner import check_and_run_research
        await check_and_run_research()
    except Exception as e:
        logger.error("JOB_RUNNER: Error checking research jobs: %s", str(e))

    # Print jobs
    try:
        from print_runner import check_and_run_print_jobs
        await check_and_run_print_jobs()
    except Exception as e:
        logger.error("JOB_RUNNER: Error checking print jobs: %s", str(e))

    # Refine jobs
    try:
        from research_runner import check_and_run_refine_jobs
        await check_and_run_refine_jobs()
    except Exception as e:
        logger.error("JOB_RUNNER: Error checking refine jobs: %s", str(e))

    # Schedule-triggered jobs (PM, future automation, etc.)
    try:
        from apps.schedules.job_trigger import check_schedule_jobs
        await check_schedule_jobs()
    except Exception as e:
        logger.error("JOB_RUNNER: Error checking schedule jobs: %s", str(e))


async def start_job_runner():
    """Run the job check loop forever. Start as an asyncio task."""
    logger.info("JOB_RUNNER: Started (checking every %ds)", CHECK_INTERVAL)
    while True:
        await check_and_run_jobs()
        await asyncio.sleep(CHECK_INTERVAL)
