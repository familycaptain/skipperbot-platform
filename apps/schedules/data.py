"""Schedules — data layer + recurrence engine.

Owns reads + writes for the ``app_schedules.schedules`` and
``app_schedules.schedule_completions`` tables, plus the RRULE / cron /
interval / daily / weekly / monthly / yearly recurrence math
(``compute_next_due``, ``describe_recurrence``,
``_expand_rrule_occurrences``, and the ``_next_*`` family).

Ported from ``data_layer/schedules.py`` for sub-chunk 8c-part-1.
Functionally identical; only difference is routing all queries
through the ``*_in_schema`` helpers from ``app_platform.db`` so the
schedules app's tables land in (and read from) the ``app_schedules``
schema.

The recurrence engine is kept inline rather than split into a
separate ``store.py`` because the helpers are tightly coupled to row
layout (``recurrence_rule``, ``time_of_day``, ``next_due``); pulling
them out would make this app harder to reason about. The
``app_platform.schedules`` shim re-exports the public surface so
other apps still see a clean contract.
"""

from __future__ import annotations

import json
import re
import uuid
import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from psycopg2.extras import Json

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)
from data_layer.links import ensure_edge  # platform infra — links live in public.*

from app_platform.time import get_timezone

logger = logging.getLogger(__name__)

SCHEMA = "app_schedules"

VALID_CATEGORIES = {"chore", "maintenance", "school", "auto", "medical", "general"}
VALID_RECURRENCE_TYPES = {"daily", "weekly", "monthly", "yearly", "interval", "cron", "rrule"}


# ---------------------------------------------------------------------------
# Memory-digestion hints
# ---------------------------------------------------------------------------

_SCHEDULE_HINT = (
    "Focus on: the schedule's title, category (chore/maintenance/school/"
    "auto/medical/general), assignee, recurrence (what day or interval), "
    "and next_due. Schedules are how chat answers 'what's due this week?'."
)

_COMPLETION_HINT = (
    "Focus on: which schedule was completed, who completed it, when, and "
    "any usage_value (e.g. odometer reading)."
)


