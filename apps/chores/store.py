"""Chores App — Business logic (rotation math + assignment composition).

The rotation rule is a faithful translation of the spreadsheet:

    day_number  = NETWORKDAYS(rotation_start, target_date)   # Mon-Fri only
    base_index  = day_number mod len(members)
    chore_i_kid = members[(base_index + chore.position) mod len(members)]

For solo zones (1 member) the only kid is always assigned.
Days with no active chores produce no assignments.
"""

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apps.chores import data as _dl
from app_platform.time import get_timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def today_local() -> dt.date:
    """Today's date in the configured local timezone.

    The server may run in UTC, but "today" for a chore means today in
    the household's wall-clock time (platform timezone setting).
    """
    return dt.datetime.now(get_timezone()).date()


def networkdays(start: dt.date, end: dt.date) -> int:
    """Inclusive count of weekdays (Mon-Fri) from start to end.

    Matches Google Sheets NETWORKDAYS() with no holiday list.
    Returns 0 if end < start.
    """
    if end < start:
        return 0
    days = (end - start).days + 1
    full_weeks, rem = divmod(days, 7)
    count = full_weeks * 5
    start_weekday = start.weekday()  # Mon=0..Sun=6
    for i in range(rem):
        if (start_weekday + i) % 7 < 5:
            count += 1
    return count


def _to_date(value) -> dt.date:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    return dt.date.fromisoformat(str(value))


def _postgres_dow(d: dt.date) -> int:
    """0=Sun..6=Sat, matching Postgres extract(dow) and JS Date.getDay()."""
    return (d.weekday() + 1) % 7


# ---------------------------------------------------------------------------
# Assignment computation
# ---------------------------------------------------------------------------

def assignments_for_zone(zone: dict, members: list[dict], chores: list[dict],
                         target_date: dt.date) -> list[dict]:
    """Return assignment dicts for one zone on one date.

    Each result row: {chore, kid (member dict), date}
    `chores` should already be filtered to active chores for the target dow.
    """
    if not members or not chores:
        return []
    rotation_start = _to_date(zone["rotation_start"])
    base = networkdays(rotation_start, target_date)
    n = len(members)
    out = []
    for chore in chores:
        kid = members[(base + chore["position"]) % n]
        out.append({"chore": chore, "kid": kid, "date": target_date.isoformat()})
    return out


def assignments_for_date(target_date: dt.date) -> list[dict]:
    """Compute every assignment across every zone for a single date."""
    zones = _dl.list_zones()
    dow = _postgres_dow(target_date)
    all_assignments: list[dict] = []
    for zone in zones:
        members = _dl.get_zone_members(zone["id"])
        chores = _dl.list_chores_for_dow(zone["id"], dow)
        if not chores:
            continue
        all_assignments.extend(
            assignments_for_zone(zone, members, chores, target_date)
        )
    return all_assignments


def today_by_kid(target_date: dt.date | None = None) -> dict:
    """Top-level helper for the Today view / morning push.

    Returns:
        {
          "date": "YYYY-MM-DD",
          "kids": [
            {
              "id": "kid-...",
              "name": "Kid One",
              "color": "...",
              "user_id": "kid1",
              "assignments": [
                {
                  "chore_id": "ch-...",
                  "chore_name": "Vacuum & Empty Trash",
                  "note": "",
                  "zone_id": "cz-...",
                  "zone_name": "Bedroom - Kid One",
                  "position": 0,
                  "completed": false,
                  "completion": null  # or full completion dict
                }
              ]
            },
            ...
          ]
        }
    """
    if target_date is None:
        target_date = today_local()
    date_str = target_date.isoformat()

    kids = _dl.list_kids(active_only=True)
    kid_by_id = {k["id"]: k for k in kids}

    assignments = assignments_for_date(target_date)
    completions = _dl.list_completions_for_date(date_str)
    completion_by_key = {
        (c["chore_id"], c["kid_id"]): c for c in completions
    }

    # Bucket assignments by kid id
    buckets: dict[str, list[dict]] = {k["id"]: [] for k in kids}
    zones_cache = {z["id"]: z for z in _dl.list_zones()}

    for a in assignments:
        kid_id = a["kid"]["kid_id"]
        chore = a["chore"]
        zone = zones_cache.get(chore["zone_id"], {})
        completion = completion_by_key.get((chore["id"], kid_id))
        buckets.setdefault(kid_id, []).append({
            "chore_id": chore["id"],
            "chore_name": chore["name"],
            "note": chore["note"],
            "zone_id": chore["zone_id"],
            "zone_name": zone.get("name", ""),
            "position": chore["position"],
            "completed": completion is not None,
            "completion": completion,
        })

    return {
        "date": date_str,
        "kids": [
            {
                "id": k["id"],
                "name": k["name"],
                "color": k["color"],
                "user_id": k["user_id"],
                "sort_order": k["sort_order"],
                "notify_morning": k["notify_morning"],
                "assignments": buckets.get(k["id"], []),
            }
            for k in kids
        ],
    }


