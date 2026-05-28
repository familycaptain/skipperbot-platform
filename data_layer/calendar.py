"""Calendar Aggregation — unified calendar events from all sources
===================================================================
Combines schedule occurrences, reminders, tasks with due dates,
auto service records, and nags into a single event stream.
"""

import logging
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo

from data_layer.db import fetch_all

logger = logging.getLogger(__name__)

from config import TIMEZONE as _CFG_TZ
CENTRAL_TZ = ZoneInfo(_CFG_TZ)


def get_aggregated_events(
    from_date: str,
    to_date: str,
    assigned_to: str | None = None,
) -> list[dict]:
    """Return all calendar-worthy events in [from_date, to_date].

    Each event follows a unified shape:
        {source_type, source_id, title, category, date, time_of_day,
         overdue, assigned_to, all_day}
    """
    events: list[dict] = []

    events.extend(_events_from_schedules(from_date, to_date, assigned_to))
    events.extend(_events_from_reminders(from_date, to_date, assigned_to))
    events.extend(_events_from_goals(from_date, to_date, assigned_to))
    events.extend(_events_from_projects(from_date, to_date, assigned_to))
    events.extend(_events_from_tasks(from_date, to_date, assigned_to))
    events.extend(_events_from_auto_service(from_date, to_date))
    events.extend(_events_from_nags(from_date, to_date, assigned_to))
    events.extend(_events_from_todo(from_date, to_date, assigned_to))

    events.sort(key=lambda e: (e["date"], e.get("time_of_day") or ""))
    return events


# ---------------------------------------------------------------------------
# Schedules (delegate to existing engine)
# ---------------------------------------------------------------------------

