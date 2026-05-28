"""Reminders — business logic.

The main public entry points:

- ``create_reminder(...)`` — used by chat tools and other apps
  (via the ``app_platform.reminders`` shim).
- ``create_nag(...)`` — daily-nag-until-acknowledged variant.
- ``list_reminders(user_id, include_inactive=False)`` — desktop UI feed.
- ``cancel_reminder(reminder_id)`` / ``modify_reminder(...)`` — edits.
- ``snooze_reminder(reminder_id, minutes)`` — push to a later time.
- ``get_due_reminders()`` / ``mark_delivered(reminder_id)`` — used by
  the scheduler loop.

Plus several internal helpers for RRULE → schedule parameter mapping,
nag-time selection, and recurrence iteration.

Ported from ``reminder_store.py`` for sub-chunk 7c-part-2. Functionally
identical; only difference is routing all persistence through
``apps.reminders.data`` instead of ``data_layer.reminders``. Schedule
integration (``data_layer.schedules``) is left untouched here — the
``schedules`` app is still pending packaging in a later chunk.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from auto_memory import log_entity_change
from app_platform.memory import digest_record
from config import NAG_WAKE_HOUR, NAG_SLEEP_HOUR, NAG_SLOTS, TIMEZONE
from apps.reminders import data as _dl_rem
import data_layer.schedules as _dl_sched  # platform-side; schedules app not yet packaged


_REMINDER_HINT = (
    "Focus on: who the reminder is for, the reminder message, when it fires (remind_at), "
    "whether it repeats (recurrence rule), and whether it is a daily nag reminder."
)

# Module-local timezone for ISO timestamps. Mirrors the pattern used by
# the other store modules (goals, lists, notifications). The name is
# historical; the value reflects whatever the TIMEZONE env var points to.
CENTRAL_TZ = ZoneInfo(TIMEZONE)

# RRULE day abbreviation → schedule day name
# Mapping for converting old dict-format recurrence to RRULE strings
_DAY_ABBR = {
    "monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH",
    "friday": "FR", "saturday": "SA", "sunday": "SU",
}
_FREQ_MAP = {
    "minutely": "MINUTELY", "hourly": "HOURLY", "daily": "DAILY",
    "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY",
}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_reminders() -> list[dict]:
    return _dl_rem.get_all_reminders()


def _save_reminders(reminders: list[dict]):
    _dl_rem.save_all_reminders(reminders)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_reminder(
    user_id: str,
    message: str,
    remind_at: str,
    recurrence: dict | None = None,
) -> dict:
    """Create a new reminder.

    Args:
        user_id: Who this reminder is for (e.g. "alice").
        message: The reminder text.
        remind_at: ISO datetime string for when to fire (first occurrence).
        recurrence: Optional RRULE string (RFC 5545) for recurring reminders.
                    Examples:
                      "FREQ=WEEKLY;BYDAY=MO,WE,FR"  (every Mon/Wed/Fri)
                      "FREQ=MONTHLY;BYMONTHDAY=1,15" (1st and 15th)
                      "FREQ=MONTHLY;BYDAY=3TU"       (3rd Tuesday)
                      "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO" (every 2 weeks on Mon)
                      "FREQ=DAILY;UNTIL=20261231T235959" (daily until Dec 31)
                    The time of day comes from remind_at (dtstart).
                    Can also accept the old dict format for backward compat.

    Returns:
        The created reminder dict.
    """
    reminders = _load_reminders()

    now = datetime.now(CENTRAL_TZ)

    # Normalize recurrence: convert old dict format to RRULE string
    rrule_str = None
    if recurrence:
        if isinstance(recurrence, dict):
            rrule_str = _dict_to_rrule(recurrence)
        elif isinstance(recurrence, str):
            rrule_str = recurrence.strip()

    reminder = {
        "id": f"r-{uuid.uuid4().hex[:8]}",
        "user_id": user_id.lower().strip(),
        "message": message,
        "remind_at": remind_at,
        "created_at": now.isoformat(),
        "recurrence": rrule_str,
        "active": True,
        "sort_order": _dl_rem.next_sort_order(),
    }

    # Auto-create a backing schedule for recurring reminders
    if rrule_str:
        try:
            sched_params = _rrule_to_schedule_params(rrule_str, remind_at)
            sch = _dl_sched.create_schedule(
                title=message[:120],
                created_by=user_id.lower().strip(),
                category="general",
                assigned_to=user_id.lower().strip(),
                recurrence_type=sched_params["recurrence_type"],
                recurrence_rule=sched_params["recurrence_rule"],
                time_of_day=sched_params["time_of_day"],
                linked_entity_id=reminder["id"],
                linked_entity_type="reminder",
                reminder_mins=0,
                notify_channel="none",
            )
            if sch:
                reminder["schedule_id"] = sch["id"]
                # Sync remind_at from schedule's next_due
                if sch.get("next_due"):
                    reminder["remind_at"] = sch["next_due"]
        except Exception as e:
            import logging
            logging.getLogger("skipperbot").warning(
                "Failed to create backing schedule for reminder %s: %s",
                reminder["id"], e,
            )

    reminders.append(reminder)
    _save_reminders(reminders)

    log_entity_change("created", reminder["id"], "reminder",
                      f"For {user_id}: {message[:80]} at {remind_at}",
                      by=user_id)
    digest_record(app_id="reminders", entity_type="reminder", action="created",
                  entity_id=reminder["id"], record=reminder,
                  by=user_id, context_hint=_REMINDER_HINT)
    return reminder


def create_nag(user_id: str, message: str, time_slot: str | None = None) -> dict:
    """Create a nag reminder — fires once daily at a random time.

    Args:
        user_id: Who to nag (e.g. "alice").
        message: What to nag them about.
        time_slot: Optional time-of-day scope: "morning", "afternoon",
                   "evening", or "night". Constrains the random fire time
                   to that window. None = any time during waking hours.

    Returns:
        The created nag reminder dict.
    """
    # Normalize time_slot
    if time_slot:
        time_slot = time_slot.strip().lower()
        if time_slot not in NAG_SLOTS:
            time_slot = None  # fall back to full waking hours

    reminders = _load_reminders()
    now = datetime.now(CENTRAL_TZ)
    today = now.date()

    nag_id = f"r-{uuid.uuid4().hex[:8]}"

    # Count existing active nags for this user (within same time_slot) to assign a slot
    user_nags = [r for r in reminders if r.get("nag") and r.get("active", True)
                 and r["user_id"] == user_id.lower().strip()
                 and r.get("time_slot") == time_slot]
    total_slots = len(user_nags) + 1  # +1 for the new one
    slot_index = len(user_nags)

    # Pick today's random time if still within window, otherwise tomorrow
    fire_time = _nag_time_for_date(nag_id, today, slot_index, total_slots,
                                   time_slot=time_slot)
    if fire_time <= now:
        tomorrow = today + timedelta(days=1)
        fire_time = _nag_time_for_date(nag_id, tomorrow, slot_index, total_slots,
                                       time_slot=time_slot)

    nag = {
        "id": nag_id,
        "user_id": user_id.lower().strip(),
        "message": message,
        "remind_at": fire_time.isoformat(),
        "created_at": now.isoformat(),
        "recurrence": None,
        "active": True,
        "nag": True,
        "last_nagged": "",
        "time_slot": time_slot or "",
        "sort_order": _dl_rem.next_sort_order(),
    }

    reminders.append(nag)
    _save_reminders(reminders)

    slot_label = f" ({time_slot})" if time_slot else ""
    log_entity_change("created", nag_id, "nag",
                      f"For {user_id}{slot_label}: {message[:80]}",
                      by=user_id)
    digest_record(app_id="reminders", entity_type="reminder", action="created",
                  entity_id=nag_id, record=nag,
                  by=user_id, context_hint=_REMINDER_HINT)
    return nag


def assign_nag_times():
    """Re-assign random times for all active nags that haven't fired today.

    Called by the scheduler on each tick. Groups nags by user + time_slot
    so that nags within the same slot are spread across that window.
    """
    reminders = _load_reminders()
    today = datetime.now(CENTRAL_TZ).date()
    changed = False

    # Group active nags by (user_id, time_slot) for proper slot spreading
    groups: dict[tuple[str, str | None], list[dict]] = {}
    for r in reminders:
        if r.get("nag") and r.get("active", True):
            key = (r["user_id"], r.get("time_slot"))
            groups.setdefault(key, []).append(r)

    for (uid, ts), nags in groups.items():
        total = len(nags)
        for idx, nag in enumerate(nags):
            last = nag.get("last_nagged")
            if last == today.isoformat():
                continue  # already nagged today
            # Check if remind_at is already set for today
            try:
                current_fire = datetime.fromisoformat(nag["remind_at"]).date()
                if current_fire == today:
                    continue  # already has a time for today
            except (ValueError, KeyError):
                pass
            # Assign a new random time for today — but only if it's still in the future
            new_time = _nag_time_for_date(nag["id"], today, idx, total,
                                          time_slot=nag.get("time_slot"))
            if new_time > datetime.now(CENTRAL_TZ):
                nag["remind_at"] = new_time.isoformat()
                changed = True

    if changed:
        _save_reminders(reminders)


def _nag_time_for_date(
    nag_id: str, target_date: date, slot_index: int = 0, total_slots: int = 1,
    time_slot: str | None = None,
) -> datetime:
    """Compute a deterministic random time during waking hours for a nag.

    Divides the available window into slots (one per nag for this user) and
    picks a random minute within the assigned slot. Uses hash(nag_id + date)
    so the time is stable throughout the day but varies day-to-day.

    Args:
        time_slot: Optional "morning", "afternoon", "evening", or "night".
                   Constrains the random time to that part of the day.
                   None = full waking hours (default).
    """
    if time_slot and time_slot in NAG_SLOTS:
        start_hour, end_hour = NAG_SLOTS[time_slot]
        window_start = start_hour * 60
        window_end = end_hour * 60
    else:
        window_start = NAG_WAKE_HOUR * 60
        window_end = NAG_SLEEP_HOUR * 60

    total_minutes = window_end - window_start

    # Divide window into slots; add padding so nags don't fire at edges
    slot_size = total_minutes // max(total_slots, 1)
    slot_start = window_start + (slot_index * slot_size)

    # Deterministic random offset within the slot
    seed = hashlib.md5(f"{nag_id}:{target_date.isoformat()}".encode()).hexdigest()
    random_offset = int(seed, 16) % max(slot_size, 1)
    fire_minute = slot_start + random_offset

    # Clamp to window
    fire_minute = max(window_start, min(fire_minute, window_end - 1))

    return datetime(
        target_date.year, target_date.month, target_date.day,
        fire_minute // 60, fire_minute % 60,
        tzinfo=CENTRAL_TZ,
    )


def list_reminders(user_id: str, include_inactive: bool = False) -> list[dict]:
    """List reminders for a user.

    Args:
        user_id: Whose reminders to list.
        include_inactive: If True, include delivered/cancelled reminders.

    Returns:
        List of reminder dicts.
    """
    reminders = _load_reminders()
    result = []
    for r in reminders:
        if r["user_id"] != user_id.lower().strip():
            continue
        if not include_inactive and not r.get("active", True):
            continue
        result.append(r)
    return result


def get_reminder(reminder_id: str) -> dict | None:
    """Get a single reminder by ID."""
    reminders = _load_reminders()
    for r in reminders:
        if r["id"] == reminder_id:
            return r
    return None


def cancel_reminder(reminder_id: str) -> str:
    """Cancel (deactivate) a reminder by ID.

    Returns:
        Status message.
    """
    reminders = _load_reminders()
    for r in reminders:
        if r["id"] == reminder_id:
            if not r.get("active", True):
                return f"Reminder '{reminder_id}' is already inactive."
            r["active"] = False
            # Deactivate backing schedule if present
            if r.get("schedule_id"):
                try:
                    _dl_sched.update_schedule(r["schedule_id"], active=False)
                except Exception:
                    pass
            _save_reminders(reminders)
            log_entity_change("cancelled", reminder_id, "reminder",
                              f"For {r['user_id']}: {r['message'][:80]}")
            digest_record(app_id="reminders", entity_type="reminder", action="deleted",
                          entity_id=reminder_id, record=dict(r),
                          by=r.get("user_id", ""))
            return f"Reminder '{reminder_id}' cancelled."
    return f"Reminder '{reminder_id}' not found."


def modify_reminder(
    reminder_id: str,
    message: str | None = None,
    remind_at: str | None = None,
    recurrence: dict | None = None,
    clear_recurrence: bool = False,
    time_slot: str | None = None,
    clear_time_slot: bool = False,
) -> str:
    """Modify an existing reminder or nag.

    Args:
        reminder_id: Which reminder to modify.
        message: New message text (or None to keep current).
        remind_at: New next fire time as ISO datetime (or None to keep current).
        recurrence: New recurrence rule (or None to keep current).
        clear_recurrence: If True, remove recurrence (make one-shot).
        time_slot: New time-of-day scope for nags: "morning", "afternoon",
                   "evening", or "night". Only applies to nag reminders.
        clear_time_slot: If True, remove time_slot (revert to full waking hours).

    Returns:
        Status message.
    """
    reminders = _load_reminders()
    for r in reminders:
        if r["id"] == reminder_id:
            if message is not None:
                r["message"] = message
            if remind_at is not None:
                r["remind_at"] = remind_at
            if clear_recurrence:
                r["recurrence"] = None
            elif recurrence is not None:
                r["recurrence"] = recurrence

            # Handle time_slot changes on nags
            if r.get("nag"):
                slot_changed = False
                if clear_time_slot:
                    r["time_slot"] = None
                    slot_changed = True
                elif time_slot is not None:
                    ts = time_slot.strip().lower()
                    if ts in NAG_SLOTS:
                        r["time_slot"] = ts
                        slot_changed = True

                # Reschedule into the new window if slot changed and no explicit remind_at
                if slot_changed and remind_at is None:
                    now = datetime.now(CENTRAL_TZ)
                    today = now.date()
                    same_slot_nags = [x for x in reminders
                                      if x.get("nag") and x.get("active", True)
                                      and x["user_id"] == r["user_id"]
                                      and x.get("time_slot") == r.get("time_slot")]
                    idx = next((i for i, n in enumerate(same_slot_nags) if n["id"] == reminder_id), 0)
                    new_time = _nag_time_for_date(
                        r["id"], today, idx, len(same_slot_nags),
                        time_slot=r.get("time_slot"),
                    )
                    if new_time <= now:
                        new_time = _nag_time_for_date(
                            r["id"], today + timedelta(days=1), idx, len(same_slot_nags),
                            time_slot=r.get("time_slot"),
                        )
                    r["remind_at"] = new_time.isoformat()

            # Sync changes to backing schedule if present
            if r.get("schedule_id") and not r.get("nag"):
                try:
                    sched_updates = {}
                    if message is not None:
                        sched_updates["title"] = message[:120]
                    if clear_recurrence:
                        # Recurrence cleared — deactivate backing schedule
                        _dl_sched.update_schedule(r["schedule_id"], active=False)
                        r["schedule_id"] = ""
                    elif r.get("recurrence"):
                        params = _rrule_to_schedule_params(r["recurrence"], r["remind_at"])
                        sched_updates["recurrence_type"] = params["recurrence_type"]
                        sched_updates["recurrence_rule"] = params["recurrence_rule"]
                        sched_updates["time_of_day"] = params["time_of_day"]
                    if remind_at is not None:
                        try:
                            next_due = datetime.fromisoformat(r["remind_at"])
                            if next_due.tzinfo is None:
                                next_due = next_due.replace(tzinfo=CENTRAL_TZ)
                            else:
                                next_due = next_due.astimezone(CENTRAL_TZ)
                            sched_updates["next_due"] = next_due
                        except (ValueError, TypeError):
                            pass
                    if sched_updates:
                        _dl_sched.update_schedule(r["schedule_id"], **sched_updates)
                except Exception:
                    pass

            r["active"] = True
            _save_reminders(reminders)
            log_entity_change("modified", reminder_id, "reminder",
                              f"For {r['user_id']}: {r['message'][:80]}")
            digest_record(app_id="reminders", entity_type="reminder", action="updated",
                          entity_id=reminder_id, record=dict(r),
                          by=r.get("user_id", ""), context_hint=_REMINDER_HINT)
            # Return the full saved state so callers see exactly what's persisted
            slot_info = f"  time_slot: {r.get('time_slot')}\n" if r.get("nag") else ""
            return (
                f"Reminder '{reminder_id}' updated. Current saved state:\n"
                f"  remind_at: {r['remind_at']}\n"
                f"  message: {r['message']}\n"
                f"  recurrence: {r.get('recurrence')}\n"
                f"{slot_info}"
                f"  active: {r['active']}"
            )
    return f"Reminder '{reminder_id}' not found."


# ---------------------------------------------------------------------------
# RRULE → Schedule parameter conversion
# ---------------------------------------------------------------------------

def _rrule_to_schedule_params(rrule_str: str, dtstart_iso: str) -> dict:
    """Preserve RRULE-backed reminders as first-class RRULE schedules."""
    time_of_day = None
    try:
        dt = datetime.fromisoformat(dtstart_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CENTRAL_TZ)
        else:
            dt = dt.astimezone(CENTRAL_TZ)
        if dt.hour or dt.minute:
            time_of_day = f"{dt.hour:02d}:{dt.minute:02d}"
    except (ValueError, TypeError):
        dt = datetime.now(CENTRAL_TZ)
    return {
        "recurrence_type": "rrule",
        "recurrence_rule": {
            "rrule": str(rrule_str or "").strip(),
            "dtstart": dt.isoformat(),
        },
        "time_of_day": time_of_day,
    }


# ---------------------------------------------------------------------------
# Legacy format conversion
# ---------------------------------------------------------------------------

def _dict_to_rrule(rec: dict) -> str:
    """Convert old dict-format recurrence to an RRULE string."""
    parts = []
    freq = rec.get("freq", "daily").upper()
    parts.append(f"FREQ={_FREQ_MAP.get(freq.lower(), freq)}")

    interval = rec.get("interval", 1)
    if interval and interval > 1:
        parts.append(f"INTERVAL={interval}")

    days_of_week = rec.get("days_of_week", [])
    if days_of_week:
        abbrs = [_DAY_ABBR.get(d.lower(), d.upper()[:2]) for d in days_of_week]
        parts.append(f"BYDAY={','.join(abbrs)}")

    days_of_month = rec.get("days_of_month", [])
    if days_of_month:
        parts.append(f"BYMONTHDAY={','.join(str(d) for d in days_of_month)}")

    time_str = rec.get("time")
    if time_str:
        h, m = time_str.split(":")
        parts.append(f"BYHOUR={int(h)}")
        parts.append(f"BYMINUTE={int(m)}")

    end_date = rec.get("end_date")
    if end_date:
        # Convert to UNTIL format (YYYYMMDDTHHMMSS)
        try:
            ed = datetime.fromisoformat(end_date)
            parts.append(f"UNTIL={ed.strftime('%Y%m%dT235959')}")
        except ValueError:
            parts.append(f"UNTIL={end_date.replace('-', '')}T235959")

    return ";".join(parts)


def _fix_until_tz(rrule_string: str, dtstart: datetime) -> str:
    """Fix UNTIL values in RRULE strings for tz-aware dtstart.

    dateutil requires UNTIL to be UTC (ending with Z) when dtstart is
    timezone-aware. This converts naive UNTIL values to UTC assuming
    they were specified in the platform's local timezone.
    """
    import re
    match = re.search(r'UNTIL=(\d{8}T\d{6})(?!Z)', rrule_string)
    if not match:
        return rrule_string  # Already has Z or no UNTIL

    naive_str = match.group(1)
    try:
        naive_dt = datetime.strptime(naive_str, "%Y%m%dT%H%M%S")
        # Treat as platform-local, convert to UTC
        local_dt = naive_dt.replace(tzinfo=CENTRAL_TZ)
        utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
        utc_str = utc_dt.strftime("%Y%m%dT%H%M%S") + "Z"
        return rrule_string.replace(f"UNTIL={naive_str}", f"UNTIL={utc_str}")
    except ValueError:
        return rrule_string


# ---------------------------------------------------------------------------
# Due reminders & next occurrence (powered by dateutil.rrule)
# ---------------------------------------------------------------------------

def get_due_reminders() -> list[dict]:
    """Get all active reminders that are due (remind_at <= now)."""
    reminders = _load_reminders()
    now = datetime.now(CENTRAL_TZ)
    due = []
    for r in reminders:
        if not r.get("active", True):
            continue
        try:
            remind_at = datetime.fromisoformat(r["remind_at"])
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=CENTRAL_TZ)
            if remind_at <= now:
                due.append(r)
        except (ValueError, KeyError):
            continue
    return due


def mark_delivered(reminder_id: str):
    """Mark a reminder as delivered. For one-shot, deactivates it.
    For recurring, advances remind_at to the next occurrence.
    For nags, sets last_nagged to today and assigns tomorrow's random time."""
    reminders = _load_reminders()
    for r in reminders:
        if r["id"] == reminder_id:
            if r.get("nag"):
                # Nag: record today, assign a new random time for tomorrow
                today = datetime.now(CENTRAL_TZ).date()
                r["last_nagged"] = today.isoformat()
                tomorrow = today + timedelta(days=1)
                # Count this user's active nags in the same time_slot to spread times
                ts = r.get("time_slot")
                user_nags = [x for x in reminders if x.get("nag") and x.get("active", True)
                             and x["user_id"] == r["user_id"]
                             and x.get("time_slot") == ts]
                slot_index = next((i for i, n in enumerate(user_nags) if n["id"] == reminder_id), 0)
                r["remind_at"] = _nag_time_for_date(
                    r["id"], tomorrow, slot_index, len(user_nags),
                    time_slot=ts,
                ).isoformat()
            elif r.get("schedule_id"):
                # Schedule-backed: complete the schedule, sync remind_at
                try:
                    sch = _dl_sched.complete_schedule(
                        r["schedule_id"],
                        completed_by=r.get("user_id", ""),
                        notes="Auto-completed by reminder delivery",
                    )
                    if sch and sch.get("next_due"):
                        r["remind_at"] = sch["next_due"]
                    else:
                        r["active"] = False
                except Exception:
                    # Fallback to RRULE if schedule completion fails
                    if r.get("recurrence"):
                        current_dt = datetime.fromisoformat(r["remind_at"])
                        if current_dt.tzinfo is None:
                            current_dt = current_dt.replace(tzinfo=CENTRAL_TZ)
                        next_time = compute_next_occurrence(current_dt, r["recurrence"])
                        if next_time:
                            r["remind_at"] = next_time.isoformat()
                        else:
                            r["active"] = False
                    else:
                        r["active"] = False
            elif r.get("recurrence"):
                current_dt = datetime.fromisoformat(r["remind_at"])
                if current_dt.tzinfo is None:
                    current_dt = current_dt.replace(tzinfo=CENTRAL_TZ)
                next_time = compute_next_occurrence(current_dt, r["recurrence"])
                if next_time:
                    r["remind_at"] = next_time.isoformat()
                else:
                    r["active"] = False
            else:
                r["active"] = False
            _save_reminders(reminders)
            return


