"""Reminders — MCP tools.

Six tools used by the chat agent:

- ``set_reminder(user_id, message, remind_at, rrule="")``
- ``get_reminders(user_id, include_inactive="false")``
- ``cancel_reminder_by_id(reminder_id)``
- ``modify_reminder_by_id(...)``
- ``set_nag(user_id, message, time_slot="")``
- ``snooze_reminder(reminder_id, duration)``

Ported from ``tools/reminder_tool.py`` for sub-chunk 7e. Only change
is the import path: the store helpers now live at
``apps.reminders.store``.
"""

from __future__ import annotations

import os
import sys
import re

# Make sure the platform root is on sys.path so this module is importable
# both as ``apps.reminders.tools`` and (rarely) directly.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from apps.reminders.store import (
    create_reminder,
    create_nag as _create_nag,
    list_reminders as _list_reminders,
    cancel_reminder as _cancel_reminder,
    modify_reminder as _modify_reminder,
    snooze_reminder as _snooze_reminder,
)


def set_reminder(
    user_id: str,
    message: str,
    remind_at: str,
    rrule: str = "",
) -> str:
    """Create a reminder for a user at a SPECIFIC date/time. Supports one-shot and recurring via RRULE.

    IMPORTANT: Do NOT use this for open-ended requests with no specific time.
    If the user says "don't let me forget", "nag me", "keep reminding me",
    "don't forget", or any request WITHOUT a specific date/time — use set_nag instead.
    This tool requires a concrete remind_at datetime.

    Args:
        user_id: Who this reminder is for (a person's name).
        message: The reminder text (what to remind them about).
        remind_at: When to first fire, as ISO datetime with timezone
                   (e.g. "2026-02-10T09:00:00-06:00"). For recurring reminders
                   this is also the dtstart that anchors the time of day.
        rrule: Optional RFC 5545 RRULE string for recurring reminders.
               Leave empty for a one-shot reminder. Examples:
                 "FREQ=DAILY"                          (every day)
                 "FREQ=WEEKLY;BYDAY=MO,WE,FR"          (Mon/Wed/Fri)
                 "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"     (every 2 weeks on Monday)
                 "FREQ=MONTHLY;BYMONTHDAY=1,15"         (1st and 15th of month)
                 "FREQ=MONTHLY;BYDAY=3TU"               (3rd Tuesday of month)
                 "FREQ=MONTHLY;BYDAY=-1FR"              (last Friday of month)
                 "FREQ=YEARLY"                          (once a year)
                 "FREQ=DAILY;UNTIL=20261231T235959"     (daily until end of 2026)

    Returns:
        Confirmation with reminder ID, or error message.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        if not message or not message.strip():
            return "Error: message is required."
        if not remind_at or not remind_at.strip():
            return "Error: remind_at is required (ISO datetime)."

        recurrence = rrule.strip() if rrule and rrule.strip() else None

        reminder = create_reminder(
            user_id=user_id.strip(),
            message=message.strip(),
            remind_at=remind_at.strip(),
            recurrence=recurrence,
        )

        result = f"Reminder set (ID: {reminder['id']}) for {reminder['user_id']}.\n"
        result += f"Next fire: {reminder['remind_at']}\n"
        result += f"Message: {reminder['message']}\n"
        if recurrence:
            result += f"Recurrence: {recurrence}\n"
        else:
            result += "Type: one-shot\n"

        return result

    except Exception as e:
        return f"Error in set_reminder: {str(e)}"


def get_reminders(user_id: str, include_inactive: str = "false") -> str:
    """List all reminders for a user.

    Args:
        user_id: Whose reminders to list.
        include_inactive: "true" to include cancelled/completed reminders.

    Returns:
        Formatted list of reminders.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."

        inc_inactive = include_inactive.strip().lower() == "true"
        reminders = _list_reminders(user_id.strip(), include_inactive=inc_inactive)

        if not reminders:
            status = "active or inactive" if inc_inactive else "active"
            return f"No {status} reminders found for {user_id.strip()}."

        lines = [f"Reminders for {user_id.strip()} ({len(reminders)} found):\n"]
        for r in reminders:
            status = "ACTIVE" if r.get("active", True) else "INACTIVE"
            rtype = "NAG" if r.get("nag") else ("RECURRING" if r.get("recurrence") else "ONE-SHOT")
            line = f"  [{r['id']}] ({status}, {rtype}) Next: {r['remind_at']}\n"
            line += f"    Message: {r['message']}\n"
            if r.get("nag"):
                last = r.get("last_nagged", "never")
                line += f"    Last nagged: {last}\n"
            elif r.get("recurrence"):
                line += f"    RRULE: {r['recurrence']}\n"
            lines.append(line)

        return "".join(lines)

    except Exception as e:
        return f"Error in get_reminders: {str(e)}"


