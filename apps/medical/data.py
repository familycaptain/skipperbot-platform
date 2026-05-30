"""Medical App — Data Layer
===========================
CRUD for members, medications, events, treatments, lab tests, and lab results.
All tables live in the app_medical schema.
"""

import logging
from datetime import date, datetime, timezone, timedelta

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
)
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_medical"

_MEDICATION_HINT = (
    "Focus on: family member name, medication name, dosage notes, prescriber, pharmacy, "
    "start/end dates, active status, refill status, and any notes."
)
_EVENT_HINT = (
    "Focus on: family member name, event type (visit/lab/procedure/specialist/emergency), "
    "date, provider/doctor, summary, follow-up date and notes, and any tags."
)
_TREATMENT_HINT = (
    "Focus on: family member name, treatment name, description, interval in days, "
    "last done date, next due date, active status, and notes."
)
_TREATMENT_LOG_HINT = (
    "Focus on: treatment name, date performed, any medication used, and notes."
)
_LAB_RESULT_HINT = (
    "Focus on: family member name, lab test name, result date, numeric value, "
    "and whether it falls inside or outside the normal range."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _ts(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ===========================================================================
# MEMBERS
# ===========================================================================

def _member_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "notes": row.get("notes") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def get_all_members() -> list[dict]:
    rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM medical_members ORDER BY name")
    return [_member_row(r) for r in rows]


def get_member(member_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_members WHERE id = %s", (member_id,))
    return _member_row(row) if row else None


def get_member_by_name(name: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM medical_members WHERE lower(name) = lower(%s)", (name,)
    )
    return _member_row(row) if row else None


def create_member(member: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_members (id, name, notes, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (member["id"], member.get("name", ""), member.get("notes", ""), _now(), _now()),
    )
    result = _member_row(row) if row else None
    if result:
        digest_record(app_id="medical", entity_type="family member", action="created",
                      entity_id=result["id"], record=result, by=member.get("created_by", ""),
                      context_hint="Focus on: family member name added to medical records.")
    return result


def update_member(member_id: str, updates: dict) -> bool:
    allowed = {"name", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [member_id]
    n = execute_in_schema(SCHEMA, f"UPDATE medical_members SET {set_clause} WHERE id = %s", tuple(params))
    if n > 0:
        updated = get_member(member_id)
        if updated:
            digest_record(app_id="medical", entity_type="family member", action="updated",
                          entity_id=member_id, record=updated, by=updates.get("updated_by", ""),
                          context_hint="Focus on: family member name updated in medical records.")
    return n > 0


def delete_member(member_id: str) -> bool:
    member = get_member(member_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_members WHERE id = %s", (member_id,))
    if n > 0 and member:
        digest_record(app_id="medical", entity_type="family member", action="deleted",
                      entity_id=member_id, record=member, by="")
    return n > 0


# ===========================================================================
# MEDICATIONS
# ===========================================================================

def _med_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "member_id": row.get("member_id") or "",
        "name": row.get("name") or "",
        "dosage_notes": row.get("dosage_notes") or "",
        "prescriber": row.get("prescriber") or "",
        "pharmacy": row.get("pharmacy") or "",
        "start_date": _date(row.get("start_date")),
        "end_date": _date(row.get("end_date")),
        "active": bool(row.get("active", True)),
        "last_dose_date": _date(row.get("last_dose_date")),
        "duration_days": row.get("duration_days"),
        "reminder_days": row.get("reminder_days") or 7,
        "refill_status": row.get("refill_status") or "active",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def get_all_medications(member_id: str = "", active_only: bool = True) -> list[dict]:
    if member_id and active_only:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_medications WHERE member_id = %s AND active = TRUE ORDER BY last_dose_date ASC NULLS LAST, name",
            (member_id,),
        )
    elif member_id:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_medications WHERE member_id = %s ORDER BY active DESC, last_dose_date ASC NULLS LAST, name",
            (member_id,),
        )
    elif active_only:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_medications WHERE active = TRUE ORDER BY last_dose_date ASC NULLS LAST, name",
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_medications ORDER BY active DESC, last_dose_date ASC NULLS LAST, name",
        )
    return [_med_row(r) for r in rows]


def get_medication(med_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_medications WHERE id = %s", (med_id,))
    return _med_row(row) if row else None


def create_medication(med: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_medications
               (id, member_id, name, dosage_notes, prescriber, pharmacy,
                start_date, end_date, active, last_dose_date, duration_days,
                reminder_days, refill_status, notes, created_by, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            med["id"], med["member_id"], med.get("name", ""),
            med.get("dosage_notes", ""), med.get("prescriber", ""),
            med.get("pharmacy", ""), med.get("start_date") or None,
            med.get("end_date") or None, med.get("active", True),
            med.get("last_dose_date") or None, med.get("duration_days"),
            med.get("reminder_days", 7), med.get("refill_status", "active"),
            med.get("notes", ""), med.get("created_by", ""), _now(), _now(),
        ),
    )
    result = _med_row(row) if row else None
    if result:
        digest_record(app_id="medical", entity_type="medication", action="created",
                      entity_id=result["id"], record=result,
                      by=med.get("created_by", ""), context_hint=_MEDICATION_HINT)
    return result


def update_medication(med_id: str, updates: dict) -> dict | None:
    """Update medication. Handles nag side-effects for refill-related fields."""
    allowed = {
        "name", "dosage_notes", "prescriber", "pharmacy", "start_date", "end_date",
        "active", "last_dose_date", "duration_days", "reminder_days", "refill_status",
        "notes",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_medication(med_id)

    # Nag side-effects
    current = get_medication(med_id)
    if current:
        # If deactivating — reset status to active (stops nagging)
        if fields.get("active") is False:
            fields["refill_status"] = "active"
        # If last_dose_date is being cleared — reset status
        elif "last_dose_date" in fields and not fields["last_dose_date"]:
            fields["refill_status"] = "active"
        # If last_dose_date or duration_days changed and currently nagging/ordered,
        # check if nag should still be active
        elif ("last_dose_date" in fields or "duration_days" in fields):
            new_last_dose = fields.get("last_dose_date") or current.get("last_dose_date")
            reminder_days = fields.get("reminder_days") or current.get("reminder_days") or 7
            if new_last_dose and current.get("refill_status") in ("nagging", "ordered"):
                try:
                    last_dose = date.fromisoformat(str(new_last_dose))
                    days_left = (last_dose - date.today()).days
                    if days_left > reminder_days:
                        fields["refill_status"] = "active"
                except (ValueError, TypeError):
                    pass

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [med_id]
    n = execute_in_schema(SCHEMA, f"UPDATE medical_medications SET {set_clause} WHERE id = %s", tuple(params))
    if n > 0:
        updated = get_medication(med_id)
        if updated:
            digest_record(app_id="medical", entity_type="medication", action="updated",
                          entity_id=med_id, record=updated,
                          by=updates.get("updated_by", ""), context_hint=_MEDICATION_HINT)
        return updated
    return None


def mark_medication_ordered(med_id: str) -> dict | None:
    n = execute_in_schema(
        SCHEMA,
        "UPDATE medical_medications SET refill_status = 'ordered', updated_at = %s WHERE id = %s AND active = TRUE",
        (_now(), med_id),
    )
    return get_medication(med_id) if n > 0 else None


def mark_medication_filled(med_id: str) -> dict | None:
    """Advance last_dose_date by duration_days, reset refill_status to active."""
    med = get_medication(med_id)
    if not med:
        return None
    last_dose_str = med.get("last_dose_date")
    duration = med.get("duration_days")
    if not last_dose_str or not duration:
        return None
    try:
        new_last_dose = date.fromisoformat(last_dose_str) + timedelta(days=duration)
    except ValueError:
        return None
    n = execute_in_schema(
        SCHEMA,
        """UPDATE medical_medications
              SET last_dose_date = %s, refill_status = 'active', updated_at = %s
            WHERE id = %s""",
        (new_last_dose.isoformat(), _now(), med_id),
    )
    return get_medication(med_id) if n > 0 else None


def delete_medication(med_id: str) -> bool:
    med = get_medication(med_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_medications WHERE id = %s", (med_id,))
    if n > 0 and med:
        digest_record(app_id="medical", entity_type="medication", action="deleted",
                      entity_id=med_id, record=med, by="")
    return n > 0


def get_medications_needing_nag() -> list[dict]:
    """Return active meds where last_dose_date is within reminder_days (for nag job)."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM medical_medications
            WHERE active = TRUE
              AND last_dose_date IS NOT NULL
              AND (
                (refill_status = 'active'   AND last_dose_date - CURRENT_DATE <= reminder_days)
                OR refill_status IN ('nagging', 'ordered')
              )
            ORDER BY last_dose_date ASC""",
    )
    return [_med_row(r) for r in rows]


def set_medication_nagging(med_id: str) -> None:
    execute_in_schema(
        SCHEMA,
        "UPDATE medical_medications SET refill_status = 'nagging', updated_at = %s WHERE id = %s",
        (_now(), med_id),
    )


def get_upcoming_refills(days: int = 14) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT m.*, mb.name AS member_name
             FROM medical_medications m
             JOIN medical_members mb ON mb.id = m.member_id
            WHERE m.active = TRUE
              AND m.last_dose_date IS NOT NULL
              AND m.last_dose_date <= CURRENT_DATE + %s
            ORDER BY m.last_dose_date ASC""",
        (days,),
    )
    result = []
    for r in rows:
        d = _med_row(r)
        d["member_name"] = r.get("member_name") or ""
        result.append(d)
    return result


# ===========================================================================
# MEDICAL EVENTS
# ===========================================================================

def _event_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "member_id": row.get("member_id") or "",
        "event_type": row.get("event_type") or "visit",
        "title": row.get("title") or "",
        "event_date": _date(row.get("event_date")),
        "provider": row.get("provider") or "",
        "summary": row.get("summary") or "",
        "follow_up_date": _date(row.get("follow_up_date")),
        "follow_up_notes": row.get("follow_up_notes") or "",
        "tags": list(row.get("tags") or []),
        "notes": row.get("notes") or "",
        "appointment_id": row.get("appointment_id") or None,
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def get_all_events(member_id: str = "", event_type: str = "", since: str = "") -> list[dict]:
    conditions = ["TRUE"]
    params: list = []
    if member_id:
        conditions.append("member_id = %s")
        params.append(member_id)
    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if since:
        conditions.append("event_date >= %s")
        params.append(since)
    where = " AND ".join(conditions)
    rows = fetch_all_in_schema(
        SCHEMA, f"SELECT * FROM medical_events WHERE {where} ORDER BY event_date DESC, created_at DESC", tuple(params)
    )
    return [_event_row(r) for r in rows]


def get_event(event_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_events WHERE id = %s", (event_id,))
    return _event_row(row) if row else None


def get_lab_events(member_id: str = "") -> list[dict]:
    """Return events of type 'lab' for linking to lab results."""
    if member_id:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_events WHERE event_type = 'lab' AND member_id = %s ORDER BY event_date DESC",
            (member_id,),
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_events WHERE event_type = 'lab' ORDER BY event_date DESC",
        )
    return [_event_row(r) for r in rows]


def create_event(event: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_events
               (id, member_id, event_type, title, event_date, provider, summary,
                follow_up_date, follow_up_notes, tags, notes, appointment_id,
                created_by, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            event["id"], event["member_id"], event.get("event_type", "visit"),
            event.get("title", ""), event.get("event_date"),
            event.get("provider", ""), event.get("summary", ""),
            event.get("follow_up_date") or None, event.get("follow_up_notes", ""),
            event.get("tags", []), event.get("notes", ""),
            event.get("appointment_id") or None,
            event.get("created_by", ""), _now(), _now(),
        ),
    )
    result = _event_row(row) if row else None
    if result:
        digest_record(app_id="medical", entity_type="medical event", action="created",
                      entity_id=result["id"], record=result,
                      by=event.get("created_by", ""), context_hint=_EVENT_HINT)
    return result


def update_event(event_id: str, updates: dict) -> dict | None:
    allowed = {
        "event_type", "title", "event_date", "provider", "summary",
        "follow_up_date", "follow_up_notes", "tags", "notes", "appointment_id",
    }
    _date_fields = {"event_date", "follow_up_date"}
    fields = {k: (None if k in _date_fields and v == "" else v) for k, v in updates.items() if k in allowed}
    if not fields:
        return get_event(event_id)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [event_id]
    n = execute_in_schema(SCHEMA, f"UPDATE medical_events SET {set_clause} WHERE id = %s", tuple(params))
    if n > 0:
        updated = get_event(event_id)
        if updated:
            digest_record(app_id="medical", entity_type="medical event", action="updated",
                          entity_id=event_id, record=updated,
                          by=updates.get("updated_by", ""), context_hint=_EVENT_HINT)
        return updated
    return None


def delete_event(event_id: str) -> bool:
    event = get_event(event_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_events WHERE id = %s", (event_id,))
    if n > 0 and event:
        digest_record(app_id="medical", entity_type="medical event", action="deleted",
                      entity_id=event_id, record=event, by="")
    return n > 0


def get_past_appointments_without_events(member_id: str = "") -> list[dict]:
    """Return non-cancelled past appointments that have no linked medical event."""
    conditions = [
        "a.cancelled = FALSE",
        "a.appointment_at < now()",
        "NOT EXISTS (SELECT 1 FROM medical_events e WHERE e.appointment_id = a.id)",
    ]
    params: list = []
    if member_id:
        conditions.append("a.member_id = %s")
        params.append(member_id)
    where = " AND ".join(conditions)
    rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT a.*, m.name AS member_name
           FROM medical_appointments a
           JOIN medical_members m ON a.member_id = m.id
           WHERE {where}
           ORDER BY a.appointment_at DESC""",
        tuple(params),
    )
    result = []
    for row in rows:
        appt = _appointment_row(row)
        appt["member_name"] = row.get("member_name") or ""
        result.append(appt)
    return result


def get_pending_followups(days_ahead: int = 3) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM medical_events
            WHERE follow_up_date IS NOT NULL
              AND follow_up_date <= CURRENT_DATE + %s
            ORDER BY follow_up_date ASC""",
        (days_ahead,),
    )
    return [_event_row(r) for r in rows]


# ===========================================================================
# TREATMENTS
# ===========================================================================

def _treatment_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "member_id": row.get("member_id") or "",
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "interval_days": row.get("interval_days"),
        "last_done_at": _date(row.get("last_done_at")),
        "next_due_at": _date(row.get("next_due_at")),
        "active": bool(row.get("active", True)),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def _treatment_log_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "treatment_id": row.get("treatment_id") or "",
        "done_at": _date(row.get("done_at")),
        "medication": row.get("medication") or "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
    }


def get_all_treatments(member_id: str = "", active_only: bool = True) -> list[dict]:
    conditions = []
    params: list = []
    if member_id:
        conditions.append("member_id = %s")
        params.append(member_id)
    if active_only:
        conditions.append("active = TRUE")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fetch_all_in_schema(
        SCHEMA,
        f"SELECT * FROM medical_treatments {where} ORDER BY next_due_at ASC NULLS LAST, name",
        tuple(params),
    )
    return [_treatment_row(r) for r in rows]


def get_treatment(treatment_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_treatments WHERE id = %s", (treatment_id,))
    return _treatment_row(row) if row else None


def create_treatment(treatment: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_treatments
               (id, member_id, name, description, interval_days,
                last_done_at, next_due_at, active, notes, created_by, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            treatment["id"], treatment["member_id"], treatment.get("name", ""),
            treatment.get("description", ""), treatment["interval_days"],
            treatment.get("last_done_at") or None, treatment.get("next_due_at") or None,
            treatment.get("active", True), treatment.get("notes", ""),
            treatment.get("created_by", ""), _now(), _now(),
        ),
    )
    result = _treatment_row(row) if row else None
    if result:
        digest_record(app_id="medical", entity_type="treatment", action="created",
                      entity_id=result["id"], record=result,
                      by=treatment.get("created_by", ""), context_hint=_TREATMENT_HINT)
    return result


def update_treatment(treatment_id: str, updates: dict) -> dict | None:
    allowed = {"name", "description", "interval_days", "last_done_at", "next_due_at", "active", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_treatment(treatment_id)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [treatment_id]
    n = execute_in_schema(SCHEMA, f"UPDATE medical_treatments SET {set_clause} WHERE id = %s", tuple(params))
    if n > 0:
        updated = get_treatment(treatment_id)
        if updated:
            digest_record(app_id="medical", entity_type="treatment", action="updated",
                          entity_id=treatment_id, record=updated,
                          by=updates.get("updated_by", ""), context_hint=_TREATMENT_HINT)
        return updated
    return None


def delete_treatment(treatment_id: str) -> bool:
    treatment = get_treatment(treatment_id)
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_treatments WHERE id = %s", (treatment_id,))
    if n > 0 and treatment:
        digest_record(app_id="medical", entity_type="treatment", action="deleted",
                      entity_id=treatment_id, record=treatment, by="")
    return n > 0


def log_treatment(log: dict) -> dict | None:
    """Log an instance of a treatment and advance next_due_at."""
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_treatment_log
               (id, treatment_id, done_at, medication, notes, created_by, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            log["id"], log["treatment_id"],
            log.get("done_at") or date.today().isoformat(),
            log.get("medication", ""), log.get("notes", ""),
            log.get("created_by", ""), _now(),
        ),
    )
    if not row:
        return None
    result = _treatment_log_row(row)
    # Advance next_due_at
    treatment = get_treatment(log["treatment_id"])
    if treatment and treatment.get("interval_days"):
        try:
            done = date.fromisoformat(str(log.get("done_at") or date.today().isoformat()))
            next_due = done + timedelta(days=treatment["interval_days"])
            execute_in_schema(
                SCHEMA,
                "UPDATE medical_treatments SET last_done_at = %s, next_due_at = %s, updated_at = %s WHERE id = %s",
                (done.isoformat(), next_due.isoformat(), _now(), log["treatment_id"]),
            )
        except (ValueError, TypeError):
            pass
    record_for_digest = dict(result)
    record_for_digest["treatment_name"] = treatment.get("name", "") if treatment else ""
    digest_record(app_id="medical", entity_type="treatment log", action="created",
                  entity_id=result["id"], record=record_for_digest,
                  by=log.get("created_by", ""), context_hint=_TREATMENT_LOG_HINT)
    return result


def get_all_treatment_logs(limit: int = 5000) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM medical_treatment_log ORDER BY done_at DESC LIMIT %s",
        (limit,),
    )
    return [_treatment_log_row(r) for r in rows]


def get_treatment_log(treatment_id: str, limit: int = 50) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM medical_treatment_log WHERE treatment_id = %s ORDER BY done_at DESC LIMIT %s",
        (treatment_id, limit),
    )
    return [_treatment_log_row(r) for r in rows]


def update_treatment_log_entry(log_id: str, updates: dict) -> dict | None:
    allowed = {"done_at", "medication", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return None
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [log_id]
    n = execute_in_schema(
        SCHEMA,
        f"UPDATE medical_treatment_log SET {set_clause} WHERE id = %s",
        tuple(params),
    )
    if n == 0:
        return None
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_treatment_log WHERE id = %s", (log_id,))
    return _treatment_log_row(row) if row else None


def delete_treatment_log_entry(log_id: str) -> bool:
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_treatment_log WHERE id = %s", (log_id,))
    return n > 0


def get_due_treatments(days_ahead: int = 7) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM medical_treatments
            WHERE active = TRUE
              AND next_due_at IS NOT NULL
              AND next_due_at <= CURRENT_DATE + %s
            ORDER BY next_due_at ASC""",
        (days_ahead,),
    )
    return [_treatment_row(r) for r in rows]


# ===========================================================================
# LAB TESTS (master list)
# ===========================================================================

def _lab_test_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "unit": row.get("unit") or "",
        "normal_min": row.get("normal_min"),
        "normal_max": row.get("normal_max"),
        "sort_order": row.get("sort_order") or 0,
        "notes": row.get("notes") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def get_all_lab_tests() -> list[dict]:
    rows = fetch_all_in_schema(SCHEMA, "SELECT * FROM medical_lab_tests ORDER BY sort_order, name")
    return [_lab_test_row(r) for r in rows]


def get_lab_test(test_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_lab_tests WHERE id = %s", (test_id,))
    return _lab_test_row(row) if row else None


def get_lab_test_by_name(name: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM medical_lab_tests WHERE lower(name) = lower(%s)", (name,)
    )
    return _lab_test_row(row) if row else None


def create_lab_test(test: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_lab_tests (id, name, unit, normal_min, normal_max, sort_order, notes, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            test["id"], test.get("name", ""), test.get("unit", ""),
            test.get("normal_min"), test.get("normal_max"),
            test.get("sort_order", 0), test.get("notes", ""), _now(), _now(),
        ),
    )
    return _lab_test_row(row) if row else None


def update_lab_test(test_id: str, updates: dict) -> dict | None:
    allowed = {"name", "unit", "normal_min", "normal_max", "sort_order", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_lab_test(test_id)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [test_id]
    n = execute_in_schema(SCHEMA, f"UPDATE medical_lab_tests SET {set_clause} WHERE id = %s", tuple(params))
    return get_lab_test(test_id) if n > 0 else None


def delete_lab_test(test_id: str) -> bool:
    """Only deletes if no results reference this test."""
    count_row = fetch_one_in_schema(
        SCHEMA, "SELECT COUNT(*) AS cnt FROM medical_lab_results WHERE lab_test_id = %s", (test_id,)
    )
    if count_row and count_row.get("cnt", 0) > 0:
        return False
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_lab_tests WHERE id = %s", (test_id,))
    return n > 0


# ===========================================================================
# LAB RESULTS
# ===========================================================================

def _lab_result_row(row: dict) -> dict:
    result = {
        "id": row["id"],
        "member_id": row.get("member_id") or "",
        "event_id": row.get("event_id") or "",
        "lab_test_id": row.get("lab_test_id") or "",
        "result_date": _date(row.get("result_date")),
        "value": row.get("value"),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
    }
    for key in (
        "member_name", "test_name", "unit", "normal_min", "normal_max",
        "sort_order", "event_title", "event_date", "event_provider",
    ):
        if key in row:
            result[key] = _date(row.get(key)) if key == "event_date" else row.get(key)
    return result


def get_lab_results(
    member_id: str = "",
    test_id: str = "",
    event_id: str = "",
    since: str = "",
    result_date: str = "",
    include_details: bool = False,
) -> list[dict]:
    conditions = ["TRUE"]
    params: list = []
    if member_id:
        conditions.append("r.member_id = %s" if include_details else "member_id = %s")
        params.append(member_id)
    if test_id:
        conditions.append("r.lab_test_id = %s" if include_details else "lab_test_id = %s")
        params.append(test_id)
    if event_id:
        conditions.append("r.event_id = %s" if include_details else "event_id = %s")
        params.append(event_id)
    if result_date:
        conditions.append("r.result_date = %s" if include_details else "result_date = %s")
        params.append(result_date)
    if since:
        conditions.append("r.result_date >= %s" if include_details else "result_date >= %s")
        params.append(since)
    where = " AND ".join(conditions)
    if include_details:
        rows = fetch_all_in_schema(
            SCHEMA,
            f"""SELECT r.*,
                       m.name AS member_name,
                       t.name AS test_name,
                       t.unit,
                       t.normal_min,
                       t.normal_max,
                       t.sort_order,
                       e.title AS event_title,
                       e.event_date AS event_date,
                       e.provider AS event_provider
                  FROM medical_lab_results r
                  JOIN medical_members m ON m.id = r.member_id
                  JOIN medical_lab_tests t ON t.id = r.lab_test_id
                  LEFT JOIN medical_events e ON e.id = r.event_id
                 WHERE {where}
                 ORDER BY r.result_date DESC, t.sort_order, t.name, r.created_at DESC""",
            tuple(params),
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            f"SELECT * FROM medical_lab_results WHERE {where} ORDER BY result_date DESC, created_at DESC",
            tuple(params),
        )
    return [_lab_result_row(r) for r in rows]


def create_lab_result(result: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_lab_results
               (id, member_id, event_id, lab_test_id, result_date, value, notes, created_by, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            result["id"], result["member_id"],
            result.get("event_id") or None, result["lab_test_id"],
            result["result_date"], result["value"],
            result.get("notes", ""), result.get("created_by", ""), _now(),
        ),
    )
    saved = _lab_result_row(row) if row else None
    if saved:
        digest_record(app_id="medical", entity_type="lab result", action="created",
                      entity_id=saved["id"], record=saved,
                      by=result.get("created_by", ""), context_hint=_LAB_RESULT_HINT)
    return saved


def update_lab_result(result_id: str, updates: dict) -> dict | None:
    allowed = {"event_id", "result_date", "value", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_lab_results WHERE id = %s", (result_id,))
        return _lab_result_row(row) if row else None
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [result_id]
    n = execute_in_schema(SCHEMA, f"UPDATE medical_lab_results SET {set_clause} WHERE id = %s", tuple(params))
    if n == 0:
        return None
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_lab_results WHERE id = %s", (result_id,))
    saved = _lab_result_row(row) if row else None
    if saved:
        digest_record(app_id="medical", entity_type="lab result", action="updated",
                      entity_id=result_id, record=saved,
                      by=updates.get("updated_by", ""), context_hint=_LAB_RESULT_HINT)
    return saved


def delete_lab_result(result_id: str) -> bool:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM medical_lab_results WHERE id = %s", (result_id,))
    lab_result = _lab_result_row(row) if row else None
    n = execute_in_schema(SCHEMA, "DELETE FROM medical_lab_results WHERE id = %s", (result_id,))
    if n > 0 and lab_result:
        digest_record(app_id="medical", entity_type="lab result", action="deleted",
                      entity_id=result_id, record=lab_result, by="")
    return n > 0


def delete_lab_results_by_date(member_id: str, result_date: str) -> int:
    """Delete all results for a member on a given date (delete row in UI)."""
    n = execute_in_schema(
        SCHEMA,
        "DELETE FROM medical_lab_results WHERE member_id = %s AND result_date = %s",
        (member_id, result_date),
    )
    return n


def get_lab_history(test_id: str, member_id: str = "") -> list[dict]:
    """Get historical results for a specific test, optionally filtered by member."""
    if member_id:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_lab_results WHERE lab_test_id = %s AND member_id = %s ORDER BY result_date ASC",
            (test_id, member_id),
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_lab_results WHERE lab_test_id = %s ORDER BY result_date ASC",
            (test_id,),
        )
    return [_lab_result_row(r) for r in rows]


def get_lab_events_missing_results(days_old: int = 7) -> list[dict]:
    """Return lab events older than days_old with no lab results linked to them."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT e.* FROM medical_events e
           WHERE e.event_type = 'lab'
             AND e.event_date <= (CURRENT_DATE - %s::int)
             AND NOT EXISTS (
                 SELECT 1 FROM medical_lab_results r WHERE r.event_id = e.id
             )
           ORDER BY e.event_date DESC""",
        (days_old,),
    )
    return [_event_row(r) for r in rows]


def lab_event_has_results(event_id: str) -> bool:
    """Return True if any lab results are linked to this event."""
    row = fetch_one_in_schema(
        SCHEMA,
        "SELECT COUNT(*) AS cnt FROM medical_lab_results WHERE event_id = %s",
        (event_id,),
    )
    return bool(row and row["cnt"] > 0)


# ===========================================================================
# SEARCH
# ===========================================================================

def search_medical(query: str, member_id: str = "") -> dict:
    """Search across medications and events."""
    q = f"%{query.lower()}%"
    member_filter = "AND member_id = %s" if member_id else ""
    member_param = [member_id] if member_id else []

    med_rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT * FROM medical_medications
            WHERE active = TRUE
              AND (lower(name) LIKE %s OR lower(dosage_notes) LIKE %s
                   OR lower(prescriber) LIKE %s OR lower(notes) LIKE %s)
              {member_filter}
            ORDER BY name""",
        (q, q, q, q, *member_param),
    )
    event_rows = fetch_all_in_schema(
        SCHEMA,
        f"""SELECT * FROM medical_events
            WHERE (lower(title) LIKE %s OR lower(summary) LIKE %s
                   OR lower(provider) LIKE %s OR lower(notes) LIKE %s)
              {member_filter}
            ORDER BY event_date DESC""",
        (q, q, q, q, *member_param),
    )
    return {
        "medications": [_med_row(r) for r in med_rows],
        "events": [_event_row(r) for r in event_rows],
    }


# ===========================================================================
# APPOINTMENTS
# ===========================================================================

_APPOINTMENT_HINT = (
    "Focus on: family member name, appointment title, date and time, provider/doctor, "
    "location, appointment type, and any notes."
)


def _appointment_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "member_id": row.get("member_id") or "",
        "title": row.get("title") or "",
        "appointment_at": _ts(row.get("appointment_at")),
        "provider": row.get("provider") or "",
        "location": row.get("location") or "",
        "appointment_type": row.get("appointment_type") or "visit",
        "notes": row.get("notes") or "",
        "cancelled": bool(row.get("cancelled", False)),
        "notified_24h": bool(row.get("notified_24h", False)),
        "notified_2h": bool(row.get("notified_2h", False)),
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def get_all_appointments(member_id: str = "", include_past: bool = False,
                         include_cancelled: bool = False) -> list[dict]:
    conditions = []
    params: list = []

    if member_id:
        conditions.append("member_id = %s")
        params.append(member_id)
    if not include_past:
        conditions.append("appointment_at >= now() - interval '1 hour'")
    if not include_cancelled:
        conditions.append("cancelled = FALSE")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = "ORDER BY appointment_at ASC"
    rows = fetch_all_in_schema(
        SCHEMA,
        f"SELECT * FROM medical_appointments {where} {order}",
        tuple(params),
    )
    return [_appointment_row(r) for r in rows]


def get_appointment(appt_id: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM medical_appointments WHERE id = %s", (appt_id,)
    )
    return _appointment_row(row) if row else None


def create_appointment(appt: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_appointments
               (id, member_id, title, appointment_at, provider, location,
                appointment_type, notes, cancelled, notified_24h, notified_2h,
                created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, FALSE, %s, %s, %s)
           RETURNING *""",
        (
            appt["id"], appt["member_id"], appt["title"], appt["appointment_at"],
            appt.get("provider", ""), appt.get("location", ""),
            appt.get("appointment_type", "visit"), appt.get("notes", ""),
            appt.get("created_by", ""), _now(), _now(),
        ),
    )
    result = _appointment_row(row) if row else None
    if result:
        digest_record(
            app_id="medical", entity_type="appointment", action="created",
            entity_id=result["id"], record=result, by=appt.get("created_by", ""),
            context_hint=_APPOINTMENT_HINT,
        )
    return result


def update_appointment(appt_id: str, updates: dict) -> dict | None:
    allowed = {"title", "appointment_at", "provider", "location",
               "appointment_type", "notes", "cancelled"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_appointment(appt_id)
    if "appointment_at" in fields:
        fields["notified_24h"] = False
        fields["notified_2h"] = False
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [appt_id]
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE medical_appointments SET {set_clause} WHERE id = %s RETURNING *",
        tuple(params),
    )
    result = _appointment_row(row) if row else None
    if result:
        digest_record(
            app_id="medical", entity_type="appointment", action="updated",
            entity_id=appt_id, record=result, by=updates.get("updated_by", ""),
            context_hint=_APPOINTMENT_HINT,
        )
    return result


def delete_appointment(appt_id: str) -> bool:
    appt = get_appointment(appt_id)
    n = execute_in_schema(
        SCHEMA, "DELETE FROM medical_appointments WHERE id = %s", (appt_id,)
    )
    if n > 0 and appt:
        digest_record(
            app_id="medical", entity_type="appointment", action="deleted",
            entity_id=appt_id, record=appt, by="",
        )
    return n > 0


def get_appointments_due_for_notification() -> list[dict]:
    """Return appointments that need a 24h or 2h notification fired.

    Returns one dict per notification that should fire, with an extra
    `notify_kind` field ('24h' or '2h') and `member_name`.
    """
    sql = """
        SELECT a.*, m.name AS member_name,
               EXTRACT(EPOCH FROM (a.appointment_at - now())) AS secs_until
        FROM medical_appointments a
        JOIN medical_members m ON a.member_id = m.id
        WHERE NOT a.cancelled
          AND a.appointment_at > now()
          AND (
                (a.notified_24h = FALSE AND (a.appointment_at - now()) <= interval '24 hours')
             OR (a.notified_2h  = FALSE AND (a.appointment_at - now()) <= interval '2 hours')
          )
        ORDER BY a.appointment_at ASC
    """
    rows = fetch_all_in_schema(SCHEMA, sql)
    result = []
    for row in rows:
        appt = _appointment_row(row)
        appt["member_name"] = row.get("member_name") or ""
        secs = float(row.get("secs_until") or 0)
        if not row.get("notified_2h") and secs <= 7200:
            item = dict(appt)
            item["notify_kind"] = "2h"
            result.append(item)
        if not row.get("notified_24h") and secs <= 86400:
            item = dict(appt)
            item["notify_kind"] = "24h"
            result.append(item)
    return result


def mark_appointment_notified(appt_id: str, kind: str) -> None:
    """Mark a notification as sent so it won't fire again."""
    field = "notified_2h" if kind == "2h" else "notified_24h"
    execute_in_schema(
        SCHEMA,
        f"UPDATE medical_appointments SET {field} = TRUE, updated_at = %s WHERE id = %s",
        (_now(), appt_id),
    )


def get_upcoming_appointments(days_ahead: int = 7) -> list[dict]:
    """Return non-cancelled appointments within the next N days (for backlog)."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT a.*, m.name AS member_name
           FROM medical_appointments a
           JOIN medical_members m ON a.member_id = m.id
           WHERE NOT a.cancelled
             AND a.appointment_at >= now()
             AND a.appointment_at <= now() + (%s || ' days')::interval
           ORDER BY a.appointment_at ASC""",
        (str(days_ahead),),
    )
    result = []
    for row in rows:
        appt = _appointment_row(row)
        appt["member_name"] = row.get("member_name") or ""
        result.append(appt)
    return result


# ===========================================================================
# MEDICAL EQUIPMENT
# ===========================================================================

_EQUIPMENT_HINT = (
    "Focus on: family member name, equipment name, brand/model, serial number, "
    "active status, and any notes about the device."
)
_EQUIP_TASK_HINT = (
    "Focus on: equipment name, task name, how often it recurs (interval_days), "
    "when it was last done, when it is next due, and any notes."
)


def _equipment_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "member_id": row.get("member_id") or "",
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "brand": row.get("brand") or "",
        "model": row.get("model") or "",
        "serial_no": row.get("serial_no") or "",
        "active": bool(row.get("active", True)),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def _equip_task_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "equipment_id": row.get("equipment_id") or "",
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "interval_days": row.get("interval_days"),
        "last_done_at": _date(row.get("last_done_at")),
        "next_due_at": _date(row.get("next_due_at")),
        "active": bool(row.get("active", True)),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
        "updated_at": _ts(row.get("updated_at")),
    }


def _equip_log_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "task_id": row.get("task_id") or "",
        "completed_at": _date(row.get("completed_at")),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _ts(row.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Equipment CRUD
# ---------------------------------------------------------------------------

def get_all_equipment(member_id: str = "", include_inactive: bool = False) -> list[dict]:
    conditions = []
    params: list = []
    if member_id:
        conditions.append("member_id = %s")
        params.append(member_id)
    if not include_inactive:
        conditions.append("active = TRUE")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fetch_all_in_schema(
        SCHEMA,
        f"SELECT * FROM medical_equipment {where} ORDER BY name",
        tuple(params),
    )
    return [_equipment_row(r) for r in rows]


def get_equipment(equip_id: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM medical_equipment WHERE id = %s", (equip_id,)
    )
    return _equipment_row(row) if row else None


def create_equipment(equip: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_equipment
               (id, member_id, name, description, brand, model, serial_no,
                active, notes, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
           RETURNING *""",
        (
            equip["id"], equip["member_id"], equip["name"],
            equip.get("description", ""), equip.get("brand", ""),
            equip.get("model", ""), equip.get("serial_no", ""),
            equip.get("notes", ""), equip.get("created_by", ""),
            _now(), _now(),
        ),
    )
    result = _equipment_row(row) if row else None
    if result:
        digest_record(
            app_id="medical", entity_type="medical equipment", action="created",
            entity_id=result["id"], record=result, by=equip.get("created_by", ""),
            context_hint=_EQUIPMENT_HINT,
        )
    return result


def update_equipment(equip_id: str, updates: dict) -> dict | None:
    allowed = {"name", "description", "brand", "model", "serial_no", "active", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_equipment(equip_id)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [equip_id]
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE medical_equipment SET {set_clause} WHERE id = %s RETURNING *",
        tuple(params),
    )
    result = _equipment_row(row) if row else None
    if result:
        digest_record(
            app_id="medical", entity_type="medical equipment", action="updated",
            entity_id=equip_id, record=result, by=updates.get("updated_by", ""),
            context_hint=_EQUIPMENT_HINT,
        )
    return result


def delete_equipment(equip_id: str) -> bool:
    equip = get_equipment(equip_id)
    n = execute_in_schema(
        SCHEMA, "DELETE FROM medical_equipment WHERE id = %s", (equip_id,)
    )
    if n > 0 and equip:
        digest_record(
            app_id="medical", entity_type="medical equipment", action="deleted",
            entity_id=equip_id, record=equip, by="",
        )
    return n > 0


# ---------------------------------------------------------------------------
# Equipment Task CRUD
# ---------------------------------------------------------------------------

def get_tasks_for_equipment(equipment_id: str, include_inactive: bool = False) -> list[dict]:
    if include_inactive:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_equipment_tasks WHERE equipment_id = %s ORDER BY next_due_at ASC NULLS LAST, name",
            (equipment_id,),
        )
    else:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM medical_equipment_tasks WHERE equipment_id = %s AND active = TRUE ORDER BY next_due_at ASC NULLS LAST, name",
            (equipment_id,),
        )
    return [_equip_task_row(r) for r in rows]


def get_equip_task(task_id: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM medical_equipment_tasks WHERE id = %s", (task_id,)
    )
    return _equip_task_row(row) if row else None


def create_equip_task(task: dict) -> dict | None:
    row = execute_returning_in_schema(
        SCHEMA,
        """INSERT INTO medical_equipment_tasks
               (id, equipment_id, name, description, interval_days,
                last_done_at, next_due_at, active, notes, created_by, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
           RETURNING *""",
        (
            task["id"], task["equipment_id"], task["name"],
            task.get("description", ""), task.get("interval_days"),
            task.get("last_done_at") or None, task.get("next_due_at") or None,
            task.get("notes", ""), task.get("created_by", ""),
            _now(), _now(),
        ),
    )
    result = _equip_task_row(row) if row else None
    if result:
        digest_record(
            app_id="medical", entity_type="equipment task", action="created",
            entity_id=result["id"], record=result, by=task.get("created_by", ""),
            context_hint=_EQUIP_TASK_HINT,
        )
    return result


def update_equip_task(task_id: str, updates: dict) -> dict | None:
    allowed = {"name", "description", "interval_days", "last_done_at",
               "next_due_at", "active", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_equip_task(task_id)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [task_id]
    row = execute_returning_in_schema(
        SCHEMA,
        f"UPDATE medical_equipment_tasks SET {set_clause} WHERE id = %s RETURNING *",
        tuple(params),
    )
    result = _equip_task_row(row) if row else None
    if result:
        digest_record(
            app_id="medical", entity_type="equipment task", action="updated",
            entity_id=task_id, record=result, by=updates.get("updated_by", ""),
            context_hint=_EQUIP_TASK_HINT,
        )
    return result


def delete_equip_task(task_id: str) -> bool:
    task = get_equip_task(task_id)
    n = execute_in_schema(
        SCHEMA, "DELETE FROM medical_equipment_tasks WHERE id = %s", (task_id,)
    )
    if n > 0 and task:
        digest_record(
            app_id="medical", entity_type="equipment task", action="deleted",
            entity_id=task_id, record=task, by="",
        )
    return n > 0


def complete_equip_task(
    task_id: str,
    completed_at: str = "",
    notes: str = "",
    created_by: str = "",
    log_id: str = "",
) -> dict:
    """Mark a maintenance task done: log entry + advance next_due_at for recurring tasks."""
    from datetime import date as _date_cls, timedelta
    import uuid as _uuid

    task = get_equip_task(task_id)
    if not task:
        return {"error": "Task not found"}

    done_date = completed_at or _date_cls.today().isoformat()
    entry_id = log_id or f"meql-{_uuid.uuid4().hex[:8]}"

    from app_platform.db import scoped_conn
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO medical_equipment_log
                       (id, task_id, completed_at, notes, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (entry_id, task_id, done_date, notes, created_by, _now()),
            )
            if task.get("interval_days"):
                d = _date_cls.fromisoformat(done_date)
                next_due = (d + timedelta(days=task["interval_days"])).isoformat()
                cur.execute(
                    """UPDATE medical_equipment_tasks
                       SET last_done_at = %s, next_due_at = %s, updated_at = %s
                       WHERE id = %s""",
                    (done_date, next_due, _now(), task_id),
                )
            else:
                cur.execute(
                    """UPDATE medical_equipment_tasks
                       SET last_done_at = %s, updated_at = %s
                       WHERE id = %s""",
                    (done_date, _now(), task_id),
                )
        conn.commit()

    updated = get_equip_task(task_id)
    if updated:
        record = dict(updated)
        record["completed_at"] = done_date
        digest_record(
            app_id="medical", entity_type="equipment task", action="completed",
            entity_id=task_id, record=record, by=created_by,
            context_hint=_EQUIP_TASK_HINT,
        )
    log = get_equip_task_log(task_id, limit=1)
    return {"task": updated, "log_entry": log[0] if log else {}}


def get_equip_task_log(task_id: str, limit: int = 50) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM medical_equipment_log WHERE task_id = %s ORDER BY completed_at DESC, created_at DESC LIMIT %s",
        (task_id, limit),
    )
    return [_equip_log_row(r) for r in rows]


def get_overdue_equip_tasks(days_ahead: int = 0) -> list[dict]:
    """Return active tasks due within days_ahead (or overdue). Joins equipment + member."""
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT t.*, e.name AS equipment_name, e.member_id,
                  m.name AS member_name
           FROM medical_equipment_tasks t
           JOIN medical_equipment e ON t.equipment_id = e.id
           JOIN medical_members m ON e.member_id = m.id
           WHERE t.active = TRUE AND e.active = TRUE
             AND t.next_due_at IS NOT NULL
             AND t.next_due_at <= CURRENT_DATE + %s
           ORDER BY t.next_due_at ASC""",
        (days_ahead,),
    )
    result = []
    for row in rows:
        task = _equip_task_row(row)
        task["equipment_name"] = row.get("equipment_name") or ""
        task["member_id"] = row.get("member_id") or ""
        task["member_name"] = row.get("member_name") or ""
        result.append(task)
    return result


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "family member",
     "list_fn": get_all_members, "context_hint": ""},
    {"entity_type": "medication",
     "list_fn": lambda: get_all_medications(active_only=False),
     "context_hint": _MEDICATION_HINT},
    {"entity_type": "medical event",
     "list_fn": get_all_events, "context_hint": _EVENT_HINT},
    {"entity_type": "treatment",
     "list_fn": lambda: get_all_treatments(active_only=False),
     "context_hint": _TREATMENT_HINT},
    {"entity_type": "treatment log",
     "list_fn": get_all_treatment_logs, "context_hint": _TREATMENT_LOG_HINT},
    {"entity_type": "lab result",
     "list_fn": get_lab_results, "context_hint": _LAB_RESULT_HINT},
]
