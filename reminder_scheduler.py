"""
SkipperBot Reminder Scheduler
Background async loop that checks for due reminders every ~30 seconds.
Creates notification records for due reminders; actual delivery is handled
by the centralized notification_delivery module.
"""

import asyncio
from config import logger
from reminder_store import get_due_reminders, mark_delivered, assign_nag_times
from app_platform.notifications import create_notification


# How often to check for due reminders (seconds)
CHECK_INTERVAL = 30

# Graceful shutdown flag
_shutting_down = False

def request_shutdown():
    """Signal the reminder scheduler to stop processing."""
    global _shutting_down
    _shutting_down = True
    logger.info("REMINDER: Shutdown requested — no new reminders will be processed")


def process_due_reminder(reminder: dict):
    """Process a due reminder: create a notification record and advance recurrence.

    Actual delivery (Discord, Pushover, WebSocket, chat log) is handled by
    the centralized notification_delivery module later in the same cycle.
    """
    user_id = reminder["user_id"]
    message = reminder["message"]
    reminder_id = reminder["id"]

    is_nag = reminder.get("nag", False)
    prefix = "👋 Nag" if is_nag else "⏰ Reminder"

    # Determine delivery channel
    try:
        from tools.pushover_tool import is_pushover_user
        channel = "both" if is_pushover_user(user_id) else "discord"
    except Exception:
        channel = "discord"

    # Create notification record (delivered=False) — picked up by notification_delivery
    try:
        create_notification(
            recipient=user_id,
            message=f"{prefix}: {message}",
            source_type="nag" if is_nag else "reminder",
            source_id=reminder_id,
            channel=channel,
            delivered=False,
        )
        logger.info("REMINDER [%s]: Created notification for %s", reminder_id, user_id)
    except Exception as e:
        logger.error("REMINDER [%s]: Failed to create notification record: %s", reminder_id, str(e))

    # Mark as delivered (advances recurring or deactivates one-shot)
    mark_delivered(reminder_id)
    logger.info("REMINDER [%s]: Processed for %s (recurrence advanced)", reminder_id, user_id)


async def check_and_deliver():
    """Check for due reminders and deliver them, then check schedules."""
    try:
        # Assign random waking-hour times for any nags that need today's schedule
        assign_nag_times()
        due = get_due_reminders()
        if not due:
            pass
        else:
            logger.info("REMINDER: Found %d due reminder(s)", len(due))
            for reminder in due:
                try:
                    process_due_reminder(reminder)
                except Exception as e:
                    logger.error("REMINDER: Failed to process reminder %s: %s",
                                 reminder.get("id", "?"), str(e))
    except Exception as e:
        logger.error("REMINDER: Error checking due reminders: %s", str(e))

    # Check schedule notifications (upcoming + overdue) — creates notification records
    try:
        from schedule_notifier import check_schedule_notifications
        await check_schedule_notifications()
    except Exception as e:
        logger.error("SCHEDULE_NOTIF: Error in schedule notification check: %s", str(e))

    # Check to-do nudge notifications (weekly, per-user)
    try:
        from todo_nudge_notifier import check_todo_nudges
        await check_todo_nudges()
    except Exception as e:
        logger.error("TODO_NUDGE: Error in to-do nudge check: %s", str(e))

    # Run all registered nag providers (app-package daily nags)
    try:
        from nag_registry import run_all_nag_providers
        await run_all_nag_providers()
    except Exception as e:
        logger.error("NAG_REGISTRY: Error running nag providers: %s", str(e))

    # Deliver any pending notifications (schedule, todo nudge, or any other source)
    try:
        from apps.notifications.delivery import deliver_pending_notifications
        await deliver_pending_notifications()
    except Exception as e:
        logger.error("NOTIF_DELIVERY: Error delivering pending notifications: %s", str(e))



async def start_reminder_scheduler():
    """Run the reminder check loop forever. Start as an asyncio task."""
    logger.info("REMINDER: Scheduler started (checking every %ds)", CHECK_INTERVAL)
    while True:
        if _shutting_down:
            logger.info("REMINDER: Scheduler exiting — shutdown requested")
            return
        await check_and_deliver()
        await asyncio.sleep(CHECK_INTERVAL)