def cancel_reminder_by_id(reminder_id: str) -> str:
    """Cancel an active reminder.

    Args:
        reminder_id: The reminder ID to cancel (e.g. "r-a1b2c3d4").

    Returns:
        Status message.
    """
    try:
        if not reminder_id or not reminder_id.strip():
            return "Error: reminder_id is required."
        return _cancel_reminder(reminder_id.strip())
    except Exception as e:
        return f"Error in cancel_reminder_by_id: {str(e)}"


def modify_reminder_by_id(
    reminder_id: str,
    message: str = "",
    remind_at: str = "",
    rrule: str = "",
    clear_recurrence: str = "false",
    time_slot: str = "",
    clear_time_slot: str = "false",
) -> str:
    """Modify an existing reminder or nag. YOU MUST CALL THIS TOOL to change a reminder.
    Only provide fields you want to change — leave others empty.

    Args:
        reminder_id: The reminder ID to modify (e.g. "r-dceecb54").
        message: New reminder text. Leave empty to keep current message.
        remind_at: New fire time as ISO datetime (e.g. "2026-02-07T10:30:00-06:00").
                   Leave empty to keep current time.
        rrule: New RRULE string for recurrence (e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR").
               Leave empty to keep current recurrence.
        clear_recurrence: "true" to remove recurrence and make one-shot.
        time_slot: For nags only. Change when the nag fires: "morning",
                   "afternoon", "evening", or "night". The nag will be
                   rescheduled into the new window automatically.
        clear_time_slot: "true" to remove time_slot (revert nag to any waking hour).

    Returns:
        Status message confirming the update with actual saved state.
    """
    try:
        if not reminder_id or not reminder_id.strip():
            return "Error: reminder_id is required."

        new_message = message.strip() if message and message.strip() else None
        new_remind_at = remind_at.strip() if remind_at and remind_at.strip() else None
        do_clear = clear_recurrence.strip().lower() == "true"
        do_clear_slot = clear_time_slot.strip().lower() == "true"

        new_recurrence = rrule.strip() if rrule and rrule.strip() else None
        new_time_slot = time_slot.strip().lower() if time_slot and time_slot.strip() else None

        return _modify_reminder(
            reminder_id=reminder_id.strip(),
            message=new_message,
            remind_at=new_remind_at,
            recurrence=new_recurrence,
            clear_recurrence=do_clear,
            time_slot=new_time_slot,
            clear_time_slot=do_clear_slot,
        )

    except Exception as e:
        return f"Error in modify_reminder_by_id: {str(e)}"


def set_nag(user_id: str, message: str, time_slot: str = "") -> str:
    """Create a nag — a low-ceremony persistent daily nudge until cancelled.

    USE THIS (not set_reminder) whenever the request has NO specific date or time.

    Nags are gentle daily pokes that say "hey, don't forget about this."
    They fire once per day at a random time. If a user has multiple nags,
    they are spread out so they don't cluster.

    Optionally scope to a time of day:
      - "morning"   → 7 AM – 12 PM
      - "afternoon" → 12 PM – 5 PM
      - "evening" / "night" → 5 PM – 9 PM
      - (empty)     → any time during waking hours (default)

    ALWAYS use this when the user says things like:
      - "don't let me forget to..."
      - "don't let X forget to..."
      - "nag me to..."
      - "nag me every morning to..."
      - "don't let me forget in the evening to..."
      - "keep reminding me to..."
      - "bug me about..."
      - "I need to remember to..." (no time given)
      - "remind me to X" (no specific time)

    The nag continues daily until cancelled with cancel_reminder_by_id.

    Args:
        user_id: Who to nag (a person's name).
        message: What to nag them about.
        time_slot: Optional. "morning", "afternoon", "evening", or "night".
                   Constrains the random nag time to that window.
                   Leave empty for any time during waking hours.

    Returns:
        Confirmation with nag ID.
    """
    try:
        if not user_id or not user_id.strip():
            return "Error: user_id is required."
        if not message or not message.strip():
            return "Error: message is required."

        ts = time_slot.strip().lower() if time_slot and time_slot.strip() else None

        nag = _create_nag(
            user_id=user_id.strip(),
            message=message.strip(),
            time_slot=ts,
        )

        slot_label = f" ({nag['time_slot']})" if nag.get("time_slot") else ""
        return (
            f"Nag set (ID: {nag['id']}) for {nag['user_id']}{slot_label}.\n"
            f"Message: {nag['message']}\n"
            f"First nag: {nag['remind_at']}\n"
            f"Will repeat daily at random{slot_label} times until cancelled."
        )

    except Exception as e:
        return f"Error in set_nag: {str(e)}"


