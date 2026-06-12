"""Timers — MCP/chat tools: set, list, and cancel short-duration timers.

Timers are in-memory countdowns that fire a notification to the requesting user
when they expire. Use them for sub-minute and short (< ~30 min) countdowns. For
anything tied to a wall-clock time or longer, use set_reminder instead.
"""

from __future__ import annotations

import os
import sys

# Keep the platform root importable whether this module is loaded as
# ``apps.timers.tools`` (the normal path) or, rarely, directly.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


async def start_timer(
    user_id: str,
    seconds: int = 0,
    minutes: int = 0,
    name: str = "",
) -> str:
    """Start a countdown timer that fires a notification to the user when it expires.

    Use this for short countdowns (seconds to a few minutes) like "30 second timer",
    "5 minute timer", "set a timer for 90 seconds for the eggs". The total duration
    is seconds + minutes*60. Always DO IT immediately — do not ask the user to
    confirm a timer.

    For wall-clock reminders ("remind me at 3pm", "tomorrow morning") use
    set_reminder instead. For anything longer than ~30 minutes prefer set_reminder
    because timers are in-memory and do not survive a restart.

    Args:
        user_id: Canonical user id of the person who asked for the timer
                 (e.g. "alice", "carol"). Required.
        seconds: Seconds component of the duration. Default 0.
        minutes: Minutes component of the duration. Default 0.
        name: Optional label (e.g. "eggs", "laundry", "pasta"). Used in the
              fire notification and in list_timers output.

    Returns:
        Confirmation with the timer id (tm-*) and total duration.
    """
    try:
        clean_user = (user_id or "").strip()
        if not clean_user:
            return "Error: user_id is required."

        total = int(seconds or 0) + int(minutes or 0) * 60
        if total <= 0:
            return "Error: timer duration must be greater than zero seconds."

        from data_layer.users import get_user
        if not get_user(clean_user.lower()):
            return f"Error: unknown user '{clean_user}'."

        from apps.timers import scheduler as timer_scheduler
        if timer_scheduler.is_shutting_down():
            return "Error: timer service is shutting down."

        record = await timer_scheduler.start_timer(
            user_id=clean_user,
            duration_seconds=total,
            name=(name or "").strip(),
        )

        label = record["name"] or "Timer"
        if total % 60 == 0 and total >= 60:
            mins = total // 60
            dur_text = f"{mins} minute{'s' if mins != 1 else ''}"
        else:
            dur_text = f"{total} second{'s' if total != 1 else ''}"
        return (
            f"Timer started (id: {record['id']}). "
            f"{label} — {dur_text}. Fires at {record['expires_at']}."
        )
    except Exception as e:
        return f"Error in start_timer: {e}"


def list_timers(user_id: str = "") -> str:
    """List active timers currently running in the background.

    Args:
        user_id: Optional canonical user id to filter by (e.g. "alice").
                 Leave empty to list all active timers across all users.

    Returns:
        Formatted list of active timers with their ids, names, and time
        remaining, or a message that none are active.
    """
    try:
        from apps.timers import store as timer_store

        clean = (user_id or "").strip().lower()
        records = timer_store.list_active(clean if clean else None)
        if not records:
            who = f" for {clean}" if clean else ""
            return f"No active timers{who}."

        lines = [f"Active timers ({len(records)}):"]
        for r in records:
            remaining = max(0, int(timer_store.seconds_remaining(r)))
            if remaining >= 60:
                rem_text = f"{remaining // 60}m {remaining % 60}s"
            else:
                rem_text = f"{remaining}s"
            label = r.get("name") or "Timer"
            lines.append(
                f"  [{r['id']}] {label} — {r['user_id']} — {rem_text} remaining "
                f"(of {r['duration_seconds']}s)"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_timers: {e}"


def cancel_timer(timer_id: str) -> str:
    """Cancel an active timer before it fires.

    Args:
        timer_id: The timer id to cancel (e.g. "tm-a1b2c3d4"). Required.

    Returns:
        Status message.
    """
    try:
        clean = (timer_id or "").strip()
        if not clean:
            return "Error: timer_id is required."

        from apps.timers import scheduler as timer_scheduler
        if timer_scheduler.cancel(clean):
            return f"Timer {clean} cancelled."
        return f"No active timer with id {clean}."
    except Exception as e:
        return f"Error in cancel_timer: {e}"
