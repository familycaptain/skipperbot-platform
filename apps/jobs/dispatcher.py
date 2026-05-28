"""Jobs — dispatcher engine.

The queue dispatcher: claims newly queued jobs, invokes the registered
handler for each ``job_type``, records progress + logs + output as the
handler runs, and finishes the job (complete / fail / cancelled).

Public surface (re-exported via the ``app_platform.jobs`` shim):

- ``register_handler(job_type, fn, max_concurrent=1, cancel_on_shutdown=True)``
- ``submit_job(...)``
- ``JobContext`` dataclass
- ``start_dispatcher()`` (launched from platform startup)
- ``request_shutdown()`` / ``is_shutting_down()``
- ``get_active_job_ids()``
- ``RequeueRequested`` exception for handler-driven requeue

Ported from ``job_dispatcher.py`` for sub-chunk 9e. Functionally
identical; only changes are routing data-layer calls through
``apps.jobs.data`` and the bare ``UPDATE`` for requeue through
``execute_in_schema``.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Callable, Awaitable

from config import logger, TIMEZONE
from app_platform.db import execute_in_schema
from apps.jobs.data import SCHEMA as _JOBS_SCHEMA

# Graceful shutdown flag
_shutting_down = False


def request_shutdown():
    """Signal the dispatcher to stop claiming new jobs."""
    global _shutting_down
    _shutting_down = True
    logger.info("JOB_DISPATCH: Shutdown requested — no new jobs will be claimed")


def is_shutting_down() -> bool:
    return _shutting_down


# Context-aware storage for current job_id (used by JobLogHandler).
# ContextVar is asyncio-safe: each Task gets its own value, so concurrent
# coroutines don't leak logs into unrelated jobs. asyncio.to_thread copies
# the context automatically.
_current_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_job_id", default=None,
)


class JobLogHandler(logging.Handler):
    """Logging handler that captures log lines into the job_logs DB table
    for whatever job is currently running in this task/thread."""

    def emit(self, record):
        job_id = _current_job_id.get(None)
        if not job_id:
            return
        try:
            from apps.jobs.data import append_log
            msg = self.format(record)
            append_log(job_id, record.levelname, msg)
        except Exception:
            pass  # never let log capture break the job


# Install the handler on the root logger so ALL log calls get captured
_job_log_handler = JobLogHandler()
_job_log_handler.setLevel(logging.INFO)
_job_log_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_job_log_handler)

CENTRAL_TZ = ZoneInfo(TIMEZONE)

# Check interval (seconds)
POLL_INTERVAL = 10


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

# Handler signature: async def handler(job: dict, ctx: JobContext) -> str
#   - job: the full job dict from the queue
#   - ctx: a JobContext with update_progress(), is_cancelled(), etc.
#   - returns: a result summary string

_handlers: dict[str, dict] = {}


def register_handler(
    job_type: str,
    handler_fn: Callable,
    max_concurrent: int = 1,
    cancel_on_shutdown: bool = True,
):
    """Register a handler function for a job type.

    Args:
        job_type: e.g. "research", "backup", "evolve_cycle"
        handler_fn: async def handler(job, ctx) -> str (or sync — auto-threaded)
        max_concurrent: max simultaneous jobs of this type (default 1)
        cancel_on_shutdown: if False, is_cancelled() ignores graceful
            shutdown — the job must finish before the process exits.
            Use for operations that must not be interrupted.
    """
    _handlers[job_type] = {
        "fn": handler_fn,
        "max_concurrent": max_concurrent,
        "cancel_on_shutdown": cancel_on_shutdown,
    }
    logger.info(
        "JOB_DISPATCH: Registered handler '%s' (max_concurrent=%d, cancel_on_shutdown=%s)",
        job_type, max_concurrent, cancel_on_shutdown,
    )


# ---------------------------------------------------------------------------
# Job context (passed to handlers)
# ---------------------------------------------------------------------------

class RequeueRequested(Exception):
    """Raised by a handler to request the job be re-queued instead of completed."""
    pass


class JobContext:
    """Context object passed to job handlers for progress/cancellation."""

    def __init__(self, job_id: str, cancel_on_shutdown: bool = True):
        self.job_id = job_id
        self._cancelled = False
        self._cancel_on_shutdown = cancel_on_shutdown

    def update_progress(self, pct: int, message: str = ""):
        """Update job progress (0-100) with optional message."""
        from apps.jobs.data import update_progress
        update_progress(self.job_id, pct, message)

    def update_output(self, **kwargs):
        """Merge key-value pairs into the job's output JSONB."""
        from apps.jobs.data import update_output
        update_output(self.job_id, kwargs)

    def log(self, message: str, level: str = "INFO"):
        """Write a log line directly to the job's log."""
        from apps.jobs.data import append_log
        append_log(self.job_id, level, message)

    def is_cancelled(self) -> bool:
        """Check if this job has been cancelled OR a graceful shutdown is
        in progress. Handlers should check this periodically and exit
        gracefully if True.

        Jobs registered with cancel_on_shutdown=False ignore the global
        shutdown flag — only explicit per-job cancellation stops them.
        """
        if self._cancelled:
            return True
        if _shutting_down and self._cancel_on_shutdown:
            self._cancelled = True
            return True
        from apps.jobs.data import is_cancelled
        self._cancelled = is_cancelled(self.job_id)
        return self._cancelled