# ---------------------------------------------------------------------------
# Backfill registry
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES = [
    {
        "entity_type": "schedule",
        "list_fn": lambda: list_schedules(active_only=False, limit=10000),
        "context_hint": _SCHEDULE_HINT,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    # Serialize datetimes to ISO strings for JSON transport
    for key in ("created_at", "updated_at", "last_completed", "next_due"):
        if key in d and d[key] is not None:
            if isinstance(d[key], datetime):
                d[key] = d[key].isoformat()
    # time_of_day -> string
    if d.get("time_of_day") is not None and isinstance(d["time_of_day"], time):
        d["time_of_day"] = d["time_of_day"].strftime("%H:%M")
    # recurrence_rule is already a dict from JSONB
    if isinstance(d.get("recurrence_rule"), str):
        try:
            d["recurrence_rule"] = json.loads(d["recurrence_rule"])
        except (json.JSONDecodeError, TypeError):
            pass
    # job_config — same shape
    if isinstance(d.get("job_config"), str):
        try:
            d["job_config"] = json.loads(d["job_config"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def _new_id() -> str:
    return f"sch-{uuid.uuid4().hex[:8]}"


def _completion_id() -> str:
    return f"sc-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(get_timezone())


def _coerce_central_datetime(value, fallback_time: Optional[time] = None) -> datetime:
    """Parse a datetime-like value and normalize it to the platform's local timezone."""
    if isinstance(value, datetime):
        dt = value
    else:
        from dateutil.parser import parse as _dtparse
        dt = _dtparse(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_timezone())
    else:
        dt = dt.astimezone(get_timezone())
    if fallback_time is not None:
        dt = dt.replace(
            hour=fallback_time.hour,
            minute=fallback_time.minute,
            second=0,
            microsecond=0,
        )
    return dt


def _parse_time_of_day(time_of_day: Optional[str]) -> Optional[time]:
    if time_of_day:
        try:
            parts = time_of_day.split(":")
            return time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None
    return None


def _time_str_from_dt(dt: datetime) -> Optional[str]:
    return f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None


def _fix_until_tz(rrule_string: str, dtstart: datetime) -> str:
    """Convert naive UNTIL values to UTC for tz-aware dateutil parsing."""
    match = re.search(r"UNTIL=(\d{8}T\d{6})(?!Z)", rrule_string)
    if not match:
        return rrule_string
    naive_str = match.group(1)
    try:
        naive_dt = datetime.strptime(naive_str, "%Y%m%dT%H%M%S")
        utc_dt = naive_dt.replace(tzinfo=get_timezone()).astimezone(ZoneInfo("UTC"))
        return rrule_string.replace(
            f"UNTIL={naive_str}",
            f"UNTIL={utc_dt.strftime('%Y%m%dT%H%M%SZ')}",
        )
    except ValueError:
        return rrule_string


def _normalize_rrule_rule(
    recurrence_rule: dict | str | None,
    time_of_day: Optional[str] = None,
    anchor_dt=None,
) -> dict:
    """Return a normalized RRULE payload with a concrete dtstart."""
    if isinstance(recurrence_rule, dict):
        rule = dict(recurrence_rule)
    else:
        rule = {"rrule": str(recurrence_rule or "").strip()}

    rrule_string = str(rule.get("rrule") or "").strip()
    if not rrule_string:
        raise ValueError("RRULE schedules require recurrence_rule['rrule'].")

    fallback_tod = _parse_time_of_day(time_of_day)
    dtstart_raw = rule.get("dtstart") or anchor_dt or _now()
    dtstart = _coerce_central_datetime(dtstart_raw, fallback_time=fallback_tod)
    rrulestr(_fix_until_tz(rrule_string, dtstart), dtstart=dtstart)

    normalized = dict(rule)
    normalized["rrule"] = rrule_string
    normalized["dtstart"] = dtstart.isoformat()
    return normalized


def _rrule_components(rule: dict) -> tuple[str, datetime]:
    rrule_string = str((rule or {}).get("rrule") or "").strip()
    if not rrule_string:
        raise ValueError("Missing recurrence_rule['rrule'] for rrule schedule.")
    dtstart_raw = (rule or {}).get("dtstart")
    dtstart = _coerce_central_datetime(dtstart_raw or _now())
    return _fix_until_tz(rrule_string, dtstart), dtstart


def _next_rrule(now: datetime, rule: dict) -> Optional[datetime]:
    rrule_string, dtstart = _rrule_components(rule)
    next_dt = rrulestr(rrule_string, dtstart=dtstart).after(now, inc=False)
    if next_dt is None:
        return None
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=get_timezone())
    else:
        next_dt = next_dt.astimezone(get_timezone())
    return next_dt


def _expand_rrule_occurrences(rule: dict, start: datetime, end: datetime) -> list[datetime]:
    rrule_string, dtstart = _rrule_components(rule)
    occurrences = rrulestr(rrule_string, dtstart=dtstart).between(start, end, inc=True)
    normalized = []
    for occ in occurrences:
        if occ.tzinfo is None:
            occ = occ.replace(tzinfo=get_timezone())
        else:
            occ = occ.astimezone(get_timezone())
        normalized.append(occ)
    return normalized


# ---------------------------------------------------------------------------
# Recurrence Engine — compute next_due from recurrence_type + recurrence_rule
# ---------------------------------------------------------------------------

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def compute_next_due(
    recurrence_type: str,
    recurrence_rule: dict,
    time_of_day: Optional[str] = None,
    from_dt: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next occurrence after ``from_dt`` (default: now).

    Returns a timezone-aware datetime in the platform's local timezone,
    or None if unable to compute.
    """
    now = from_dt or _now()
    if isinstance(now, datetime) and now.tzinfo is None:
        now = now.replace(tzinfo=get_timezone())

    tod = _parse_time_of_day(time_of_day)

    try:
        if recurrence_type == "daily":
            return _next_daily(now, recurrence_rule, tod)
        elif recurrence_type == "weekly":
            return _next_weekly(now, recurrence_rule, tod)
        elif recurrence_type == "monthly":
            return _next_monthly(now, recurrence_rule, tod)
        elif recurrence_type == "yearly":
            return _next_yearly(now, recurrence_rule, tod)
        elif recurrence_type == "interval":
            return _next_interval(now, recurrence_rule, tod)
        elif recurrence_type == "cron":
            return _next_cron(now, recurrence_rule)
        elif recurrence_type == "rrule":
            return _next_rrule(now, recurrence_rule)
    except Exception as e:
        logger.warning("compute_next_due failed for %s/%s: %s", recurrence_type, recurrence_rule, e)

    return None


def _apply_time(dt: datetime, tod: Optional[time]) -> datetime:
    """Replace time component of dt with tod if provided."""
    if tod:
        return dt.replace(hour=tod.hour, minute=tod.minute, second=0, microsecond=0)
    return dt.replace(hour=9, minute=0, second=0, microsecond=0)  # default 9 AM


def _next_month_start(year: int, month: int) -> tuple[int, int]:
    month += 1
    if month > 12:
        return year + 1, 1
    return year, month


def _monthly_matches(year: int, month: int, weekdays: list[int]) -> list[datetime]:
    matches: list[datetime] = []
    cursor = datetime(year, month, 1, tzinfo=get_timezone())
    next_year, next_month = _next_month_start(year, month)
    month_end = datetime(next_year, next_month, 1, tzinfo=get_timezone())
    while cursor < month_end:
        if cursor.weekday() in weekdays:
            matches.append(cursor)
        cursor += timedelta(days=1)
    return matches


def _ordinal_label(value: int) -> str:
    if value == -1:
        return "Last"
    if value == -2:
        return "2nd last"
    if value == -3:
        return "3rd last"
    suffix = "th"
    if value % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _next_daily(now: datetime, rule: dict, tod: Optional[time]) -> datetime:
    every = rule.get("every", 1)
    candidate = _apply_time(now, tod)
    if candidate <= now:
        candidate += timedelta(days=1)
    # Align to "every N days" cycle
    if every > 1:
        while True:
            if candidate > now:
                return candidate
            candidate += timedelta(days=every)
    return candidate


def _next_weekly(now: datetime, rule: dict, tod: Optional[time]) -> datetime:
    days = rule.get("days", [])
    if not days:
        days = [now.strftime("%a").lower()[:3]]

    target_weekdays = sorted(set(WEEKDAY_MAP.get(d.lower()[:3], 0) for d in days))
    every = rule.get("every", 1)  # every N weeks

    # Start from today, scan up to 8 weeks out
    for offset in range(every * 7 * 2 + 1):
        candidate = now + timedelta(days=offset)
        candidate = _apply_time(candidate, tod)
        if candidate.weekday() in target_weekdays and candidate > now:
            return candidate

    # Fallback
    return _apply_time(now + timedelta(days=1), tod)


def _next_monthly(now: datetime, rule: dict, tod: Optional[time]) -> datetime:
    day = rule.get("day")

    if day == "last":
        # Last day of current or next month
        month = now.month
        year = now.year
        for _ in range(3):
            if month == 12:
                next_month_first = datetime(year + 1, 1, 1, tzinfo=get_timezone())
            else:
                next_month_first = datetime(year, month + 1, 1, tzinfo=get_timezone())
            last_day = next_month_first - timedelta(days=1)
            candidate = _apply_time(last_day, tod)
            if candidate > now:
                return candidate
            month = month + 1 if month < 12 else 1
            year = year + 1 if month == 1 else year
    elif isinstance(day, int):
        month = now.month
        year = now.year
        for _ in range(3):
            try:
                candidate = _apply_time(
                    datetime(year, month, day, tzinfo=get_timezone()), tod
                )
                if candidate > now:
                    return candidate
            except ValueError:
                pass
            year, month = _next_month_start(year, month)
    elif "week" in rule and ("weekday" in rule or "weekdays" in rule):
        target_week = int(rule["week"])
        weekday_names = rule.get("weekdays") or [rule.get("weekday", "mon")]
        target_wds = sorted(
            {WEEKDAY_MAP.get(str(name).lower()[:3], 0) for name in weekday_names if name}
        )
        month = now.month
        year = now.year
        for _ in range(3):
            matches = _monthly_matches(year, month, target_wds)
            if matches:
                try:
                    selected = matches[target_week - 1] if target_week > 0 else matches[target_week]
                except IndexError:
                    selected = None
                if selected is not None:
                    candidate = _apply_time(selected, tod)
                    if candidate > now:
                        return candidate
            year, month = _next_month_start(year, month)

    return _apply_time(now + timedelta(days=1), tod)


def _next_yearly(now: datetime, rule: dict, tod: Optional[time]) -> datetime:
    months = rule.get("months") or ([rule["month"]] if "month" in rule else [now.month])
    day = rule.get("day", 1)

    for year_offset in range(3):
        year = now.year + year_offset
        for month in months:
            try:
                candidate = _apply_time(
                    datetime(year, month, min(day, 28), tzinfo=get_timezone()), tod
                )
                if candidate > now:
                    return candidate
            except ValueError:
                pass

    return _apply_time(now + timedelta(days=1), tod)


def _next_interval(now: datetime, rule: dict, tod: Optional[time]) -> datetime:
    """Interval-based: N days from now (used when completing to advance from last_completed)."""
    days = rule.get("days", 30)
    return _apply_time(now + timedelta(days=days), tod)


def _next_cron(now: datetime, rule: dict) -> Optional[datetime]:
    """Use croniter to compute next from a cron expression."""
    expr = rule.get("expr", "")
    if not expr:
        return None
    try:
        from croniter import croniter
        cron = croniter(expr, now)
        return cron.get_next(datetime).replace(tzinfo=get_timezone())
    except ImportError:
        logger.warning("croniter not installed — cron schedule ignored")
    except Exception as e:
        logger.warning("Invalid cron expression '%s': %s", expr, e)
    return None


def describe_recurrence(recurrence_type: str, recurrence_rule: dict) -> str:
    """Human-readable summary of a recurrence pattern."""
    rule = recurrence_rule or {}
    if recurrence_type == "daily":
        every = rule.get("every", 1)
        return "Every day" if every == 1 else f"Every {every} days"
    elif recurrence_type == "weekly":
        days = rule.get("days", [])
        every = rule.get("every", 1)
        day_str = ", ".join(d.capitalize() for d in days) if days else "week"
        prefix = "" if every == 1 else f"Every {every} weeks on "
        return f"{prefix}{day_str}" if every > 1 else f"Every {day_str}"
    elif recurrence_type == "monthly":
        day = rule.get("day")
        if day == "last":
            return "Last day of every month"
        elif isinstance(day, int):
            return f"{day}th of every month"
        elif "week" in rule:
            week = rule["week"]
            weekday_names = rule.get("weekdays") or [rule.get("weekday", "")]
            wd = "/".join(str(name).capitalize() for name in weekday_names if name)
            return f"{_ordinal_label(int(week))} {wd} of every month".strip()
        return "Monthly"
    elif recurrence_type == "yearly":
        months = rule.get("months") or ([rule.get("month")] if "month" in rule else [])
        day = rule.get("day", 1)
        import calendar
        month_names = [calendar.month_name[m] for m in months if 1 <= m <= 12]
        return f"Every {' & '.join(month_names)} {day}" if month_names else "Yearly"
    elif recurrence_type == "interval":
        days = rule.get("days", 30)
        return f"Every {days} days"
    elif recurrence_type == "cron":
        return f"Cron: {rule.get('expr', '?')}"
    elif recurrence_type == "rrule":
        raw = str(rule.get("rrule") or "").strip()
        return f"RRULE: {raw}" if raw else "RRULE"
    return recurrence_type


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_schedule(
    title: str,
    created_by: str,
    category: str = "general",
    assigned_to: str = "",
    description: str = "",
    recurrence_type: str = "weekly",
    recurrence_rule: dict | None = None,
    time_of_day: str | None = None,
    duration_mins: int | None = None,
    usage_metric: str | None = None,
    usage_interval: int | None = None,
    linked_entity_id: str | None = None,
    linked_entity_type: str | None = None,
    reminder_mins: int | None = None,
    notify_channel: str = "both",
    start_date: str | None = None,
    job_config: dict | None = None,
) -> dict:
    """Create a new schedule and compute its first next_due.

    If start_date is provided (YYYY-MM-DD), use it as the first next_due
    instead of computing from recurrence rules.

    reminder_mins=None means "use the app default" — the Settings → Schedules
    `default_reminder_minutes` value (falling back to 60). Pass an explicit int
    to override per-schedule.
    """
    if reminder_mins is None:
        try:
            from app_platform import settings as _settings
            reminder_mins = int(_settings.get(
                "default_reminder_minutes", scope="app:schedules", default=60) or 60)
        except (TypeError, ValueError):
            reminder_mins = 60
    sch_id = _new_id()
    rule = recurrence_rule or {}
    effective_recurrence_type = recurrence_type if recurrence_type in VALID_RECURRENCE_TYPES else "weekly"
    effective_time_of_day = time_of_day

    if effective_recurrence_type == "rrule":
        anchor_dt = start_date or _now()
        rule = _normalize_rrule_rule(rule, effective_time_of_day, anchor_dt=anchor_dt)
        effective_time_of_day = _time_str_from_dt(_coerce_central_datetime(rule["dtstart"]))

    # Compute first next_due
    if start_date and effective_recurrence_type != "rrule":
        from dateutil.parser import parse as _dtparse
        dt = _dtparse(start_date)
        if effective_time_of_day:
            h, m = (int(x) for x in effective_time_of_day.split(":"))
            dt = dt.replace(hour=h, minute=m, second=0)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=get_timezone())
        next_due = dt
    else:
        next_due = compute_next_due(effective_recurrence_type, rule, effective_time_of_day)

    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO schedules (
                    id, title, description, category, assigned_to, created_by,
                    recurrence_type, recurrence_rule, time_of_day, duration_mins,
                    usage_metric, usage_interval,
                    next_due, completed_count,
                    linked_entity_id, linked_entity_type,
                    reminder_mins, notify_channel,
                    active, created_at, updated_at,
                    job_config
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, 0,
                    %s, %s,
                    %s, %s,
                    TRUE, now(), now(),
                    %s
                )
                """,
                (
                    sch_id, title.strip(), description.strip(),
                    category if category in VALID_CATEGORIES else "general",
                    assigned_to.strip().lower() if assigned_to else created_by.strip().lower(),
                    created_by.strip().lower(),
                    effective_recurrence_type,
                    Json(rule),
                    effective_time_of_day if effective_time_of_day else None,
                    duration_mins,
                    usage_metric, usage_interval,
                    next_due,
                    linked_entity_id, linked_entity_type,
                    reminder_mins, notify_channel,
                    Json(job_config or {}),
                ),
            )
        conn.commit()

    if linked_entity_id:
        ensure_edge(sch_id, linked_entity_id, "linked_to", "linked_to")

    return get_schedule(sch_id)


def get_schedule(schedule_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM schedules WHERE id = %s", (schedule_id,))
    return _row_to_dict(row)


def list_schedules(
    category: str | None = None,
    assigned_to: str | None = None,
    active_only: bool = True,
    limit: int = 200,
) -> list[dict]:
    clauses = []
    params = []
    if category:
        clauses.append("category = %s")
        params.append(category)
    if assigned_to:
        clauses.append("assigned_to = %s")
        params.append(assigned_to.lower().strip())
    if active_only:
        clauses.append("active = TRUE")

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = fetch_all_in_schema(
        SCHEMA,
        f"""
        SELECT * FROM schedules
        {where}
        ORDER BY
            next_due ASC NULLS LAST,
            created_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [_row_to_dict(r) for r in rows]


def update_schedule(schedule_id: str, **kwargs) -> dict | None:
    """Update schedule fields. Recomputes next_due if recurrence changes."""
    current = get_schedule(schedule_id)
    if not current:
        return None

    allowed = {
        "title", "description", "category", "assigned_to",
        "recurrence_type", "recurrence_rule", "time_of_day", "duration_mins",
        "usage_metric", "usage_interval",
        "linked_entity_id", "linked_entity_type",
        "reminder_mins", "notify_channel", "active", "next_due",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return current

    effective_recurrence_type = updates.get("recurrence_type", current.get("recurrence_type", "weekly"))
    effective_time_of_day = updates.get("time_of_day", current.get("time_of_day"))
    if effective_recurrence_type == "rrule":
        anchor_dt = (
            updates.get("next_due")
            or (current.get("recurrence_rule") or {}).get("dtstart")
            or current.get("next_due")
            or current.get("last_completed")
            or _now()
        )
        normalized_rule = _normalize_rrule_rule(
            updates.get("recurrence_rule", current.get("recurrence_rule") or {}),
            effective_time_of_day,
            anchor_dt=anchor_dt,
        )
        updates["recurrence_rule"] = normalized_rule
        updates["time_of_day"] = _time_str_from_dt(_coerce_central_datetime(normalized_rule["dtstart"]))

    set_parts = []
    params = []
    for key, val in updates.items():
        if key == "recurrence_rule":
            set_parts.append(f"{key} = %s")
            params.append(Json(val))
        else:
            set_parts.append(f"{key} = %s")
            params.append(val)

    set_parts.append("updated_at = now()")
    params.append(schedule_id)

    execute_in_schema(
        SCHEMA,
        f"UPDATE schedules SET {', '.join(set_parts)} WHERE id = %s",
        tuple(params),
    )

    # Recompute next_due if recurrence changed (skip if next_due was explicitly set)
    if "next_due" not in updates and any(k in updates for k in ("recurrence_type", "recurrence_rule", "time_of_day")):
        sch = get_schedule(schedule_id)
        if sch:
            new_next = compute_next_due(
                sch["recurrence_type"],
                sch["recurrence_rule"],
                sch.get("time_of_day"),
                from_dt=datetime.fromisoformat(sch["last_completed"]) if sch.get("last_completed") else None,
            )
            if new_next:
                execute_in_schema(
                    SCHEMA,
                    "UPDATE schedules SET next_due = %s WHERE id = %s",
                    (new_next, schedule_id),
                )

    # Re-register edge if linked_entity_id changed
    if "linked_entity_id" in updates and updates["linked_entity_id"]:
        ensure_edge(schedule_id, updates["linked_entity_id"], "linked_to", "linked_to")

    return get_schedule(schedule_id)


def delete_schedule(schedule_id: str) -> bool:
    execute_in_schema(SCHEMA, "DELETE FROM schedules WHERE id = %s", (schedule_id,))
    return True


# ---------------------------------------------------------------------------
# Complete (Mark Done)
# ---------------------------------------------------------------------------

def complete_schedule(
    schedule_id: str,
    completed_by: str = "",
    notes: str = "",
    usage_value: int | None = None,
) -> dict | None:
    """Mark current occurrence as done, log completion, advance next_due."""
    sch = get_schedule(schedule_id)
    if not sch:
        return None

    now = _now()
    comp_id = _completion_id()

    # Log the completion
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO schedule_completions (id, schedule_id, completed_at, completed_by, notes, usage_value)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (comp_id, schedule_id, now, completed_by.strip().lower(), notes.strip(), usage_value),
            )
        conn.commit()

    # Compute new next_due from now
    new_next = compute_next_due(
        sch["recurrence_type"],
        sch["recurrence_rule"],
        sch.get("time_of_day"),
        from_dt=now,
    )

    # Update the schedule
    execute_in_schema(
        SCHEMA,
        """
        UPDATE schedules
        SET last_completed = %s,
            next_due = %s,
            completed_count = completed_count + 1,
            updated_at = now()
        WHERE id = %s
        """,
        (now, new_next, schedule_id),
    )

    return get_schedule(schedule_id)


def get_completions(schedule_id: str, limit: int = 20) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM schedule_completions WHERE schedule_id = %s ORDER BY completed_at DESC LIMIT %s",
        (schedule_id, limit),
    )
    result = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("completed_at"), datetime):
            d["completed_at"] = d["completed_at"].isoformat()
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Due / Overdue queries
# ---------------------------------------------------------------------------

def get_due_schedules(
    assigned_to: str | None = None,
    days_ahead: int = 7,
    exclude_reminder_backed: bool = False,
) -> list[dict]:
    """Get active schedules that are overdue or due within N days."""
    cutoff = _now() + timedelta(days=days_ahead)
    params: list = [cutoff]
    user_clause = ""
    if assigned_to:
        user_clause = "AND assigned_to = %s"
        params.append(assigned_to.lower().strip())
    reminder_clause = ""
    if exclude_reminder_backed:
        reminder_clause = "AND (linked_entity_type IS NULL OR linked_entity_type != 'reminder')"

    rows = fetch_all_in_schema(
        SCHEMA,
        f"""
        SELECT * FROM schedules
        WHERE active = TRUE
          AND next_due IS NOT NULL
          AND next_due <= %s
          {user_clause}
          {reminder_clause}
        ORDER BY next_due ASC
        """,
        tuple(params),
    )
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Calendar events — expand schedules into per-day events for a date range
# ---------------------------------------------------------------------------

def get_calendar_events(
    from_date: str,
    to_date: str,
    assigned_to: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Expand active schedules into calendar events for a date range.

    Returns a list of event dicts, one per occurrence per day, sorted by date.
    Each event: {schedule_id, title, category, assigned_to, date, time_of_day, overdue}
    """
    start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=get_timezone())
    end = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=get_timezone(), hour=23, minute=59, second=59)

    # Fetch all active schedules
    clauses = ["active = TRUE"]
    params: list = []
    if assigned_to:
        clauses.append("assigned_to = %s")
        params.append(assigned_to.lower().strip())
    if category:
        clauses.append("category = %s")
        params.append(category)

    where = " AND ".join(clauses)
    rows = fetch_all_in_schema(SCHEMA, f"SELECT * FROM schedules WHERE {where}", tuple(params))

    events = []
    now = _now()

    for row in rows:
        sch = _row_to_dict(row)
        if not sch:
            continue

        occurrences = _expand_occurrences(sch, start, end)
        for occ_date in occurrences:
            events.append({
                "schedule_id": sch["id"],
                "title": sch["title"],
                "category": sch["category"],
                "assigned_to": sch["assigned_to"],
                "date": occ_date.strftime("%Y-%m-%d"),
                "time_of_day": sch.get("time_of_day"),
                "overdue": sch.get("next_due") is not None and datetime.fromisoformat(sch["next_due"]) < now,
                "linked_entity_id": sch.get("linked_entity_id"),
                "linked_entity_type": sch.get("linked_entity_type"),
            })

    events.sort(key=lambda e: e["date"])
    return events


def _expand_occurrences(
    sch: dict,
    start: datetime,
    end: datetime,
) -> list[date]:
    """Generate all occurrence dates for a schedule within [start, end]."""
    results = []
    rec_type = sch["recurrence_type"]
    rule = sch["recurrence_rule"] or {}
    tod = sch.get("time_of_day")

    # For interval-based, we only have next_due (no pattern to expand)
    if rec_type == "interval":
        if sch.get("next_due"):
            nd = datetime.fromisoformat(sch["next_due"])
            if start <= nd <= end:
                results.append(nd.date() if isinstance(nd, datetime) else nd)
        return results

    # For cron, just use next_due
    if rec_type == "cron":
        if sch.get("next_due"):
            nd = datetime.fromisoformat(sch["next_due"])
            if start <= nd <= end:
                results.append(nd.date() if isinstance(nd, datetime) else nd)
        return results

    if rec_type == "rrule":
        try:
            return [occ.date() for occ in _expand_rrule_occurrences(rule, start, end)]
        except Exception as e:
            logger.warning("RRULE occurrence expansion failed for %s: %s", sch.get("id", "?"), e)
            return results

    # For daily/weekly/monthly/yearly, iterate through the range
    cursor = start
    max_iterations = 366  # safety limit
    iterations = 0

    while cursor <= end and iterations < max_iterations:
        iterations += 1
        next_occ = compute_next_due(rec_type, rule, tod, from_dt=cursor - timedelta(seconds=1))
        if not next_occ or next_occ > end:
            break
        if next_occ >= start:
            occ_d = next_occ.date() if isinstance(next_occ, datetime) else next_occ
            if not results or results[-1] != occ_d:
                results.append(occ_d)
        cursor = next_occ + timedelta(hours=1)  # advance past this occurrence

    return results
