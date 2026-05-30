"""Medical App Package — registers platform integrations at import time."""

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prioritize backlog providers
# ---------------------------------------------------------------------------

def _med_refill_backlog(user_id: str) -> list[dict]:
    """Medications that need to be ordered or are waiting to be filled."""
    try:
        from apps.medical import data as _dl
        from datetime import date
        meds = _dl.get_all_medications(active_only=True)
        today = date.today()
        result = []
        for m in meds:
            status = m.get("refill_status", "active")
            if status not in ("nagging", "ordered"):
                continue
            last_dose_str = m.get("last_dose_date") or ""
            detail = ""
            if last_dose_str:
                try:
                    last_dose = date.fromisoformat(last_dose_str)
                    days_left = (last_dose - today).days
                    if days_left < 0:
                        detail = f"{abs(days_left)}d overdue"
                    elif days_left == 0:
                        detail = "runs out today"
                    else:
                        detail = f"{days_left}d left"
                except ValueError:
                    pass
            label = "needs ordering" if status == "nagging" else "ordered, awaiting fill"
            result.append({
                "source_type": "med_refill",
                "source_id": m["id"],
                "title": f"{m['name']} — {label}",
                "category": "Medication",
                "detail": detail,
                "overdue": status == "nagging",
                "member_id": m.get("member_id"),
            })
        return result
    except Exception as e:
        logger.error("MEDICAL: med_refill backlog provider failed: %s", e)
        return []


def _treatment_backlog(user_id: str) -> list[dict]:
    """Active treatments due within 3 days."""
    try:
        from apps.medical import data as _dl
        from datetime import date
        treatments = _dl.get_due_treatments(days_ahead=3)
        today = date.today()
        result = []
        for t in treatments:
            due_str = t.get("next_due_at") or ""
            detail = ""
            overdue = False
            if due_str:
                try:
                    due_date = date.fromisoformat(due_str)
                    delta = (due_date - today).days
                    if delta < 0:
                        overdue = True
                        detail = f"{abs(delta)}d overdue"
                    elif delta == 0:
                        detail = "due today"
                    else:
                        detail = f"due in {delta}d"
                except ValueError:
                    pass
            result.append({
                "source_type": "med_treatment",
                "source_id": t["id"],
                "title": t["name"],
                "category": "Treatment",
                "detail": detail,
                "overdue": overdue,
                "member_id": t.get("member_id"),
            })
        return result
    except Exception as e:
        logger.error("MEDICAL: treatment backlog provider failed: %s", e)
        return []


def _followup_backlog(user_id: str) -> list[dict]:
    """Medical events with follow-up dates within 3 days."""
    try:
        from apps.medical import data as _dl
        from datetime import date
        events = _dl.get_pending_followups(days_ahead=3)
        today = date.today()
        result = []
        for ev in events:
            due_str = ev.get("follow_up_date") or ""
            detail = ""
            overdue = False
            if due_str:
                try:
                    due_date = date.fromisoformat(due_str)
                    delta = (due_date - today).days
                    if delta < 0:
                        overdue = True
                        detail = f"{abs(delta)}d overdue"
                    elif delta == 0:
                        detail = "today"
                    else:
                        detail = f"in {delta}d"
                except ValueError:
                    pass
            result.append({
                "source_type": "med_followup",
                "source_id": ev["id"],
                "title": f"Follow-up: {ev['title']}",
                "category": "Follow-up",
                "detail": detail,
                "overdue": overdue,
                "follow_up_notes": ev.get("follow_up_notes"),
                "member_id": ev.get("member_id"),
            })
        return result
    except Exception as e:
        logger.error("MEDICAL: followup backlog provider failed: %s", e)
        return []