def _parse_duration_to_minutes(duration: str) -> int | None:
    """Parse a human-readable duration string into minutes.

    Supports:
        "30m", "30min", "30 minutes"
        "1h", "1hr", "1 hour", "2 hours"
        "1h30m", "1 hour 30 minutes"
        "90" (bare number = minutes)
        "1.5h", "0.5 hours"
    """
    s = duration.strip().lower()

    # Bare number → minutes
    try:
        return max(1, int(float(s)))
    except (ValueError, TypeError):
        pass

    total = 0
    found = False

    # Hours
    h_match = re.search(r'(\d+\.?\d*)\s*(?:h|hr|hrs|hour|hours)', s)
    if h_match:
        total += float(h_match.group(1)) * 60
        found = True

    # Minutes
    m_match = re.search(r'(\d+\.?\d*)\s*(?:m|min|mins|minute|minutes)', s)
    if m_match:
        total += float(m_match.group(1))
        found = True

    if found:
        return max(1, int(total))

    return None


def snooze_reminder(
    reminder_id: str,
    duration: str,
) -> str:
    """Snooze a reminder or nag — creates a one-time follow-up that fires later.

    Use this when a user receives a reminder/nag and says something like:
    - "come back in an hour"
    - "remind me again in 30 minutes"
    - "snooze that for 2 hours"
    - "I'm busy, follow up later"

    This does NOT modify the original reminder. It creates a brand-new one-shot
    follow-up with the same message. The follow-up can itself be snoozed again.

    Args:
        reminder_id: The reminder ID to snooze (e.g. "r-a1b2c3d4").
                     This is the reminder that just fired.
        duration: How long until the follow-up fires.
                  Supports: "30m", "1h", "1h30m", "2 hours",
                  "90 minutes", "45", "1.5h", etc.
                  A bare number is treated as minutes.

    Returns:
        Confirmation with follow-up details.

    Ack: Snoozing reminder...
    """
    try:
        if not reminder_id or not reminder_id.strip():
            return "Error: reminder_id is required."
        if not duration or not duration.strip():
            return "Error: duration is required (e.g. '1h', '30m', '2 hours')."

        reminder_id = reminder_id.strip()
        if not reminder_id.startswith("r-"):
            return f"Error: '{reminder_id}' doesn't look like a reminder ID (expected r-*)."

        minutes = _parse_duration_to_minutes(duration)
        if minutes is None:
            return (
                f"Error: Couldn't parse duration '{duration}'. "
                f"Try formats like: '30m', '1h', '1h30m', '2 hours', '90 minutes', or just a number of minutes."
            )

        result = _snooze_reminder(reminder_id, minutes)
        if isinstance(result, str):
            return f"Error: {result}"

        # Format a nice duration string
        if minutes >= 60:
            h = minutes // 60
            m = minutes % 60
            dur_str = f"{h}h{m}m" if m else f"{h}h"
        else:
            dur_str = f"{minutes}m"

        return (
            f"Snoozed! Follow-up reminder created ({result['id']})\n"
            f"  Message: {result['message']}\n"
            f"  Fires in: {dur_str} ({result['remind_at']})\n"
            f"  Original: {reminder_id}\n"
            f"You can snooze the follow-up again when it fires."
        )

    except Exception as e:
        return f"Error in snooze_reminder: {str(e)}"
