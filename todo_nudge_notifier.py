"""
To-Do Nudge Notifier
====================
Checks for users whose weekly to-do nudge is due and creates notification
records. Called from the reminder scheduler loop (~30s interval).

This module only creates notification records (delivered=False). Actual
delivery (Discord, Pushover, WebSocket, chat log) is handled by the
centralized notification_delivery module.

Nudge fires once per week on the user's configured nudge_day at nudge_time.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE
from notification_store import create_notification
from data_layer.db import fetch_one as _db_fetch_one

CENTRAL_TZ = ZoneInfo(TIMEZONE)


def _now():
    return datetime.now(CENTRAL_TZ)


def _has_nudge_today(user_id: str) -> bool:
    """Check if a to-do nudge was already created for this user today."""
    today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    row = _db_fetch_one(
        "SELECT 1 FROM notifications WHERE recipient = %s AND source_type = %s AND created_at >= %s LIMIT 1",
        (user_id, "todo_nudge", today_start),
    )
    return row is not None


async def check_todo_nudges():
    """Check all users' to-do configs and create nudge notifications as needed.

    Called every ~30 seconds from the reminder scheduler loop.
    Only creates a nudge if:
      - today's weekday matches the user's nudge_day
      - current time is at or past the user's nudge_time
      - nudge_enabled is True
      - the user's default to-do list has active items
      - no nudge was already sent today (dedup)
    """
    try:
        from apps.todo.data import get_all_configs
        from apps.todo.store import get_todo_items
    except Exception as e:
        logger.error("TODO_NUDGE: Failed to import todo data layer: %s", e)
        return

    try:
        configs = await asyncio.to_thread(get_all_configs)
    except Exception as e:
        logger.error("TODO_NUDGE: Failed to load configs: %s", e)
        return

    if not configs:
        return

    now = _now()
    today_name = now.strftime("%A").lower()  # e.g. "saturday"

    for cfg in configs:
        user_id = cfg["user_id"]

        if not cfg.get("nudge_enabled", True):
            continue
        if cfg.get("nudge_day", "saturday").lower() != today_name:
            continue
        if not cfg.get("default_list_id"):
            continue

        # Check nudge_time — only fire at or after the configured time
        nudge_time_str = cfg.get("nudge_time", "07:00")
        try:
            parts = nudge_time_str.split(":")
            nudge_hour, nudge_minute = int(parts[0]), int(parts[1])
            if now.hour < nudge_hour or (now.hour == nudge_hour and now.minute < nudge_minute):
                continue
        except (ValueError, IndexError):
            pass  # If time parsing fails, proceed with delivery

        # Dedup — only one nudge per user per day
        if _has_nudge_today(user_id):
            continue

        try:
            result = await asyncio.to_thread(get_todo_items, user_id)
            if not result or not result.get("items"):
                continue

            active = [i for i in result["items"] if not i.get("archived")]
            if not active:
                continue

            # Build nudge message
            top_items = active[:5]
            lines = [f"{i+1}. {item['text']}" for i, item in enumerate(top_items)]
            remaining = len(active) - len(top_items)

            msg = (
                f"☀️ **Your To-Do List** — here's what's on your plate when you have time:\n\n"
                + "\n".join(lines)
            )
            if remaining > 0:
                msg += f"\n...and {remaining} more"
            msg += f"\n\n_{len(active)} item{'s' if len(active) != 1 else ''} total_"

            # Determine delivery channel
            try:
                from tools.pushover_tool import is_pushover_user
                channel = "both" if is_pushover_user(user_id) else "discord"
            except Exception:
                channel = "discord"

            create_notification(
                recipient=user_id,
                message=msg,
                source_type="todo_nudge",
                source_id=cfg["default_list_id"],
                channel=channel,
                delivered=False,
            )
            logger.info("TODO_NUDGE: Created nudge notification for %s (%d items)", user_id, len(active))

        except Exception as e:
            logger.error("TODO_NUDGE: Failed to process nudge for %s: %s", user_id, e)