# ---------------------------------------------------------------------------
# Submit a job (public API)
# ---------------------------------------------------------------------------

def submit_job(
    job_type: str,
    name: str = "",
    config: dict | None = None,
    created_by: str = "",
    notify_user: str = "",
    description: str = "",
    schedule_expr: dict | None = None,
    scheduled_for: str = "",
    max_retries: int = 0,
    parent_job_id: str = "",
) -> dict:
    """Submit a new job to the queue.

    Returns the created job dict.
    """
    from apps.jobs.data import create_job

    job_id = f"j-{uuid.uuid4().hex[:8]}"
    if not name:
        name = f"{job_type}: {job_id}"

    job = create_job(
        job_id=job_id,
        name=name,
        job_type=job_type,
        created_by=created_by,
        description=description,
        schedule_expr=schedule_expr,
        scheduled_for=scheduled_for,
        notify_user=notify_user or created_by,
        config=config,
        parent_job_id=parent_job_id,
        max_retries=max_retries,
    )
    logger.info("JOB_DISPATCH: Submitted %s job %s: %s", job_type, job_id, name)
    return job


# ---------------------------------------------------------------------------
# Tracking active tasks
# ---------------------------------------------------------------------------

_active_tasks: dict[str, asyncio.Task] = {}


def get_active_job_ids() -> list[str]:
    """Get IDs of jobs currently being executed by this worker."""
    return [jid for jid, t in _active_tasks.items() if not t.done()]


# ---------------------------------------------------------------------------
# Worker: execute a single job
# ---------------------------------------------------------------------------

async def _execute_job(job: dict, handler_info: dict):
    """Execute a single job using its registered handler."""
    job_id = job["id"]
    job_type = job["job_type"]
    handler_fn = handler_info["fn"]
    cancel_on_shutdown = handler_info.get("cancel_on_shutdown", True)
    ctx = JobContext(job_id, cancel_on_shutdown=cancel_on_shutdown)

    logger.info("JOB_DISPATCH: Starting %s [%s] — %s", job_type, job_id, job["name"])

    token = _current_job_id.set(job_id)
    try:
        # Run the handler
        if asyncio.iscoroutinefunction(handler_fn):
            result = await handler_fn(job, ctx)
        else:
            # Sync handler — run in thread pool
            # asyncio.to_thread copies the context, so _current_job_id is
            # available in the worker thread automatically.
            result = await asyncio.to_thread(handler_fn, job, ctx)

        result_str = str(result or "Done")[:500]

        # Check if cancelled during execution
        if ctx.is_cancelled():
            logger.info("JOB_DISPATCH: %s [%s] was cancelled during execution", job_type, job_id)
            return

        # Mark complete
        from apps.jobs.data import complete_job
        complete_job(job_id, result=result_str)
        logger.info("JOB_DISPATCH: Completed %s [%s] — %s", job_type, job_id, result_str[:80])

        # Send notification
        await _notify_completion(job, result_str, success=True)

    except RequeueRequested as rq:
        logger.info("JOB_DISPATCH: Re-queuing %s [%s] — %s", job_type, job_id, rq)
        execute_in_schema(
            _JOBS_SCHEMA,
            "UPDATE jobs SET status = 'queued', started_at = NULL, claimed_by = '' "
            "WHERE id = %s",
            (job_id,),
        )

    except Exception as e:
        error_str = str(e)[:500]
        logger.error(
            "JOB_DISPATCH: Failed %s [%s] — %s", job_type, job_id, error_str,
            exc_info=True,
        )
        from apps.jobs.data import fail_job
        fail_job(job_id, error=error_str)
        await _notify_completion(job, error_str, success=False)

    finally:
        _current_job_id.reset(token)
        _active_tasks.pop(job_id, None)


