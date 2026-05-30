"""Auto App — Platform Hooks
==============================
Registers backlog providers, activity checkers, nag providers, and
schedule claims with the platform so the platform has no hard
dependency on this app.

Called by the app loader during startup.
"""

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app_platform.time import get_timezone

from data_layer.db import fetch_one as _pub_fetch_one, fetch_all as _pub_fetch_all

SCHEMA = "app_auto"
STALE_MONTHS = 6
_OIL_PATTERN = re.compile(r"oil\s*(change|[&/]|and)\s*(filter|change)?", re.IGNORECASE)


def register_hooks():
    """Register all platform hooks for the Auto app."""
    from apps.prioritize.data import register_backlog_provider, register_activity_checker
    from nag_registry import register_nag_provider
    from apps.schedules.notifier import register_schedule_claim

    register_backlog_provider("auto_issues", _backlog_auto_issues)
    register_activity_checker("auto_issue", _is_auto_issue_active)
    register_nag_provider("vehicle_nag", _vehicle_nag_provider)
    register_schedule_claim("vehicle")


# ---------------------------------------------------------------------------
# Backlog provider
# ---------------------------------------------------------------------------

def _backlog_auto_issues(user_id: str) -> list[dict]:
    """Open vehicle issues for vehicles where user is responsible."""
    from data_layer.db import fetch_all
    rows = fetch_all(
        f"""SELECT vi.id, vi.title, vi.severity, vi.status, vi.vehicle_id,
                  v.name as vehicle_name
           FROM {SCHEMA}.vehicle_issues vi
           JOIN {SCHEMA}.vehicles v ON v.id = vi.vehicle_id
           WHERE vi.status != 'fixed'
             AND (CASE WHEN v.responsible_user != '' THEN v.responsible_user ELSE v.created_by END) = %s
           ORDER BY
             CASE vi.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1
                              WHEN 'moderate' THEN 2 ELSE 3 END,
             vi.created_at DESC""",
        (user_id,),
    )
    return [{"source_type": "auto_issue", "source_id": r["id"],
             "title": r["title"], "severity": r["severity"],
             "status": r["status"],
             "detail": r.get("vehicle_name") or "",
             "vehicle_id": r.get("vehicle_id") or ""} for r in rows]


# ---------------------------------------------------------------------------
# Activity checker
# ---------------------------------------------------------------------------

def _is_auto_issue_active(source_id: str) -> bool:
    """Check if a vehicle issue is still open (not fixed)."""
    row = _pub_fetch_one(
        f"SELECT status FROM {SCHEMA}.vehicle_issues WHERE id = %s",
        (source_id,),
    )
    return bool(row and row["status"] != "fixed")


# ---------------------------------------------------------------------------
# Vehicle nag provider
# ---------------------------------------------------------------------------

def _get_responsible_user(vehicle: dict) -> str:
    return vehicle.get("responsible_user") or vehicle.get("created_by") or ""


def _vehicle_label(v: dict) -> str:
    parts = [str(v.get("year") or ""), v.get("make") or "", v.get("model") or ""]
    label = " ".join(p for p in parts if p).strip()
    return label or v.get("name") or v.get("id") or "Vehicle"


def _check_missing_fields(vehicle: dict) -> list[str]:
    """Return list of human-readable names for missing/empty fields."""
    checks = [
        ("Year", vehicle.get("year")),
        ("Make", vehicle.get("make")),
        ("Model", vehicle.get("model")),
        ("Trim", vehicle.get("trim_level")),
        ("Color", vehicle.get("color")),
        ("Odometer", vehicle.get("odometer")),
        ("License Plate", vehicle.get("license_plate")),
        ("VIN", vehicle.get("vin")),
    ]
    missing = []
    for name, val in checks:
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    return missing


def _check_oil_change_schedule(vehicle_id: str) -> str | None:
    """Return a finding string if no oil change schedule exists.
    Skip if oil_change_tracking exists (mileage tracking replaces schedule).
    """
    from apps.auto.data import get_oil_tracking
    if get_oil_tracking(vehicle_id):
        return None
    rows = _pub_fetch_all(
        """SELECT title FROM public.schedules
           WHERE linked_entity_type = 'vehicle'
             AND linked_entity_id = %s
             AND active = TRUE""",
        (vehicle_id,),
    )
    for r in rows:
        title = (r.get("title") or "").lower()
        if "oil change" in title or _OIL_PATTERN.search(title):
            return None
    return "No oil change schedule set up"


def _check_overdue_maintenance(vehicle_id: str) -> list[str]:
    """Return list of overdue schedule finding strings."""
    now = datetime.now(get_timezone())
    rows = _pub_fetch_all(
        """SELECT title, next_due FROM public.schedules
           WHERE linked_entity_type = 'vehicle'
             AND linked_entity_id = %s
             AND active = TRUE
             AND next_due IS NOT NULL
             AND next_due < %s""",
        (vehicle_id, now),
    )
    findings = []
    for r in rows:
        title = r.get("title") or "Maintenance"
        next_due = r["next_due"]
        if isinstance(next_due, str):
            next_due = datetime.fromisoformat(next_due)
        delta = now - next_due
        if delta.days > 0:
            when = f"{delta.days}d overdue"
        else:
            hours = int(delta.total_seconds() / 3600)
            when = f"{hours}h overdue" if hours > 0 else "overdue"
        findings.append(f"Overdue: {title} — {when}")
    return findings