def snooze_reminder(reminder_id: str, minutes: int) -> dict | str:
    """Create a one-shot follow-up reminder based on an existing reminder or nag.

    Does NOT modify the original — creates a brand new one-shot reminder
    that fires at now + minutes. The follow-up can itself be snoozed again.

    Args:
        reminder_id: The reminder to snooze (e.g. "r-abc12345").
        minutes: How many minutes from now to fire the follow-up.

    Returns:
        The new follow-up reminder dict, or error string.
    """
    original = get_reminder(reminder_id)
    if not original:
        return f"Reminder '{reminder_id}' not found."

    now = datetime.now(CENTRAL_TZ)
    fire_at = now + timedelta(minutes=max(1, minutes))

    # Build message — preserve the original message, note it's a follow-up
    orig_message = original["message"]
    # Strip any existing follow-up prefix to avoid stacking
    if orig_message.startswith("🔁 "):
        orig_message = orig_message[2:].strip()
    followup_message = f"🔁 {orig_message}"

    reminders = _load_reminders()

    followup = {
        "id": f"r-{uuid.uuid4().hex[:8]}",
        "user_id": original["user_id"],
        "message": followup_message,
        "remind_at": fire_at.isoformat(),
        "created_at": now.isoformat(),
        "recurrence": None,
        "active": True,
        "snoozed_from": reminder_id,
    }

    reminders.append(followup)
    _save_reminders(reminders)

    log_entity_change("created", followup["id"], "reminder",
                      f"Snoozed from {reminder_id} for {original['user_id']}: "
                      f"{orig_message[:60]} → fires in {minutes}m",
                      by=original["user_id"])
    digest_record(app_id="reminders", entity_type="reminder", action="created",
                  entity_id=followup["id"], record=followup,
                  by=original.get("user_id", ""), context_hint=_REMINDER_HINT)
    return followup