async def _notify_completion(job: dict, result: str, success: bool):
    """Send a notification on job completion/failure.

    On failure, also sends an actual Discord DM to notify_user.
    """
    # Skip notifications for evolve internal jobs (too noisy — 100+ per cycle)
    job_type = job.get("job_type", "")
    if job_type in ("evolve_unit", "evolve_phase"):
        return

    notify_user = job.get("notify_user") or job.get("created_by")
    if not notify_user:
        return
    try:
        from app_platform.notifications import create_notification
        status = "completed" if success else "FAILED"
        msg = f"Job '{job['name']}' {status}: {result[:200]}"
        create_notification(
            recipient=notify_user,
            message=msg,
            source_type="job",
            source_id=job["id"],
            channel="discord",
            delivered=True,
        )

        # Send a real Discord DM on failure
        if not success:
            try:
                from discord_bot import send_dm
                dm_text = (
                    f"**Job Failed:** {job['name']}\n"
                    f"**Type:** {job.get('job_type', '?')}\n"
                    f"**Error:** {result[:300]}"
                )
                await send_dm(notify_user, dm_text)
            except Exception as dm_err:
                logger.error("JOB_DISPATCH: Discord DM failed for %s: %s", job["id"], dm_err)

    except Exception as e:
        logger.error("JOB_DISPATCH: Notification failed for %s: %s", job["id"], e)


# ---------------------------------------------------------------------------
# Main dispatcher loop
# ---------------------------------------------------------------------------

async def _dispatch_cycle():
    """Single dispatch cycle: claim queued jobs and execute."""
    if _shutting_down:
        return

    from apps.jobs.data import claim_queued_jobs, count_running

    # For each registered handler type, claim and execute up to max_concurrent
    for job_type, info in _handlers.items():
        try:
            max_c = info["max_concurrent"]
            running = count_running(job_type)
            slots = max_c - running
            if slots <= 0:
                continue

            claimed = claim_queued_jobs(job_type=job_type, limit=slots)
            for job in claimed:
                task = asyncio.create_task(_execute_job(job, info))
                _active_tasks[job["id"]] = task

        except Exception as e:
            logger.error("JOB_DISPATCH: Error claiming %s jobs: %s", job_type, e)


async def start_dispatcher():
    """Start the job dispatcher loop. Call once at application startup."""
    # Clean up jobs that were running when the agent last shut down
    from apps.jobs.data import fail_stale_running
    stale = await asyncio.to_thread(fail_stale_running)
    if stale:
        logger.info(
            "JOB_DISPATCH: Cleaned up %d stale running jobs from previous session",
            stale,
        )

    logger.info(
        "JOB_DISPATCH: Started (polling every %ds, %d handler types registered)",
        POLL_INTERVAL, len(_handlers),
    )
    for jtype, info in _handlers.items():
        logger.info("JOB_DISPATCH:   %s (max_concurrent=%d)", jtype, info["max_concurrent"])

    while True:
        if _shutting_down:
            logger.info("JOB_DISPATCH: Dispatcher exiting — shutdown requested")
            return
        try:
            await _dispatch_cycle()
        except Exception as e:
            logger.error("JOB_DISPATCH: Cycle error: %s", e, exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)
