"""
SkipperBot Timer Scheduler
==========================
One asyncio.Task per active timer. Each task awaits asyncio.sleep(duration),
then creates a notification record and triggers immediate delivery (so
sub-minute timers don't wait for the 30-second reminder loop).

Cancellation: cancel the task. The task removes itself from the registry
in a finally block.

Graceful shutdown: shutdown_all_timers() cancels every active task and
waits for them to finish unwinding. No expired timers fire after shutdown
begins.
"""

import asyncio

from config import logger
import timer_store
from notification_store import create_notification

_shutting_down = False


def is_shutting_down() -> bool:
    return _shutting_down


async def start_timer(user_id: str, duration_seconds: int, name: str = "") -> dict:
    """Create and schedule a new timer. Returns the registered timer record.

    Caller is responsible for validating user_id and duration.
    """
    if _shutting_down:
        raise RuntimeError("Timer scheduler is shutting down")

    timer_id = timer_store.new_timer_id()
    clean_name = (name or "").strip()
    clean_user = user_id.lower().strip()

    # Create the task first so we can register it
    task = asyncio.create_task(
        _run_timer(timer_id, clean_user, duration_seconds, clean_name),
        name=f"timer:{timer_id}",
    )
    record = timer_store.register(
        timer_id=timer_id,
        user_id=clean_user,
        name=clean_name,
        duration_seconds=duration_seconds,
        task=task,
    )
    logger.info(
        "TIMER [%s]: Started for %s — %ds%s",
        timer_id, clean_user, duration_seconds,
        f" ({clean_name})" if clean_name else "",
    )
    return record


async def _run_timer(timer_id: str, user_id: str, duration_seconds: int, name: str):
    """Body of a single timer task: sleep, then fire."""
    try:
        await asyncio.sleep(duration_seconds)
    except asyncio.CancelledError:
        logger.info("TIMER [%s]: Cancelled before expiry", timer_id)
        timer_store.pop(timer_id)
        raise

    # Fired naturally — create notification and deliver immediately.
    try:
        label = name if name else "Timer"
        # Friendly duration phrasing
        if duration_seconds % 60 == 0 and duration_seconds >= 60:
            mins = duration_seconds // 60
            dur_text = f"{mins} minute{'s' if mins != 1 else ''}"
        else:
            dur_text = f"{duration_seconds} second{'s' if duration_seconds != 1 else ''}"
        message = f"⏱️ Timer done: {label} ({dur_text})"

        create_notification(
            recipient=user_id,
            message=message,
            source_type="timer",
            source_id=timer_id,
            channel="all",
            delivered=False,
        )
    except Exception as e:
        logger.error("TIMER [%s]: Failed to create notification: %s", timer_id, e)
    finally:
        # Remove from registry whether or not the notification succeeded.
        timer_store.pop(timer_id)

    # Trigger immediate delivery so the user hears about the expiry now,
    # rather than waiting up to 30s for the reminder loop's tick.
    try:
        from notification_delivery import deliver_pending_notifications
        await deliver_pending_notifications()
    except Exception as e:
        logger.error("TIMER [%s]: Immediate delivery failed: %s", timer_id, e)


def cancel(timer_id: str) -> bool:
    """Cancel an active timer. Returns True if a timer was cancelled."""
    record = timer_store.get(timer_id)
    if not record:
        return False
    task = record.get("task")
    # Remove from store first so any concurrent listing sees it gone.
    timer_store.pop(timer_id)
    if task and not task.done():
        task.cancel()
    logger.info("TIMER [%s]: Cancelled by request", timer_id)
    return True


async def shutdown_all_timers():
    """Cancel every active timer and wait for tasks to finish unwinding.

    Called from the FastAPI lifespan shutdown. After this returns, no
    pending timer can fire — even ones that were milliseconds from expiry.
    """
    global _shutting_down
    _shutting_down = True

    records = timer_store.all_records()
    if not records:
        logger.info("TIMER: Shutdown — no active timers")
        return

    logger.info("TIMER: Shutdown — cancelling %d active timer(s)", len(records))
    tasks = [r["task"] for r in records if r.get("task")]
    for t in tasks:
        if not t.done():
            t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    timer_store.clear()
    logger.info("TIMER: Shutdown complete")