def week_by_kid(start_date: dt.date | None = None) -> dict:
    """Return 7-day matrix kid x day starting at start_date (default: this Sunday)."""
    if start_date is None:
        today = today_local()
        # find Sunday of the current week (dow=0 Sunday in postgres sense)
        days_since_sunday = (today.weekday() + 1) % 7
        start_date = today - dt.timedelta(days=days_since_sunday)

    days = [start_date + dt.timedelta(days=i) for i in range(7)]
    kids = _dl.list_kids(active_only=True)

    result_days = []
    for d in days:
        day_view = today_by_kid(d)
        result_days.append(day_view)

    return {
        "start_date": start_date.isoformat(),
        "days": result_days,
        "kids": [{"id": k["id"], "name": k["name"], "color": k["color"]} for k in kids],
    }


# ---------------------------------------------------------------------------
# Event emit helper
# ---------------------------------------------------------------------------

def _emit(event: str, data: dict) -> None:
    try:
        from app_platform.events import emit
        emit(event, data)
    except Exception as e:
        logger.debug("CHORES: event emit failed (%s): %s", event, e)


# ---------------------------------------------------------------------------
# Check-off / un-check-off (with event emit + permission resolution)
# ---------------------------------------------------------------------------

def complete_chore(chore_id: str, kid_id: str, chore_date: str,
                   completed_by: str | None = None, note: str = "") -> dict:
    """UPSERT a completion + emit event."""
    completion = _dl.upsert_completion(
        chore_id=chore_id, kid_id=kid_id, chore_date=chore_date,
        completed_by=completed_by, note=note,
    )
    _emit("chore.completed", {
        "completion_id": completion["id"],
        "chore_id": chore_id,
        "kid_id": kid_id,
        "date": chore_date,
        "completed_by": completed_by,
        "status": completion["status"],
    })
    return completion


def uncomplete_chore(chore_id: str, kid_id: str, chore_date: str) -> dict | None:
    """Delete an existing completion + emit event."""
    removed = _dl.delete_completion_by_key(chore_id, kid_id, chore_date)
    if removed:
        _emit("chore.uncompleted", {
            "completion_id": removed["id"],
            "chore_id": chore_id,
            "kid_id": kid_id,
            "date": chore_date,
        })
    return removed


# ---------------------------------------------------------------------------
# Chore name resolution (for chat use)
# ---------------------------------------------------------------------------

def find_assignment_for_kid_by_name(kid_id: str, chore_name: str,
                                     target_date: dt.date | None = None) -> dict | None:
    """Find the (chore, kid) pair matching a fuzzy chore name for a kid on a date.

    Used by the chat tool when the caller says e.g. "mark my vacuum done".
    Case-insensitive substring match. Returns None if no match.
    """
    if target_date is None:
        target_date = today_local()
    needle = chore_name.lower().strip()
    today = today_by_kid(target_date)
    for kid in today["kids"]:
        if kid["id"] != kid_id:
            continue
        for a in kid["assignments"]:
            if needle in a["chore_name"].lower():
                return a
    return None
