"""
Schedule Notifier
=================
Checks for upcoming and overdue schedules and creates notification entities.
Called from the reminder scheduler loop (~30s interval).

This module only creates notification records (delivered=False). Actual
delivery (Discord, Pushover, WebSocket, chat log) is handled by the
centralized notification_delivery module.

Two notification types:
  - UPCOMING: next_due is within reminder_mins — fires once per occurrence
  - OVERDUE:  next_due has passed — fires once per day
"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE, NAG_WAKE_HOUR, NAG_SLEEP_HOUR
from app_platform.notifications import create_notification
from data_layer.db import fetch_one as _db_fetch_one

CENTRAL_TZ = ZoneInfo(TIMEZONE)


# ---------------------------------------------------------------------------
# Schedule claim registry — app packages claim ownership of notifications
# for schedules with specific linked_entity_types.
# ---------------------------------------------------------------------------

_claimed_entity_types: set[str] = set()


def register_schedule_claim(linked_entity_type: str):
    """Claim ownership of schedule notifications for a linked_entity_type.

    schedule_notifier will skip schedules with this linked_entity_type.
    The claiming app is responsible for its own notifications.
    """
    _claimed_entity_types.add(linked_entity_type)
    logger.info("SCHEDULE_NOTIF: App claimed notifications for linked_entity_type='%s'", linked_entity_type)


def _now():
    return datetime.now(CENTRAL_TZ)


def _has_recent_notification(schedule_id: str, hours: int = 12) -> bool:
    """Check if a notification was already created for this schedule recently."""
    cutoff = _now() - timedelta(hours=hours)
    row = _db_fetch_one(
        "SELECT 1 FROM notifications WHERE source_id = %s AND source_type = %s AND created_at >= %s LIMIT 1",
        (schedule_id, "schedule", cutoff),
    )
    return row is not None


def _has_overdue_notification_today(schedule_id: str) -> bool:
    """Check if an overdue notification was already created today."""
    today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    row = _db_fetch_one(
        "SELECT 1 FROM notifications WHERE source_id = %s AND source_type = %s AND created_at >= %s LIMIT 1",
        (schedule_id, "schedule_overdue", today_start),
    )
    return row is not None


async def check_schedule_notifications():
    """Check all active schedules and create notifications as needed.

    Called every ~30 seconds from the reminder scheduler loop.
    Creates notification records; delivery is handled separately.
    """
    try:
        from data_layer.schedules import get_due_schedules
        # Get schedules due within 7 days (covers upcoming + overdue)
        schedules = await asyncio.to_thread(get_due_schedules, days_ahead=7, exclude_reminder_backed=True)
    except Exception as e:
        logger.error("SCHEDULE_NOTIF: Failed to query due schedules: %s", e)
        return

    if not schedules:
        return

    now = _now()

    for sch in schedules:
        try:
            schedule_id = sch["id"]
            title = sch["title"]
            assigned_to = sch.get("assigned_to", "")
            next_due_str = sch.get("next_due")
            reminder_mins = sch.get("reminder_mins", 60)
            notify_channel = sch.get("notify_channel", "both")

            if not next_due_str or not assigned_to or notify_channel == "none":
                continue

            # Skip schedules claimed by an app package
            linked_type = sch.get("linked_entity_type") or ""
            if linked_type in _claimed_entity_types:
                continue

            next_due = datetime.fromisoformat(next_due_str)
            delta = next_due - now
            minutes_until = delta.total_seconds() / 60

            if minutes_until < 0:
                # OVERDUE — create notification once per day
                _handle_overdue(sch, schedule_id, title, assigned_to, next_due, notify_channel)
            elif minutes_until <= reminder_mins:
                # UPCOMING — create notification once per occurrence
                _handle_upcoming(sch, schedule_id, title, assigned_to, next_due, minutes_until, notify_channel)

        except Exception as e:
            logger.error("SCHEDULE_NOTIF: Error processing schedule %s: %s",
                         sch.get("id", "?"), e, exc_info=True)


def _handle_upcoming(sch, schedule_id, title, assigned_to, next_due, minutes_until, notify_channel):
    """Create an upcoming schedule notification if not already created."""
    if _has_recent_notification(schedule_id, hours=12):
        return

    time_str = next_due.strftime("%I:%M %p").lstrip("0") if next_due.hour or next_due.minute else ""
    if minutes_until < 60:
        when = f"in {int(minutes_until)} min"
    else:
        hours = int(minutes_until / 60)
        when = f"in ~{hours}h"

    message = f"📋 Upcoming: {title} — due {when}"
    if time_str:
        message += f" ({time_str})"

    channel = "both" if notify_channel == "both" else notify_channel
    create_notification(
        recipient=assigned_to,
        message=message,
        source_type="schedule",
        source_id=schedule_id,
        channel=channel,
        delivered=False,
    )
    logger.info("SCHEDULE_NOTIF: Created upcoming notification for %s → %s", schedule_id, assigned_to)


def _nag_time_for_today(schedule_id: str) -> datetime:
    """Compute a deterministic random time during waking hours for today.

    Uses hash(schedule_id + date) so the time is stable throughout the day
    but varies day-to-day — same approach as reminder nag system.
    """
    today = _now().date()
    window_start = NAG_WAKE_HOUR * 60
    window_end = NAG_SLEEP_HOUR * 60
    total_minutes = window_end - window_start

    seed = hashlib.md5(f"{schedule_id}:{today.isoformat()}".encode()).hexdigest()
    random_offset = int(seed, 16) % max(total_minutes, 1)
    fire_minute = window_start + random_offset

    return datetime(
        today.year, today.month, today.day,
        fire_minute // 60, fire_minute % 60,
        tzinfo=CENTRAL_TZ,
    )


def _handle_overdue(sch, schedule_id, title, assigned_to, next_due, notify_channel):
    """Create an overdue notification at a random waking hour if not already created today."""
    if _has_overdue_notification_today(schedule_id):
        return

    # Wait for the random nag time before firing
    nag_time = _nag_time_for_today(schedule_id)
    if _now() < nag_time:
        return

    overdue_delta = _now() - next_due
    if overdue_delta.days > 0:
        when = f"{overdue_delta.days}d overdue"
    else:
        hours = int(overdue_delta.total_seconds() / 3600)
        when = f"{hours}h overdue" if hours > 0 else "overdue"

    message = f"⚠️ Overdue: {title} — {when}"

    channel = "both" if notify_channel == "both" else notify_channel
    create_notification(
        recipient=assigned_to,
        message=message,
        source_type="schedule_overdue",
        source_id=schedule_id,
        channel=channel,
        delivered=False,
    )
    logger.info("SCHEDULE_NOTIF: Created overdue notification for %s → %s (%s)", schedule_id, assigned_to, when)
