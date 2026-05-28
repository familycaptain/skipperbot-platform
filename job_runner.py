"""Job Runner
==========
Dedicated background async loop that manages all scheduled and queued jobs:
  - Research jobs
  - Print jobs
  - Refine jobs
  - Project Manager daily cycle
  - (future job types)

Runs every 30 seconds, checks for pending work across all job types.
Separated from the reminder scheduler so each has a clear responsibility.
"""

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