def _lab_missing_results_backlog(user_id: str) -> list[dict]:
    """Lab events older than 7 days with no results entered."""
    try:
        from apps.medical import data as _dl
        from datetime import date
        events = _dl.get_lab_events_missing_results(days_old=7)
        today = date.today()
        result = []
        for ev in events:
            event_date_str = ev.get("event_date") or ""
            detail = ""
            try:
                days_ago = (today - date.fromisoformat(event_date_str)).days
                detail = f"{days_ago}d ago — no results entered"
            except ValueError:
                detail = "no results entered"
            result.append({
                "source_type": "med_lab_missing",
                "source_id": ev["id"],
                "title": f"Lab results missing: {ev['title']}",
                "category": "Lab Results",
                "detail": detail,
                "overdue": True,
                "member_id": ev.get("member_id"),
            })
        return result
    except Exception as e:
        logger.error("MEDICAL: lab_missing_results backlog provider failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Activity checkers
# ---------------------------------------------------------------------------

def _med_refill_is_active(med_id: str) -> bool:
    try:
        from apps.medical import data as _dl
        med = _dl.get_medication(med_id)
        return bool(med and med.get("active") and med.get("refill_status") in ("nagging", "ordered"))
    except Exception:
        return False


def _treatment_is_active(treatment_id: str) -> bool:
    try:
        from apps.medical import data as _dl
        t = _dl.get_treatment(treatment_id)
        return bool(t and t.get("active"))
    except Exception:
        return False


def _followup_is_active(event_id: str) -> bool:
    try:
        from apps.medical import data as _dl
        ev = _dl.get_event(event_id)
        return bool(ev and ev.get("follow_up_date"))
    except Exception:
        return False


def _lab_missing_is_active(event_id: str) -> bool:
    try:
        from apps.medical import data as _dl
        return not _dl.lab_event_has_results(event_id)
    except Exception:
        return False


def _appointment_backlog(user_id: str) -> list[dict]:
    """Upcoming appointments within the next 7 days."""
    try:
        from apps.medical import data as _dl
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from config import TIMEZONE
        tz = ZoneInfo(TIMEZONE)
        appts = _dl.get_upcoming_appointments(days_ahead=7)
        now = datetime.now(tz)
        result = []
        for a in appts:
            appt_at_str = a.get("appointment_at") or ""
            detail = ""
            overdue = False
            if appt_at_str:
                try:
                    dt = datetime.fromisoformat(appt_at_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_local = dt.astimezone(tz)
                    delta_secs = (dt - now.astimezone(timezone.utc)).total_seconds()
                    days = int(delta_secs // 86400)
                    if days == 0:
                        detail = f"today at {dt_local.strftime('%I:%M %p').lstrip('0')}"
                    elif days == 1:
                        detail = f"tomorrow at {dt_local.strftime('%I:%M %p').lstrip('0')}"
                    else:
                        detail = f"in {days}d ({dt_local.strftime('%m/%d')})"
                except ValueError:
                    pass
            member_name = a.get("member_name") or ""
            title = a.get("title") or ""
            provider = a.get("provider") or ""
            label = f"{member_name}: {title}" if member_name else title
            if provider:
                label += f" — {provider}"
            result.append({
                "source_type": "med_appointment",
                "source_id": a["id"],
                "title": label,
                "category": "Appointment",
                "detail": detail,
                "overdue": overdue,
                "member_id": a.get("member_id"),
            })
        return result
    except Exception as e:
        logger.error("MEDICAL: appointment backlog provider failed: %s", e)
        return []


def _appointment_is_active(appt_id: str) -> bool:
    try:
        from apps.medical import data as _dl
        a = _dl.get_appointment(appt_id)
        return bool(a and not a.get("cancelled"))
    except Exception:
        return False


def _equipment_backlog(user_id: str) -> list[dict]:
    """Medical equipment tasks overdue or due within 7 days."""
    try:
        from apps.medical import data as _dl
        from datetime import date
        tasks = _dl.get_overdue_equip_tasks(days_ahead=7)
        today = date.today()
        result = []
        for t in tasks:
            due_str = t.get("next_due_at") or ""
            overdue = False
            detail = ""
            if due_str:
                try:
                    due_date = date.fromisoformat(due_str)
                    delta = (due_date - today).days
                    if delta < 0:
                        overdue = True
                        detail = f"{abs(delta)}d overdue"
                    elif delta == 0:
                        detail = "due today"
                    else:
                        detail = f"due in {delta}d"
                except ValueError:
                    pass
            equip_name = t.get("equipment_name") or ""
            member_name = t.get("member_name") or ""
            label = f"{equip_name}: {t['name']}" if equip_name else t["name"]
            result.append({
                "source_type": "med_equip_task",
                "source_id": t["id"],
                "title": label,
                "category": f"Equipment — {member_name}" if member_name else "Equipment",
                "detail": detail,
                "overdue": overdue,
                "member_id": t.get("member_id"),
            })
        return result
    except Exception as e:
        logger.error("MEDICAL: equipment backlog provider failed: %s", e)
        return []


def _equipment_task_is_active(task_id: str) -> bool:
    try:
        from apps.medical import data as _dl
        t = _dl.get_equip_task(task_id)
        return bool(t and t.get("active"))
    except Exception:
        return False


async def _equipment_maintenance_nag_provider() -> list[dict]:
    """Nag admin users when equipment maintenance tasks are overdue."""
    try:
        from apps.medical import data as _dl
        import asyncio
        from datetime import date
        tasks = await asyncio.to_thread(_dl.get_overdue_equip_tasks, 0)
    except Exception as e:
        logger.error("MEDICAL EQUIP NAG: failed to fetch tasks: %s", e)
        return []

    from datetime import date
    today = date.today()
    overdue = [
        t for t in tasks
        if t.get("next_due_at") and date.fromisoformat(t["next_due_at"]) < today
    ]
    if not overdue:
        return []

    try:
        from data_layer.users import get_users_with_any_role
        import asyncio
        admin_users = [
            user["name"]
            for user in await asyncio.to_thread(get_users_with_any_role, "admin")
        ]
    except Exception as e:
        logger.error("MEDICAL EQUIP NAG: failed to fetch admin users: %s", e)
        return []

    if not admin_users:
        return []

    lines = [f"🏥 Medical Equipment Maintenance — {len(overdue)} overdue task(s):\n"]
    for t in overdue:
        due_str = t.get("next_due_at") or ""
        days_str = ""
        if due_str:
            delta = (today - date.fromisoformat(due_str)).days
            days_str = f" — {delta}d overdue"
        equip = t.get("equipment_name") or ""
        member = t.get("member_name") or ""
        prefix = f"{member}'s {equip}" if member and equip else (equip or member)
        lines.append(f"  • {prefix}: {t['name']}{days_str}")
    message = "\n".join(lines)

    return [
        {
            "recipient": user,
            "message": message,
            "source_type": "med_equip_nag",
            "source_id": user,
        }
        for user in admin_users
    ]


async def _unlogged_appointment_nag_provider() -> list[dict]:
    """Daily nag for every past non-cancelled appointment that has no linked event."""
    try:
        from apps.medical import data as _dl
        import asyncio
        appts = await asyncio.to_thread(_dl.get_past_appointments_without_events)
    except Exception as e:
        logger.error("MEDICAL UNLOGGED NAG: failed to fetch appointments: %s", e)
        return []

    if not appts:
        return []

    try:
        from data_layer.users import get_users_with_any_role
        import asyncio
        admin_users = [
            user["name"]
            for user in await asyncio.to_thread(get_users_with_any_role, "admin")
        ]
    except Exception as e:
        logger.error("MEDICAL UNLOGGED NAG: failed to fetch admin users: %s", e)
        return []

    if not admin_users:
        return []

    from datetime import datetime, timezone
    lines = [f"📋 Medical Visit Summary Needed — {len(appts)} appointment(s) have no logged results:\n"]
    for a in appts:
        member = a.get("member_name") or a.get("member_id") or ""
        title = a.get("title") or ""
        appt_at = a.get("appointment_at") or ""
        date_str = ""
        if appt_at:
            try:
                dt = datetime.fromisoformat(appt_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%-m/%-d/%Y")
            except Exception:
                date_str = appt_at[:10]
        prefix = f"{member}: " if member else ""
        lines.append(f"  • {prefix}{title} ({date_str})")
    message = "\n".join(lines)

    return [
        {
            "recipient": user,
            "message": message,
            "source_type": "med_unlogged_appt_nag",
            "source_id": user,
        }
        for user in admin_users
    ]


async def _appointment_reminder_provider():
    """Fire 24h and 2h appointment reminders.

    Handles notification creation directly (using DB flags as dedup),
    then returns an empty list so the nag registry does no further work.
    """
    try:
        from apps.medical import data as _dl
        from app_platform.notifications import create_notification
        from data_layer.users import get_human_users
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from config import TIMEZONE

        due = _dl.get_appointments_due_for_notification()
        if not due:
            return []

        tz = ZoneInfo(TIMEZONE)
        users = get_human_users()

        for item in due:
            kind = item["notify_kind"]
            member_name = item.get("member_name") or ""
            title = item.get("title") or "Appointment"
            provider = item.get("provider") or ""
            appt_at_str = item.get("appointment_at") or ""

            time_str = ""
            date_str = ""
            try:
                dt = datetime.fromisoformat(appt_at_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_local = dt.astimezone(tz)
                time_str = dt_local.strftime("%I:%M %p").lstrip("0")
                date_str = dt_local.strftime("%a %m/%d")
            except Exception:
                time_str = appt_at_str
                date_str = ""

            if kind == "24h":
                lines = [f"📅 Appointment tomorrow ({date_str}): {title}"]
                if member_name:
                    lines.append(f"  For: {member_name}")
                if provider:
                    lines.append(f"  With: {provider}")
                lines.append(f"  Time: {time_str}")
                source_type = "med_appt_24h"
            else:
                lines = [f"⏰ Appointment in ~2 hours: {title}"]
                if member_name:
                    lines.append(f"  For: {member_name}")
                if provider:
                    lines.append(f"  With: {provider}")
                lines.append(f"  Time: {time_str} ({date_str})")
                source_type = "med_appt_2h"

            msg = "\n".join(lines)

            _dl.mark_appointment_notified(item["id"], kind)

            for user in users:
                try:
                    from tools.pushover_tool import is_pushover_user
                    channel = "both" if is_pushover_user(user["name"]) else "discord"
                except Exception:
                    channel = "discord"

                create_notification(
                    recipient=user["name"],
                    message=msg,
                    source_type=source_type,
                    source_id=item["id"],
                    channel=channel,
                    delivered=False,
                )
                logger.info("MEDICAL: Appointment %s notification sent to %s (%s)",
                            kind, user["name"], item["id"])
    except Exception as e:
        logger.error("MEDICAL: appointment reminder provider failed: %s", e)
    return []


# ---------------------------------------------------------------------------
# Register with platform
# ---------------------------------------------------------------------------

try:
    from apps.prioritize.data import register_backlog_provider, register_activity_checker
    register_backlog_provider("med_refills", _med_refill_backlog)
    register_backlog_provider("med_treatments", _treatment_backlog)
    register_backlog_provider("med_followups", _followup_backlog)
    register_backlog_provider("med_lab_missing", _lab_missing_results_backlog)
    register_backlog_provider("med_appointments", _appointment_backlog)
    register_backlog_provider("med_equipment", _equipment_backlog)
    register_activity_checker("med_refill", _med_refill_is_active)
    register_activity_checker("med_treatment", _treatment_is_active)
    register_activity_checker("med_followup", _followup_is_active)
    register_activity_checker("med_lab_missing", _lab_missing_is_active)
    register_activity_checker("med_appointment", _appointment_is_active)
    register_activity_checker("med_equip_task", _equipment_task_is_active)
except Exception as e:
    logger.warning("MEDICAL: could not register prioritize providers: %s", e)

try:
    from nag_registry import register_nag_provider
    register_nag_provider("med_appointments", _appointment_reminder_provider)
    register_nag_provider("med_equipment_maintenance", _equipment_maintenance_nag_provider)
    register_nag_provider("med_unlogged_appts", _unlogged_appointment_nag_provider)
except Exception as e:
    logger.warning("MEDICAL: could not register nag providers: %s", e)