def _events_from_schedules(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    try:
        from data_layer.schedules import get_calendar_events
        raw = get_calendar_events(from_date, to_date, assigned_to=assigned_to)
        # Exclude reminder-backed schedules (they appear via _events_from_reminders)
        return [{
            "source_type": "schedule",
            "source_id": ev["schedule_id"],
            "title": ev["title"],
            "category": ev.get("category") or "general",
            "date": ev["date"],
            "time_of_day": ev.get("time_of_day"),
            "overdue": ev.get("overdue", False),
            "assigned_to": ev.get("assigned_to") or "",
            "all_day": not bool(ev.get("time_of_day")),
        } for ev in raw if ev.get("linked_entity_type") != "reminder"]
    except Exception as e:
        logger.error("Calendar: schedules aggregation failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Reminders (expand RRULE occurrences within range)
# ---------------------------------------------------------------------------

def _events_from_reminders(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    try:
        start_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=CENTRAL_TZ)
        end_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(
            tzinfo=CENTRAL_TZ, hour=23, minute=59, second=59,
        )
        now = datetime.now(CENTRAL_TZ)

        clauses = ["active = TRUE", "nag = FALSE"]
        params: list = []
        if assigned_to:
            clauses.append("user_id = %s")
            params.append(assigned_to.lower().strip())

        where = " AND ".join(clauses)
        rows = fetch_all(
            f"SELECT id, user_id, message, remind_at, recurrence FROM reminders WHERE {where}",
            tuple(params),
        )

        events = []
        for r in rows:
            remind_at = r.get("remind_at")
            if not remind_at:
                continue
            if hasattr(remind_at, "isoformat"):
                remind_dt = remind_at if remind_at.tzinfo else remind_at.replace(tzinfo=CENTRAL_TZ)
            else:
                try:
                    remind_dt = datetime.fromisoformat(str(remind_at))
                    if remind_dt.tzinfo is None:
                        remind_dt = remind_dt.replace(tzinfo=CENTRAL_TZ)
                except (ValueError, TypeError):
                    continue

            recurrence = r.get("recurrence")
            time_str = remind_dt.strftime("%H:%M") if (remind_dt.hour or remind_dt.minute) else None

            if recurrence:
                # Expand RRULE occurrences within range
                occurrences = _expand_rrule(remind_dt, recurrence, start_dt, end_dt)
                for occ in occurrences:
                    occ_date = occ.date() if isinstance(occ, datetime) else occ
                    events.append({
                        "source_type": "reminder",
                        "source_id": r["id"],
                        "title": r["message"],
                        "category": "reminder",
                        "date": occ_date.isoformat(),
                        "time_of_day": time_str,
                        "overdue": occ < now if isinstance(occ, datetime) else datetime.combine(occ_date, dtime(), CENTRAL_TZ) < now,
                        "assigned_to": r.get("user_id") or "",
                        "all_day": time_str is None,
                    })
            else:
                # One-shot reminder — show on its fire date if in range
                remind_date = remind_dt.date()
                start_d = start_dt.date()
                end_d = end_dt.date()
                if start_d <= remind_date <= end_d:
                    events.append({
                        "source_type": "reminder",
                        "source_id": r["id"],
                        "title": r["message"],
                        "category": "reminder",
                        "date": remind_date.isoformat(),
                        "time_of_day": time_str,
                        "overdue": remind_dt < now,
                        "assigned_to": r.get("user_id") or "",
                        "all_day": time_str is None,
                    })

        return events
    except Exception as e:
        logger.error("Calendar: reminders aggregation failed: %s", e, exc_info=True)
        return []


def _expand_rrule(dtstart: datetime, rrule_string: str, start: datetime, end: datetime) -> list[datetime]:
    """Expand an RRULE into occurrences within [start, end]."""
    try:
        from dateutil.rrule import rrulestr
        rule = rrulestr(rrule_string, dtstart=dtstart)
        return list(rule.between(start, end, inc=True))
    except Exception:
        # Fallback: if RRULE can't be parsed, just return dtstart if in range
        if start <= dtstart <= end:
            return [dtstart]
        return []


# ---------------------------------------------------------------------------
# Goals with target dates
# ---------------------------------------------------------------------------

def _events_from_goals(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    try:
        now_date = datetime.now(CENTRAL_TZ).date()

        clauses = [
            "status NOT IN ('done', 'cancelled')",
            "target_date IS NOT NULL",
            "target_date != ''",
            "target_date >= %s",
            "target_date <= %s",
        ]
        params: list = [from_date, to_date]
        if assigned_to:
            uid = assigned_to.lower().strip()
            clauses.append("(%s = ANY(owners) OR %s = ANY(collaborators))")
            params.extend([uid, uid])

        where = " AND ".join(clauses)
        rows = fetch_all(
            f"SELECT id, name, target_date, owners, collaborators FROM goals WHERE {where}",
            tuple(params),
        )

        events = []
        for r in rows:
            td = r.get("target_date")
            if not td:
                continue
            if hasattr(td, "isoformat"):
                td_str = td.isoformat()[:10]
                td_date = td if isinstance(td, date) else td.date()
            else:
                td_str = str(td)[:10]
                try:
                    td_date = date.fromisoformat(td_str)
                except (ValueError, TypeError):
                    continue

            owners = r.get("owners") or []
            collabs = r.get("collaborators") or []
            events.append({
                "source_type": "goal",
                "source_id": r["id"],
                "title": f"\U0001F3AF {r['name']}",
                "category": "goal",
                "date": td_str,
                "time_of_day": None,
                "overdue": td_date < now_date,
                "assigned_to": ", ".join(owners + collabs),
                "all_day": True,
            })
        return events
    except Exception as e:
        logger.error("Calendar: goals aggregation failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Projects with due dates
# ---------------------------------------------------------------------------

def _events_from_projects(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    try:
        now_date = datetime.now(CENTRAL_TZ).date()

        clauses = [
            "status NOT IN ('done', 'cancelled')",
            "due_date IS NOT NULL",
            "due_date != ''",
            "due_date >= %s",
            "due_date <= %s",
        ]
        params: list = [from_date, to_date]
        if assigned_to:
            uid = assigned_to.lower().strip()
            clauses.append("%s = ANY(owners)")
            params.append(uid)

        where = " AND ".join(clauses)
        rows = fetch_all(
            f"SELECT id, name, due_date, priority, owners FROM projects WHERE {where}",
            tuple(params),
        )

        events = []
        for r in rows:
            due = r.get("due_date")
            if not due:
                continue
            if hasattr(due, "isoformat"):
                due_str = due.isoformat()[:10]
                due_date = due if isinstance(due, date) else due.date()
            else:
                due_str = str(due)[:10]
                try:
                    due_date = date.fromisoformat(due_str)
                except (ValueError, TypeError):
                    continue

            events.append({
                "source_type": "project",
                "source_id": r["id"],
                "title": r["name"],
                "category": "project",
                "date": due_str,
                "time_of_day": None,
                "overdue": due_date < now_date,
                "assigned_to": ", ".join(r.get("owners") or []),
                "all_day": True,
                "priority": r.get("priority") or "medium",
            })
        return events
    except Exception as e:
        logger.error("Calendar: projects aggregation failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Tasks with due dates
# ---------------------------------------------------------------------------

def _events_from_tasks(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    try:
        now = datetime.now(CENTRAL_TZ)
        now_date = now.date()

        clauses = [
            "status NOT IN ('done', 'cancelled')",
            "due_date IS NOT NULL",
            "due_date != ''",
            "due_date >= %s",
            "due_date <= %s",
        ]
        params: list = [from_date, to_date]
        if assigned_to:
            clauses.append("%s = ANY(assigned_to)")
            params.append(assigned_to.lower().strip())

        where = " AND ".join(clauses)
        rows = fetch_all(
            f"SELECT id, name, due_date, priority, assigned_to FROM tasks WHERE {where}",
            tuple(params),
        )

        events = []
        for r in rows:
            due = r.get("due_date")
            if not due:
                continue
            if hasattr(due, "isoformat"):
                due_str = due.isoformat()[:10]
                due_date = due if isinstance(due, date) else due.date()
            else:
                due_str = str(due)[:10]
                try:
                    due_date = date.fromisoformat(due_str)
                except (ValueError, TypeError):
                    continue

            events.append({
                "source_type": "task",
                "source_id": r["id"],
                "title": r["name"],
                "category": "task",
                "date": due_str,
                "time_of_day": None,
                "overdue": due_date < now_date,
                "assigned_to": ", ".join(r.get("assigned_to") or []),
                "all_day": True,
                "priority": r.get("priority") or "medium",
            })
        return events
    except Exception as e:
        logger.error("Calendar: tasks aggregation failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Auto service records with next_due_date
# ---------------------------------------------------------------------------

def _events_from_auto_service(from_date: str, to_date: str) -> list[dict]:
    try:
        now_date = datetime.now(CENTRAL_TZ).date()

        rows = fetch_all(
            """SELECT sr.id, sr.vehicle_id, sr.service_type, sr.next_due_date,
                      v.name as vehicle_name
               FROM service_records sr
               JOIN vehicles v ON v.id = sr.vehicle_id
               WHERE sr.next_due_date IS NOT NULL
                 AND sr.next_due_date >= %s
                 AND sr.next_due_date <= %s
               ORDER BY sr.next_due_date""",
            (from_date, to_date),
        )

        events = []
        for r in rows:
            ndd = r.get("next_due_date")
            if not ndd:
                continue
            if hasattr(ndd, "isoformat"):
                date_str = ndd.isoformat()[:10]
                due_date = ndd if isinstance(ndd, date) else ndd.date()
            else:
                date_str = str(ndd)[:10]
                try:
                    due_date = date.fromisoformat(date_str)
                except (ValueError, TypeError):
                    continue

            vehicle = r.get("vehicle_name") or r.get("vehicle_id") or ""
            stype = r.get("service_type") or "Service"
            events.append({
                "source_type": "auto_service",
                "source_id": r["id"],
                "title": f"{stype} — {vehicle}",
                "category": "auto_service",
                "date": date_str,
                "time_of_day": None,
                "overdue": due_date < now_date,
                "assigned_to": "",
                "all_day": True,
                "vehicle_id": r.get("vehicle_id") or "",
            })
        return events
    except Exception as e:
        logger.error("Calendar: auto_service aggregation failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Nags (daily all-day markers for each active nag)
# ---------------------------------------------------------------------------

def _events_from_nags(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    try:
        today = datetime.now(CENTRAL_TZ).date()
        start_d = date.fromisoformat(from_date)
        end_d = date.fromisoformat(to_date)

        # Only show nags on today's date
        if not (start_d <= today <= end_d):
            return []

        clauses = ["active = TRUE", "nag = TRUE"]
        params: list = []
        if assigned_to:
            clauses.append("user_id = %s")
            params.append(assigned_to.lower().strip())

        where = " AND ".join(clauses)
        rows = fetch_all(
            f"SELECT id, user_id, message, time_slot FROM reminders WHERE {where}",
            tuple(params),
        )

        events = []
        today_str = today.isoformat()
        for r in rows:
            slot = r.get("time_slot") or ""
            events.append({
                "source_type": "nag",
                "source_id": r["id"],
                "title": r["message"],
                "category": "nag",
                "date": today_str,
                "time_of_day": None,
                "overdue": False,
                "assigned_to": r.get("user_id") or "",
                "all_day": True,
                "time_slot": slot,
            })

        return events
    except Exception as e:
        logger.error("Calendar: nags aggregation failed: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# To-Do list (weekly all-day event on the user's nudge day)
# ---------------------------------------------------------------------------

def _events_from_todo(from_date: str, to_date: str, assigned_to: str | None) -> list[dict]:
    """Show an all-day 'To-Do List (N items)' event on each user's nudge day within the range."""
    try:
        from apps.todo.data import get_all_configs
        from apps.todo.store import get_todo_items

        start_d = date.fromisoformat(from_date)
        end_d = date.fromisoformat(to_date)

        DAY_MAP = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }

        configs = get_all_configs()
        events = []

        for cfg in configs:
            user_id = cfg["user_id"]

            # Filter by assigned_to if specified
            if assigned_to and user_id.lower() != assigned_to.lower().strip():
                continue

            if not cfg.get("show_on_calendar", True):
                continue
            if not cfg.get("default_list_id"):
                continue

            nudge_day = cfg.get("nudge_day", "saturday").lower()
            target_weekday = DAY_MAP.get(nudge_day)
            if target_weekday is None:
                continue

            # Get item count
            result = get_todo_items(user_id)
            if not result:
                continue
            active_count = result.get("count", 0)
            if active_count == 0:
                continue

            list_id = result.get("list_id", "")

            # Find all occurrences of the nudge weekday within the date range
            current = start_d
            while current <= end_d:
                if current.weekday() == target_weekday:
                    events.append({
                        "source_type": "todo",
                        "source_id": list_id,
                        "title": f"To-Do List ({active_count} item{'s' if active_count != 1 else ''})",
                        "category": "todo",
                        "date": current.isoformat(),
                        "time_of_day": None,
                        "overdue": False,
                        "assigned_to": user_id,
                        "all_day": True,
                    })
                current += timedelta(days=1)

        return events
    except Exception as e:
        logger.error("Calendar: todo aggregation failed: %s", e, exc_info=True)
        return []