def _check_stale_condition(vehicle_id: str) -> str | None:
    """Return a finding string if condition report is missing or stale."""
    row = _pub_fetch_one(
        f"""SELECT date_recorded FROM {SCHEMA}.vehicle_conditions
            WHERE vehicle_id = %s ORDER BY date_recorded DESC LIMIT 1""",
        (vehicle_id,),
    )
    if not row:
        return "No condition report on file"
    date_recorded = row["date_recorded"]
    if isinstance(date_recorded, str):
        from datetime import date as _date
        date_recorded = _date.fromisoformat(date_recorded)
    today = datetime.now(get_timezone()).date()
    months_ago = (today.year - date_recorded.year) * 12 + (today.month - date_recorded.month)
    if months_ago >= STALE_MONTHS:
        return f"Last condition report is {months_ago} months old ({date_recorded.isoformat()})"
    return None


def _check_stale_valuation(vehicle_id: str) -> str | None:
    """Return a finding string if valuation is missing or stale."""
    row = _pub_fetch_one(
        f"""SELECT date_recorded FROM {SCHEMA}.vehicle_valuations
            WHERE vehicle_id = %s ORDER BY date_recorded DESC LIMIT 1""",
        (vehicle_id,),
    )
    if not row:
        return "No valuation on file"
    date_recorded = row["date_recorded"]
    if isinstance(date_recorded, str):
        from datetime import date as _date
        date_recorded = _date.fromisoformat(date_recorded)
    today = datetime.now(get_timezone()).date()
    months_ago = (today.year - date_recorded.year) * 12 + (today.month - date_recorded.month)
    if months_ago >= STALE_MONTHS:
        return f"Last valuation is {months_ago} months old ({date_recorded.isoformat()})"
    return None


def _check_oil_change_tracking(vehicle_id: str) -> list[str]:
    """Evaluate oil change mileage tracking and return nag findings."""
    from apps.auto.data import get_oil_tracking
    from datetime import date as _date, timedelta

    tracking = get_oil_tracking(vehicle_id)
    if not tracking:
        return []

    today = _date.today()

    # Already flagged as overdue — nag every day
    if tracking["is_due"]:
        cur = tracking.get("last_reported_mileage") or "?"
        due = tracking["next_due_mileage"]
        if isinstance(cur, int):
            return [f"Oil change overdue! Current: {cur:,} mi / Due: {due:,} mi"]
        return [f"Oil change overdue! Due at {due:,} mi"]

    # Still in cooldown
    cooldown_expires = _date.fromisoformat(tracking["cooldown_expires"]) if tracking["cooldown_expires"] else today
    if today < cooldown_expires:
        return []

    # Already checked mileage within the last 30 days
    if tracking["last_mileage_check"]:
        last_check = _date.fromisoformat(tracking["last_mileage_check"])
        if (today - last_check) < timedelta(days=30):
            return []

    due = tracking["next_due_mileage"]
    last_mi = tracking.get("last_reported_mileage")

    # If we have a recent mileage reading, show remaining estimate
    if last_mi and isinstance(last_mi, int):
        remaining = due - last_mi
        if remaining <= 500:
            return [f"Oil change almost due — ~{remaining:,} mi remaining (due at {due:,} mi). Enter mileage to update."]

    return [f"Enter mileage to check oil change status (due at {due:,} mi)"]


def _build_nag_message(vehicle_findings: list[tuple[dict, list[str]]]) -> str:
    """Format a consolidated nag message for one responsible user."""
    lines = ["🚗 Vehicle Nag\n"]
    for vehicle, findings in vehicle_findings:
        label = _vehicle_label(vehicle)
        lines.append(f"**{label}**")
        for f in findings:
            lines.append(f"  • {f}")
        lines.append("")
    return "\n".join(lines).strip()


async def _vehicle_nag_provider() -> list[dict]:
    """Check all vehicles for nag-worthy findings.

    Returns list of nag items ready for the platform to deliver.
    Each item = {recipient, message, source_type, source_id}.
    Groups vehicles by responsible_user, builds one message per user.
    """
    from apps.auto.data import get_all_vehicles

    vehicles = await asyncio.to_thread(get_all_vehicles)
    if not vehicles:
        return []

    # Group by responsible user
    by_user: dict[str, list[dict]] = defaultdict(list)
    for v in vehicles:
        user = _get_responsible_user(v)
        if user:
            by_user[user].append(v)

    nag_items = []
    for responsible_user, user_vehicles in by_user.items():
        vehicle_findings = []
        for v in user_vehicles:
            vid = v["id"]
            findings = []

            # 1. Missing fields
            missing = await asyncio.to_thread(_check_missing_fields, v)
            if missing:
                findings.append(f"Missing: {', '.join(missing)}")

            # 2. Oil change schedule
            oil = await asyncio.to_thread(_check_oil_change_schedule, vid)
            if oil:
                findings.append(oil)

            # 3. Overdue maintenance
            overdue = await asyncio.to_thread(_check_overdue_maintenance, vid)
            findings.extend(overdue)

            # 4. Stale condition
            cond = await asyncio.to_thread(_check_stale_condition, vid)
            if cond:
                findings.append(cond)

            # 5. Stale valuation
            val = await asyncio.to_thread(_check_stale_valuation, vid)
            if val:
                findings.append(val)

            # 6. Oil change mileage tracking
            oil_tracking = await asyncio.to_thread(_check_oil_change_tracking, vid)
            findings.extend(oil_tracking)

            if findings:
                vehicle_findings.append((v, findings))

        if vehicle_findings:
            message = _build_nag_message(vehicle_findings)
            nag_items.append({
                "recipient": responsible_user,
                "message": message,
                "source_type": "vehicle_nag",
                "source_id": responsible_user,
            })

    return nag_items
