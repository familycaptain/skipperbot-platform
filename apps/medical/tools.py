"""Medical App — MCP Tools
==========================
Chat-accessible tools for managing family medical records.
"""

import uuid
from datetime import date


def add_medical_member(name: str, notes: str = "") -> dict:
    """Add a family member to the medical tracker.

    Args:
        name: First name or identifier ("alice", "bob", "kid1")
        notes: Optional notes about this member

    Ack: Adding "{name}" to medical members...
    """
    from apps.medical import data as _dl
    existing = _dl.get_member_by_name(name)
    if existing:
        return {"error": f"Member '{name}' already exists", "member": existing}
    member_id = f"mmbr-{uuid.uuid4().hex[:8]}"
    member = _dl.create_member({"id": member_id, "name": name.strip(), "notes": notes})
    return member or {"error": "Failed to create member"}



def list_medical_members() -> dict:
    """List all family members in the medical tracker.

    Ack: Loading family members...
    """
    from apps.medical import data as _dl
    return {"members": _dl.get_all_members()}



def add_medication(
    member_name: str,
    name: str,
    dosage_notes: str = "",
    last_dose_date: str = "",
    duration_days: int | None = None,
    reminder_days: int = 7,
    prescriber: str = "",
    pharmacy: str = "",
    start_date: str = "",
    notes: str = "",
    created_by: str = "",
) -> dict:
    """Track a medication for a family member.

    Args:
        member_name: Family member name (e.g. "alice")
        name: Medication name and dosage (e.g. "Lisinopril 10mg")
        dosage_notes: How to take it (e.g. "1 tablet daily in the morning")
        last_dose_date: Date they will run out / take the last pill (YYYY-MM-DD)
        duration_days: How many days one filled prescription lasts (e.g. 30, 90)
        reminder_days: Days before last_dose_date to start nagging (default 7)
        prescriber: Doctor name
        pharmacy: Pharmacy name
        start_date: When they started taking it (YYYY-MM-DD)
        notes: Additional notes
        created_by: Who is entering this

    Ack: Adding medication "{name}" for {member_name}...
    """
    from apps.medical import data as _dl
    member = _dl.get_member_by_name(member_name)
    if not member:
        return {"error": f"Member '{member_name}' not found. Add them first with add_medical_member."}
    med_id = f"mmed-{uuid.uuid4().hex[:8]}"
    med = _dl.create_medication({
        "id": med_id,
        "member_id": member["id"],
        "name": name.strip(),
        "dosage_notes": dosage_notes,
        "last_dose_date": last_dose_date or None,
        "duration_days": duration_days,
        "reminder_days": reminder_days,
        "prescriber": prescriber,
        "pharmacy": pharmacy,
        "start_date": start_date or None,
        "notes": notes,
        "created_by": created_by,
    })
    return med or {"error": "Failed to create medication"}



def list_medications(member_name: str = "", active_only: bool = True) -> dict:
    """List medications with refill status.

    Args:
        member_name: Filter by family member (optional)
        active_only: Only show active medications (default True)

    Ack: Loading medications...
    """
    from apps.medical import data as _dl
    from datetime import date as _date
    member_id = ""
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]
    meds = _dl.get_all_medications(member_id=member_id, active_only=active_only)
    today = _date.today()
    for m in meds:
        last_dose = m.get("last_dose_date")
        if last_dose:
            try:
                days_left = (_date.fromisoformat(last_dose) - today).days
                m["days_until_last_dose"] = days_left
                if days_left < 0:
                    m["status_label"] = f"⚠️ Ran out {abs(days_left)}d ago"
                elif days_left == 0:
                    m["status_label"] = "⚠️ Last dose today"
                elif days_left <= m.get("reminder_days", 7):
                    m["status_label"] = f"🟡 Refill in {days_left}d"
                else:
                    m["status_label"] = f"🟢 {days_left}d left"
            except ValueError:
                pass
    return {"medications": meds, "count": len(meds)}



