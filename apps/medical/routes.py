"""Medical App API Routes
=========================
FastAPI router for all medical endpoints.
Mounted at /api/apps/medical/ by the app platform loader.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.medical import data as _dl

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()


# ===========================================================================
# MEMBERS
# ===========================================================================

@router.get("/members")
async def api_list_members():
    members = await asyncio.to_thread(_dl.get_all_members)
    return {"members": members}


class CreateMemberRequest(BaseModel):
    name: str
    notes: str = ""


@router.post("/members")
async def api_create_member(request: CreateMemberRequest):
    member_id = f"mmbr-{uuid.uuid4().hex[:8]}"
    member = await asyncio.to_thread(_dl.create_member, {
        "id": member_id,
        "name": request.name.strip(),
        "notes": request.notes.strip(),
    })
    if not member:
        raise HTTPException(status_code=400, detail="Failed to create member")
    return member


class UpdateMemberRequest(BaseModel):
    name: str | None = None
    notes: str | None = None


@router.put("/members/{member_id}")
async def api_update_member(member_id: str, request: UpdateMemberRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    ok = await asyncio.to_thread(_dl.update_member, member_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Member not found")
    return await asyncio.to_thread(_dl.get_member, member_id)


@router.delete("/members/{member_id}")
async def api_delete_member(member_id: str):
    ok = await asyncio.to_thread(_dl.delete_member, member_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"ok": True}


# ===========================================================================
# MEDICATIONS
# ===========================================================================

@router.get("/medications")
async def api_list_medications(member_id: str = "", active: bool = True):
    meds = await asyncio.to_thread(_dl.get_all_medications, member_id, active)
    return {"medications": meds, "count": len(meds)}


@router.get("/upcoming-refills")
async def api_upcoming_refills(days: int = 14):
    meds = await asyncio.to_thread(_dl.get_upcoming_refills, days)
    return {"medications": meds, "count": len(meds)}


class CreateMedicationRequest(BaseModel):
    member_id: str
    name: str
    dosage_notes: str = ""
    prescriber: str = ""
    pharmacy: str = ""
    start_date: str | None = None
    end_date: str | None = None
    last_dose_date: str | None = None
    duration_days: int | None = None
    reminder_days: int = 7
    notes: str = ""
    created_by: str = ""


@router.post("/medications")
async def api_create_medication(request: CreateMedicationRequest, http_request: Request):
    request.created_by = _actor(http_request)
    med_id = f"mmed-{uuid.uuid4().hex[:8]}"
    med = await asyncio.to_thread(_dl.create_medication, {
        "id": med_id,
        **request.model_dump(),
    })
    if not med:
        raise HTTPException(status_code=400, detail="Failed to create medication")
    return med


@router.get("/medications/{med_id}")
async def api_get_medication(med_id: str):
    med = await asyncio.to_thread(_dl.get_medication, med_id)
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    return med


class UpdateMedicationRequest(BaseModel):
    name: str | None = None
    dosage_notes: str | None = None
    prescriber: str | None = None
    pharmacy: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    active: bool | None = None
    last_dose_date: str | None = None
    duration_days: int | None = None
    reminder_days: int | None = None
    refill_status: str | None = None
    notes: str | None = None


@router.put("/medications/{med_id}")
async def api_update_medication(med_id: str, request: UpdateMedicationRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    med = await asyncio.to_thread(_dl.update_medication, med_id, updates)
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    return med


@router.delete("/medications/{med_id}")
async def api_delete_medication(med_id: str):
    ok = await asyncio.to_thread(_dl.delete_medication, med_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Medication not found")
    return {"ok": True}


@router.post("/medications/{med_id}/ordered")
async def api_mark_ordered(med_id: str):
    med = await asyncio.to_thread(_dl.mark_medication_ordered, med_id)
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    return med


@router.post("/medications/{med_id}/filled")
async def api_mark_filled(med_id: str):
    med = await asyncio.to_thread(_dl.mark_medication_filled, med_id)
    if not med:
        raise HTTPException(status_code=400, detail="Cannot advance cycle — missing last_dose_date or duration_days")
    return med


# ===========================================================================
# EVENTS
# ===========================================================================

@router.get("/events")
async def api_list_events(member_id: str = "", type: str = "", since: str = ""):
    events = await asyncio.to_thread(_dl.get_all_events, member_id, type, since)
    return {"events": events, "count": len(events)}


@router.get("/events/lab-events")
async def api_lab_events(member_id: str = ""):
    events = await asyncio.to_thread(_dl.get_lab_events, member_id)
    return {"events": events}


class CreateEventRequest(BaseModel):
    member_id: str
    event_type: str = "visit"
    title: str
    event_date: str
    provider: str = ""
    summary: str = ""
    appointment_id: str | None = None
    follow_up_date: str | None = None
    follow_up_notes: str = ""
    tags: list[str] = []
    notes: str = ""
    created_by: str = ""


@router.post("/events")
async def api_create_event(request: CreateEventRequest, http_request: Request):
    request.created_by = _actor(http_request)
    event_id = f"mevt-{uuid.uuid4().hex[:8]}"
    event = await asyncio.to_thread(_dl.create_event, {
        "id": event_id,
        **request.model_dump(),
    })
    if not event:
        raise HTTPException(status_code=400, detail="Failed to create event")
    return event


@router.get("/events/{event_id}")
async def api_get_event(event_id: str):
    event = await asyncio.to_thread(_dl.get_event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


class UpdateEventRequest(BaseModel):
    event_type: str | None = None
    title: str | None = None
    event_date: str | None = None
    provider: str | None = None
    summary: str | None = None
    appointment_id: str | None = None
    follow_up_date: str | None = None
    follow_up_notes: str | None = None
    tags: list[str] | None = None
    notes: str | None = None


@router.put("/events/{event_id}")
async def api_update_event(event_id: str, request: UpdateEventRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    event = await asyncio.to_thread(_dl.update_event, event_id, updates)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/events/{event_id}")
async def api_delete_event(event_id: str):
    ok = await asyncio.to_thread(_dl.delete_event, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"ok": True}


# ===========================================================================
# TREATMENTS
# ===========================================================================

@router.get("/treatments")
async def api_list_treatments(member_id: str = "", active: bool = True):
    treatments = await asyncio.to_thread(_dl.get_all_treatments, member_id, active)
    return {"treatments": treatments, "count": len(treatments)}


@router.get("/upcoming-treatments")
async def api_upcoming_treatments(days: int = 7):
    treatments = await asyncio.to_thread(_dl.get_due_treatments, days)
    return {"treatments": treatments, "count": len(treatments)}


class CreateTreatmentRequest(BaseModel):
    member_id: str
    name: str
    description: str = ""
    interval_days: int
    last_done_at: str | None = None
    next_due_at: str | None = None
    notes: str = ""
    created_by: str = ""


@router.post("/treatments")
async def api_create_treatment(request: CreateTreatmentRequest, http_request: Request):
    request.created_by = _actor(http_request)
    treatment_id = f"mtrx-{uuid.uuid4().hex[:8]}"
    treatment = await asyncio.to_thread(_dl.create_treatment, {
        "id": treatment_id,
        **request.model_dump(),
    })
    if not treatment:
        raise HTTPException(status_code=400, detail="Failed to create treatment")
    return treatment


@router.get("/treatments/{treatment_id}")
async def api_get_treatment(treatment_id: str):
    treatment = await asyncio.to_thread(_dl.get_treatment, treatment_id)
    if not treatment:
        raise HTTPException(status_code=404, detail="Treatment not found")
    log = await asyncio.to_thread(_dl.get_treatment_log, treatment_id)
    return {**treatment, "log": log}


class UpdateTreatmentRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    interval_days: int | None = None
    last_done_at: str | None = None
    next_due_at: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.put("/treatments/{treatment_id}")
async def api_update_treatment(treatment_id: str, request: UpdateTreatmentRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    treatment = await asyncio.to_thread(_dl.update_treatment, treatment_id, updates)
    if not treatment:
        raise HTTPException(status_code=404, detail="Treatment not found")
    return treatment


@router.delete("/treatments/{treatment_id}")
async def api_delete_treatment(treatment_id: str):
    ok = await asyncio.to_thread(_dl.delete_treatment, treatment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Treatment not found")
    return {"ok": True}


class LogTreatmentRequest(BaseModel):
    done_at: str = ""
    medication: str = ""
    notes: str = ""
    created_by: str = ""


@router.post("/treatments/{treatment_id}/log")
async def api_log_treatment(treatment_id: str, request: LogTreatmentRequest, http_request: Request):
    request.created_by = _actor(http_request)
    log_id = f"mtrxl-{uuid.uuid4().hex[:8]}"
    entry = await asyncio.to_thread(_dl.log_treatment, {
        "id": log_id,
        "treatment_id": treatment_id,
        "done_at": request.done_at or None,
        "medication": request.medication,
        "notes": request.notes,
        "created_by": request.created_by,
    })
    if not entry:
        raise HTTPException(status_code=404, detail="Treatment not found")
    treatment = await asyncio.to_thread(_dl.get_treatment, treatment_id)
    return {"log_entry": entry, "treatment": treatment}


@router.get("/treatments/{treatment_id}/log")
async def api_treatment_log(treatment_id: str, limit: int = 50):
    log = await asyncio.to_thread(_dl.get_treatment_log, treatment_id, limit)
    return {"log": log, "count": len(log)}


class UpdateTreatmentLogRequest(BaseModel):
    done_at: str | None = None
    medication: str | None = None
    notes: str | None = None


@router.put("/treatments/log/{log_id}")
async def api_update_treatment_log(log_id: str, request: UpdateTreatmentLogRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    entry = await asyncio.to_thread(_dl.update_treatment_log_entry, log_id, updates)
    if not entry:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return entry


@router.delete("/treatments/log/{log_id}")
async def api_delete_treatment_log(log_id: str):
    ok = await asyncio.to_thread(_dl.delete_treatment_log_entry, log_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return {"ok": True}


# ===========================================================================
# LAB TESTS
# ===========================================================================

@router.get("/lab-tests")
async def api_list_lab_tests():
    tests = await asyncio.to_thread(_dl.get_all_lab_tests)
    return {"lab_tests": tests}


class CreateLabTestRequest(BaseModel):
    name: str
    unit: str = ""
    normal_min: float | None = None
    normal_max: float | None = None
    sort_order: int = 0
    notes: str = ""


@router.post("/lab-tests")
async def api_create_lab_test(request: CreateLabTestRequest):
    test_id = f"mlbt-{uuid.uuid4().hex[:8]}"
    test = await asyncio.to_thread(_dl.create_lab_test, {"id": test_id, **request.model_dump()})
    if not test:
        raise HTTPException(status_code=400, detail="Failed to create lab test (name may already exist)")
    return test


class UpdateLabTestRequest(BaseModel):
    name: str | None = None
    unit: str | None = None
    normal_min: float | None = None
    normal_max: float | None = None
    sort_order: int | None = None
    notes: str | None = None


@router.put("/lab-tests/{test_id}")
async def api_update_lab_test(test_id: str, request: UpdateLabTestRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    test = await asyncio.to_thread(_dl.update_lab_test, test_id, updates)
    if not test:
        raise HTTPException(status_code=404, detail="Lab test not found")
    return test


@router.delete("/lab-tests/{test_id}")
async def api_delete_lab_test(test_id: str):
    ok = await asyncio.to_thread(_dl.delete_lab_test, test_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot delete — results exist for this test")
    return {"ok": True}


# ===========================================================================
# LAB RESULTS
# ===========================================================================

@router.get("/lab-results")
async def api_list_lab_results(
    member_id: str = "",
    test_id: str = "",
    event_id: str = "",
    since: str = "",
    result_date: str = "",
    include_details: bool = False,
):
    results = await asyncio.to_thread(
        _dl.get_lab_results,
        member_id,
        test_id,
        event_id,
        since,
        result_date,
        include_details,
    )
    return {"results": results, "count": len(results)}


@router.get("/lab-results/history/{test_id}")
async def api_lab_history(test_id: str, member_id: str = ""):
    history = await asyncio.to_thread(_dl.get_lab_history, test_id, member_id)
    return {"history": history, "count": len(history)}


class CreateLabResultRequest(BaseModel):
    member_id: str
    lab_test_id: str
    result_date: str
    value: float
    event_id: str | None = None
    notes: str = ""
    created_by: str = ""


class BulkLabResultItem(BaseModel):
    lab_test_id: str
    value: float
    notes: str = ""


class BulkCreateLabResultsRequest(BaseModel):
    member_id: str
    result_date: str
    event_id: str | None = None
    created_by: str = ""
    results: list[BulkLabResultItem]


@router.post("/lab-results")
async def api_create_lab_result(request: CreateLabResultRequest, http_request: Request):
    request.created_by = _actor(http_request)
    result_id = f"mlbr-{uuid.uuid4().hex[:8]}"
    result = await asyncio.to_thread(_dl.create_lab_result, {"id": result_id, **request.model_dump()})
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create lab result")
    return result


@router.post("/lab-results/bulk")
async def api_bulk_create_lab_results(request: BulkCreateLabResultsRequest, http_request: Request):
    request.created_by = _actor(http_request)
    created = []
    for item in request.results:
        result_id = f"mlbr-{uuid.uuid4().hex[:8]}"
        result = await asyncio.to_thread(_dl.create_lab_result, {
            "id": result_id,
            "member_id": request.member_id,
            "event_id": request.event_id,
            "lab_test_id": item.lab_test_id,
            "result_date": request.result_date,
            "value": item.value,
            "notes": item.notes,
            "created_by": request.created_by,
        })
        if result:
            created.append(result)
    return {"results": created, "count": len(created)}


class UpdateLabResultRequest(BaseModel):
    event_id: str | None = None
    result_date: str | None = None
    value: float | None = None
    notes: str | None = None


@router.put("/lab-results/{result_id}")
async def api_update_lab_result(result_id: str, request: UpdateLabResultRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    result = await asyncio.to_thread(_dl.update_lab_result, result_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Lab result not found")
    return result


@router.delete("/lab-results/{result_id}")
async def api_delete_lab_result(result_id: str):
    ok = await asyncio.to_thread(_dl.delete_lab_result, result_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Lab result not found")
    return {"ok": True}


@router.delete("/lab-results/by-date/{member_id}/{result_date}")
async def api_delete_lab_results_by_date(member_id: str, result_date: str):
    count = await asyncio.to_thread(_dl.delete_lab_results_by_date, member_id, result_date)
    return {"ok": True, "deleted": count}


# ===========================================================================
# SEARCH
# ===========================================================================

@router.get("/search")
async def api_search(q: str, member_id: str = ""):
    if not q.strip():
        return {"medications": [], "events": []}
    results = await asyncio.to_thread(_dl.search_medical, q.strip(), member_id)
    return results


# ===========================================================================
# APPOINTMENTS
# ===========================================================================

@router.get("/appointments/unlogged")
async def api_unlogged_appointments(member_id: str = ""):
    """Past non-cancelled appointments with no linked medical event."""
    appts = await asyncio.to_thread(_dl.get_past_appointments_without_events, member_id)
    return {"appointments": appts, "count": len(appts)}


@router.get("/appointments")
async def api_list_appointments(
    member_id: str = "",
    include_past: bool = False,
    include_cancelled: bool = False,
):
    appts = await asyncio.to_thread(
        _dl.get_all_appointments, member_id, include_past, include_cancelled
    )
    return {"appointments": appts, "count": len(appts)}


class CreateAppointmentRequest(BaseModel):
    member_id: str
    title: str
    appointment_at: str
    provider: str = ""
    location: str = ""
    appointment_type: str = "visit"
    notes: str = ""
    created_by: str = ""


@router.post("/appointments")
async def api_create_appointment(request: CreateAppointmentRequest, http_request: Request):
    request.created_by = _actor(http_request)
    appt_id = f"mappt-{uuid.uuid4().hex[:8]}"
    appt = await asyncio.to_thread(_dl.create_appointment, {
        "id": appt_id,
        **request.model_dump(),
    })
    if not appt:
        raise HTTPException(status_code=400, detail="Failed to create appointment")
    return appt


@router.get("/appointments/{appt_id}")
async def api_get_appointment(appt_id: str):
    appt = await asyncio.to_thread(_dl.get_appointment, appt_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


class UpdateAppointmentRequest(BaseModel):
    title: str | None = None
    appointment_at: str | None = None
    provider: str | None = None
    location: str | None = None
    appointment_type: str | None = None
    notes: str | None = None
    cancelled: bool | None = None


@router.put("/appointments/{appt_id}")
async def api_update_appointment(appt_id: str, request: UpdateAppointmentRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    appt = await asyncio.to_thread(_dl.update_appointment, appt_id, updates)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@router.delete("/appointments/{appt_id}")
async def api_delete_appointment(appt_id: str):
    ok = await asyncio.to_thread(_dl.delete_appointment, appt_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return {"ok": True}


# ===========================================================================
# MEDICAL EQUIPMENT
# ===========================================================================

@router.get("/equipment")
async def api_list_equipment(member_id: str = "", include_inactive: bool = False):
    items = await asyncio.to_thread(_dl.get_all_equipment, member_id, include_inactive)
    return {"equipment": items, "count": len(items)}


class CreateEquipmentRequest(BaseModel):
    member_id: str
    name: str
    description: str = ""
    brand: str = ""
    model: str = ""
    serial_no: str = ""
    notes: str = ""
    created_by: str = ""


@router.post("/equipment")
async def api_create_equipment(request: CreateEquipmentRequest, http_request: Request):
    request.created_by = _actor(http_request)
    equip_id = f"meq-{uuid.uuid4().hex[:8]}"
    equip = await asyncio.to_thread(_dl.create_equipment, {"id": equip_id, **request.model_dump()})
    if not equip:
        raise HTTPException(status_code=400, detail="Failed to create equipment")
    return equip


class UpdateEquipmentRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.put("/equipment/{equip_id}")
async def api_update_equipment(equip_id: str, request: UpdateEquipmentRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    equip = await asyncio.to_thread(_dl.update_equipment, equip_id, updates)
    if not equip:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return equip


@router.delete("/equipment/{equip_id}")
async def api_delete_equipment(equip_id: str):
    ok = await asyncio.to_thread(_dl.delete_equipment, equip_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return {"ok": True}


# ===========================================================================
# EQUIPMENT MAINTENANCE TASKS
# ===========================================================================

@router.get("/equipment/{equip_id}/tasks")
async def api_list_equip_tasks(equip_id: str, include_inactive: bool = False):
    tasks = await asyncio.to_thread(_dl.get_tasks_for_equipment, equip_id, include_inactive)
    return {"tasks": tasks, "count": len(tasks)}


class CreateEquipTaskRequest(BaseModel):
    equipment_id: str
    name: str
    description: str = ""
    interval_days: int | None = None
    next_due_at: str | None = None
    notes: str = ""
    created_by: str = ""


@router.post("/equipment/{equip_id}/tasks")
async def api_create_equip_task(equip_id: str, request: CreateEquipTaskRequest, http_request: Request):
    request.created_by = _actor(http_request)
    task_id = f"meqt-{uuid.uuid4().hex[:8]}"
    data = request.model_dump()
    data["equipment_id"] = equip_id
    task = await asyncio.to_thread(_dl.create_equip_task, {"id": task_id, **data})
    if not task:
        raise HTTPException(status_code=400, detail="Failed to create task")
    return task


class UpdateEquipTaskRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    interval_days: int | None = None
    last_done_at: str | None = None
    next_due_at: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.put("/equipment/tasks/{task_id}")
async def api_update_equip_task(task_id: str, request: UpdateEquipTaskRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    task = await asyncio.to_thread(_dl.update_equip_task, task_id, updates)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/equipment/tasks/{task_id}")
async def api_delete_equip_task(task_id: str):
    ok = await asyncio.to_thread(_dl.delete_equip_task, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


class CompleteEquipTaskRequest(BaseModel):
    completed_at: str = ""
    notes: str = ""
    created_by: str = ""


@router.post("/equipment/tasks/{task_id}/complete")
async def api_complete_equip_task(task_id: str, request: CompleteEquipTaskRequest, http_request: Request):
    request.created_by = _actor(http_request)
    result = await asyncio.to_thread(
        _dl.complete_equip_task,
        task_id, request.completed_at, request.notes, request.created_by,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/equipment/tasks/{task_id}/log")
async def api_equip_task_log(task_id: str, limit: int = 50):
    log = await asyncio.to_thread(_dl.get_equip_task_log, task_id, limit)
    return {"log": log, "count": len(log)}