def compute_next_occurrence(current_dt: datetime, recurrence) -> datetime | None:
    """Compute the next fire time using dateutil.rrule.

    Args:
        current_dt: The current/just-fired remind_at.
        recurrence: RRULE string (e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR")
                    or legacy dict format (auto-converted).

    Returns:
        Next timezone-aware datetime in the platform's local timezone, or None if ended.
    """
    if current_dt.tzinfo is None:
        current_dt = current_dt.replace(tzinfo=CENTRAL_TZ)

    # Convert legacy dict to RRULE string
    if isinstance(recurrence, dict):
        rrule_string = _dict_to_rrule(recurrence)
    else:
        rrule_string = str(recurrence).strip()

    # dateutil requires UNTIL to be UTC (with Z) when dtstart is tz-aware.
    # Auto-fix naive UNTIL values by converting local time to UTC.
    rrule_string = _fix_until_tz(rrule_string, current_dt)

    try:
        rule = rrulestr(rrule_string, dtstart=current_dt)
        next_dt = rule.after(current_dt, inc=False)
        if next_dt is None:
            return None
        # Ensure local timezone
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=CENTRAL_TZ)
        return next_dt
    except (ValueError, TypeError) as e:
        # Fallback: if RRULE parsing fails, return None (deactivates reminder)
        import logging
        logging.getLogger("skipperbot").error("RRULE parse error for '%s': %s", rrule_string, e)
        return None