def update_medication(
    med_id: str,
    name: str | None = None,
    dosage_notes: str | None = None,
    prescriber: str | None = None,
    pharmacy: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    active: bool | None = None,
    last_dose_date: str | None = None,
    duration_days: int | None = None,
    reminder_days: int | None = None,
    refill_status: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update a medication record. Pass only the fields you want to change.

    Args:
        med_id: Medication ID (mmed-...)
        name: Medication name and dosage
        dosage_notes: How to take it
        prescriber: Doctor name
        pharmacy: Pharmacy name
        start_date: When they started (YYYY-MM-DD)
        end_date: When they stopped (YYYY-MM-DD)
        active: Whether the medication is currently active
        last_dose_date: Date of last pill / runs-out date (YYYY-MM-DD)
        duration_days: How many days one filled prescription lasts
        reminder_days: Days before last_dose_date to start nagging
        refill_status: One of 'active', 'needs_ordering', 'ordered', 'filled'
        notes: Additional notes

    Ack: Updating medication {med_id}...
    """
    candidates = {
        "name": name,
        "dosage_notes": dosage_notes,
        "prescriber": prescriber,
        "pharmacy": pharmacy,
        "start_date": start_date,
        "end_date": end_date,
        "active": active,
        "last_dose_date": last_dose_date,
        "duration_days": duration_days,
        "reminder_days": reminder_days,
        "refill_status": refill_status,
        "notes": notes,
    }
    updates = {k: v for k, v in candidates.items() if v is not None}

    from apps.medical import data as _dl
    med = _dl.update_medication(med_id, updates)
    return med or {"error": f"Medication {med_id} not found"}



def mark_medication_ordered(med_id: str) -> dict:
    """Mark a medication as ordered — stops the 'needs ordering' nag.
    Nag continues daily as 'ordered, awaiting fill' until mark_medication_filled is called.

    Args:
        med_id: Medication ID (mmed-...)

    Ack: Marking medication {med_id} as ordered...
    """
    from apps.medical import data as _dl
    med = _dl.mark_medication_ordered(med_id)
    return med or {"error": f"Medication {med_id} not found or not active"}



def mark_medication_filled(med_id: str) -> dict:
    """Mark a medication as filled — advances last_dose_date by duration_days, resets refill cycle.

    Args:
        med_id: Medication ID (mmed-...)

    Ack: Marking medication {med_id} as filled...
    """
    from apps.medical import data as _dl
    med = _dl.mark_medication_filled(med_id)
    return med or {"error": f"Medication {med_id} not found or missing last_dose_date/duration_days"}



def get_upcoming_refills(days: int = 14) -> dict:
    """Get medications needing a refill in the next N days.

    Args:
        days: How many days to look ahead (default 14)

    Ack: Checking upcoming refills...
    """
    from apps.medical import data as _dl
    from datetime import date as _date
    meds = _dl.get_upcoming_refills(days)
    today = _date.today()
    for m in meds:
        last_dose = m.get("last_dose_date")
        if last_dose:
            try:
                days_left = (_date.fromisoformat(last_dose) - today).days
                m["days_left"] = days_left
            except ValueError:
                pass
    return {"medications": meds, "count": len(meds)}



def log_medical_event(
    member_name: str,
    event_type: str,
    title: str,
    event_date: str,
    summary: str = "",
    provider: str = "",
    follow_up_date: str = "",
    follow_up_notes: str = "",
    tags: list[str] | None = None,
    notes: str = "",
    created_by: str = "",
) -> dict:
    """Log a medical event (visit, surgery, procedure, lab, note, or emergency).

    Args:
        member_name: Family member name
        event_type: One of: visit, surgery, procedure, lab, note, emergency
        title: Short title (e.g. "Annual Physical", "Knee X-Ray", "Blood Work")
        event_date: Date of event (YYYY-MM-DD)
        summary: What happened, what was said
        provider: Doctor or facility name
        follow_up_date: Date for follow-up (YYYY-MM-DD), if applicable
        follow_up_notes: What the follow-up is for
        tags: Tags like ["cardiology", "dental"]
        notes: Additional notes
        created_by: Who is entering this

    Ack: Logging "{title}" for {member_name}...
    """
    from apps.medical import data as _dl
    member = _dl.get_member_by_name(member_name)
    if not member:
        return {"error": f"Member '{member_name}' not found"}
    event_id = f"mevt-{uuid.uuid4().hex[:8]}"
    event = _dl.create_event({
        "id": event_id,
        "member_id": member["id"],
        "event_type": event_type,
        "title": title.strip(),
        "event_date": event_date,
        "provider": provider,
        "summary": summary,
        "follow_up_date": follow_up_date or None,
        "follow_up_notes": follow_up_notes,
        "tags": tags or [],
        "notes": notes,
        "created_by": created_by,
    })
    return event or {"error": "Failed to log event"}



def list_medical_events(
    member_name: str = "",
    event_type: str = "",
    since: str = "",
) -> dict:
    """List medical events with optional filters.

    Args:
        member_name: Filter by family member
        event_type: Filter by type (visit, surgery, procedure, lab, note, emergency)
        since: Only show events on or after this date (YYYY-MM-DD)

    Ack: Loading medical events...
    """
    from apps.medical import data as _dl
    member_id = ""
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]
    events = _dl.get_all_events(member_id=member_id, event_type=event_type, since=since)
    return {"events": events, "count": len(events)}



def add_treatment(
    member_name: str,
    name: str,
    interval_days: int,
    description: str = "",
    last_done_at: str = "",
    next_due_at: str = "",
    notes: str = "",
    created_by: str = "",
) -> dict:
    """Add a recurring treatment (injection, infusion, etc.) for a family member.

    Args:
        member_name: Family member name
        name: Treatment name (e.g. "Epoetin Alfa injection", "B12 shot")
        interval_days: Days between instances (e.g. 14 = every 2 weeks)
        description: Optional description
        last_done_at: Date last done (YYYY-MM-DD), if known
        next_due_at: Next due date (YYYY-MM-DD); auto-calculated if last_done_at provided
        notes: Additional notes
        created_by: Who is entering this

    Ack: Adding treatment "{name}" for {member_name}...
    """
    from apps.medical import data as _dl
    from datetime import timedelta
    member = _dl.get_member_by_name(member_name)
    if not member:
        return {"error": f"Member '{member_name}' not found"}
    # Auto-calculate next_due_at if last_done_at provided but next_due_at not
    computed_next = next_due_at
    if last_done_at and not next_due_at:
        try:
            computed_next = (date.fromisoformat(last_done_at) + timedelta(days=interval_days)).isoformat()
        except ValueError:
            pass
    treatment_id = f"mtrx-{uuid.uuid4().hex[:8]}"
    treatment = _dl.create_treatment({
        "id": treatment_id,
        "member_id": member["id"],
        "name": name.strip(),
        "description": description,
        "interval_days": interval_days,
        "last_done_at": last_done_at or None,
        "next_due_at": computed_next or None,
        "notes": notes,
        "created_by": created_by,
    })
    return treatment or {"error": "Failed to create treatment"}



def log_treatment(
    treatment_id: str,
    done_at: str = "",
    medication: str = "",
    notes: str = "",
    created_by: str = "",
) -> dict:
    """Record an instance of a treatment (e.g. gave the injection today).
    Automatically advances next_due_at by interval_days.

    Args:
        treatment_id: Treatment ID (mtrx-...)
        done_at: Date performed (YYYY-MM-DD, default today)
        medication: Drug name, lot#, or dose info (optional)
        notes: Notes for this specific instance
        created_by: Who performed/recorded this

    Ack: Logging treatment {treatment_id}...
    """
    from apps.medical import data as _dl
    log_id = f"mtrxl-{uuid.uuid4().hex[:8]}"
    entry = _dl.log_treatment({
        "id": log_id,
        "treatment_id": treatment_id,
        "done_at": done_at or date.today().isoformat(),
        "medication": medication,
        "notes": notes,
        "created_by": created_by,
    })
    return entry or {"error": f"Treatment {treatment_id} not found"}



def list_treatments(member_name: str = "", overdue_only: bool = False) -> dict:
    """List recurring treatments with due status.

    Args:
        member_name: Filter by family member
        overdue_only: Only show overdue treatments

    Ack: Loading treatments...
    """
    from apps.medical import data as _dl
    from datetime import date as _date
    member_id = ""
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]
    treatments = _dl.get_all_treatments(member_id=member_id, active_only=True)
    today = _date.today()
    result = []
    for t in treatments:
        due_str = t.get("next_due_at") or ""
        if due_str:
            try:
                days_left = (_date.fromisoformat(due_str) - today).days
                t["days_until_due"] = days_left
                if days_left < 0:
                    t["status_label"] = f"🔴 Overdue {abs(days_left)}d"
                elif days_left <= 7:
                    t["status_label"] = f"🟡 Due in {days_left}d"
                else:
                    t["status_label"] = f"🟢 Due in {days_left}d"
                if overdue_only and days_left >= 0:
                    continue
            except ValueError:
                pass
        result.append(t)
    return {"treatments": result, "count": len(result)}



def add_lab_test(
    name: str,
    unit: str = "",
    normal_min: float | None = None,
    normal_max: float | None = None,
    sort_order: int = 0,
    notes: str = "",
) -> dict:
    """Add a lab test to the master list.

    Args:
        name: Test name (e.g. "Phosphorous", "Hemoglobin", "PTH")
        unit: Unit of measure (e.g. "mg/dL", "g/dL")
        normal_min: Lower bound of normal range
        normal_max: Upper bound of normal range
        sort_order: Display order (lower = first)
        notes: Additional notes

    Ack: Adding lab test "{name}"...
    """
    from apps.medical import data as _dl
    existing = _dl.get_lab_test_by_name(name)
    if existing:
        return {"error": f"Lab test '{name}' already exists", "test": existing}
    test_id = f"mlbt-{uuid.uuid4().hex[:8]}"
    test = _dl.create_lab_test({
        "id": test_id,
        "name": name.strip(),
        "unit": unit,
        "normal_min": normal_min,
        "normal_max": normal_max,
        "sort_order": sort_order,
        "notes": notes,
    })
    return test or {"error": "Failed to create lab test"}



def log_lab_results(
    member_name: str,
    result_date: str,
    results: list[dict],
    event_id: str = "",
    created_by: str = "",
) -> dict:
    """Record lab results for a family member.

    Args:
        member_name: Family member name
        result_date: Date of the blood draw (YYYY-MM-DD)
        results: List of {test_name, value, notes?} dicts
        event_id: Optional — link to a medical event of type 'lab'
        created_by: Who is entering this

    Ack: Recording lab results for {member_name}...
    """
    from apps.medical import data as _dl
    member = _dl.get_member_by_name(member_name)
    if not member:
        return {"error": f"Member '{member_name}' not found"}
    created = []
    errors = []
    for item in results:
        test_name = item.get("test_name") or item.get("name") or ""
        value = item.get("value")
        if value is None:
            errors.append(f"Missing value for test '{test_name}'")
            continue
        test = _dl.get_lab_test_by_name(test_name)
        if not test:
            errors.append(f"Lab test '{test_name}' not found — add it with add_lab_test first")
            continue
        result_id = f"mlbr-{uuid.uuid4().hex[:8]}"
        result = _dl.create_lab_result({
            "id": result_id,
            "member_id": member["id"],
            "event_id": event_id or None,
            "lab_test_id": test["id"],
            "result_date": result_date,
            "value": value,
            "notes": item.get("notes", ""),
            "created_by": created_by,
        })
        if result:
            created.append({**result, "test_name": test["name"], "unit": test.get("unit")})
        else:
            errors.append(f"Failed to save result for '{test_name}'")
    return {"created": created, "count": len(created), "errors": errors}


def get_lab_results_by_date(result_date: str, member_name: str = "", event_id: str = "") -> dict:
    """Get all recorded lab results for an exact date.

    Use this when the user asks for all lab results / lab values from a date.
    This returns every stored lab result row for that date; do not guess common
    tests or call get_lab_history one test at a time for an all-results request.

    Args:
        result_date: Exact blood draw/result date (YYYY-MM-DD)
        member_name: Filter by family member (optional, e.g. "alice")
        event_id: Optional lab event ID to narrow to a specific draw

    Ack: Loading all lab results for {result_date}...
    """
    from apps.medical import data as _dl
    member_id = ""
    member = None
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]

    results = _dl.get_lab_results(
        member_id=member_id,
        event_id=event_id,
        result_date=result_date,
        include_details=True,
    )
    return {
        "result_date": result_date,
        "member": member,
        "event_id": event_id,
        "results": results,
        "summary": [
            {
                "test_name": r.get("test_name") or r.get("lab_test_id"),
                "value": r.get("value"),
                "unit": r.get("unit") or "",
                "notes": r.get("notes") or "",
                "event_id": r.get("event_id") or "",
            }
            for r in results
        ],
        "count": len(results),
    }



def get_lab_history(test_name: str, member_name: str = "") -> dict:
    """Get historical results for a specific lab test.

    Args:
        test_name: Lab test name (e.g. "Phosphorous")
        member_name: Filter by family member (optional)

    Ack: Loading lab history for "{test_name}"...
    """
    from apps.medical import data as _dl
    test = _dl.get_lab_test_by_name(test_name)
    if not test:
        return {"error": f"Lab test '{test_name}' not found"}
    member_id = ""
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]
    history = _dl.get_lab_history(test["id"], member_id=member_id)
    return {
        "test": test,
        "history": history,
        "count": len(history),
        "latest": history[-1] if history else None,
    }



def search_medical(query: str, member_name: str = "") -> dict:
    """Search across medications, treatments, and events.

    Args:
        query: Search text
        member_name: Limit search to a specific family member (optional)

    Ack: Searching medical records for "{query}"...
    """
    from apps.medical import data as _dl
    member_id = ""
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]
    return _dl.search_medical(query, member_id=member_id)


def list_medical_equipment(member_name: str = "", include_inactive: bool = False) -> dict:
    """List medical equipment such as dialysis machines and supply systems.

    Use this before working with equipment maintenance tasks when the user names
    the equipment but you do not know its equipment_id.

    Args:
        member_name: Optional member name, e.g. "alice".
        include_inactive: Include inactive equipment too.

    Ack: Loading medical equipment...
    """
    from apps.medical import data as _dl

    member_id = ""
    if member_name:
        member = _dl.get_member_by_name(member_name)
        if not member:
            return {"error": f"Member '{member_name}' not found"}
        member_id = member["id"]

    equipment = _dl.get_all_equipment(member_id=member_id, include_inactive=include_inactive)
    return {"equipment": equipment, "count": len(equipment)}


def list_equipment_tasks(equipment_id: str = "", member_name: str = "", include_inactive: bool = False) -> dict:
    """List medical equipment maintenance tasks and due dates.

    Use this when the user asks what equipment tasks are due, or before marking
    a named equipment task complete when you need the task_id. If equipment_id is
    blank, this returns tasks for all matching equipment.

    Args:
        equipment_id: Equipment ID (meq-*). Leave blank to list all equipment tasks.
        member_name: Optional member name when equipment_id is blank.
        include_inactive: Include inactive tasks/equipment.

    Ack: Loading equipment maintenance tasks...
    """
    from apps.medical import data as _dl

    if equipment_id:
        equipment = _dl.get_equipment(equipment_id)
        if not equipment:
            return {"error": f"Equipment '{equipment_id}' not found"}
        tasks = _dl.get_tasks_for_equipment(equipment_id, include_inactive=include_inactive)
        return {"equipment": equipment, "tasks": tasks, "count": len(tasks)}

    equipment_result = list_medical_equipment(
        member_name=member_name,
        include_inactive=include_inactive,
    )
    if equipment_result.get("error"):
        return equipment_result

    rows = []
    for equipment in equipment_result.get("equipment", []):
        tasks = _dl.get_tasks_for_equipment(equipment["id"], include_inactive=include_inactive)
        for task in tasks:
            row = dict(task)
            row["equipment_name"] = equipment.get("name", "")
            row["equipment_brand"] = equipment.get("brand", "")
            row["member_id"] = equipment.get("member_id", "")
            rows.append(row)

    rows.sort(key=lambda task: (task.get("next_due_at") or "9999-12-31", task.get("name") or ""))
    return {"tasks": rows, "count": len(rows)}


def get_due_equipment_tasks(days_ahead: int = 14) -> dict:
    """Get medical equipment maintenance tasks due soon or overdue.

    Args:
        days_ahead: Include tasks due within this many days. Use 0 for overdue/today only.

    Ack: Checking due equipment tasks...
    """
    from apps.medical import data as _dl

    tasks = _dl.get_overdue_equip_tasks(days_ahead=days_ahead)
    return {"tasks": tasks, "count": len(tasks), "days_ahead": days_ahead}


def complete_equipment_task(
    task_id: str,
    completed_at: str = "",
    notes: str = "",
    created_by: str = "",
) -> dict:
    """Mark a medical equipment maintenance task complete/done.

    Use this when the user says an equipment task is done/completed/finished,
    for example "I flushed the drain line" or "mark Flush drain line done".
    This logs a completion and advances the next due date for recurring tasks.
    Get task_id from list_equipment_tasks or get_due_equipment_tasks.

    Args:
        task_id: Equipment task ID (meqt-*).
        completed_at: Completion date YYYY-MM-DD. Defaults to today.
        notes: Optional notes.
        created_by: User who completed it, e.g. "user".

    Ack: Marking equipment task complete...
    """
    from apps.medical import data as _dl

    if not task_id or not task_id.strip():
        return {"error": "task_id is required"}

    return _dl.complete_equip_task(
        task_id=task_id.strip(),
        completed_at=completed_at,
        notes=notes,
        created_by=(created_by or "").strip().lower(),
    )
