"""Auto Maintenance API Routes
================================
FastAPI router for vehicle CRUD, services, issues, valuations, conditions,
images, and maintenance schedules.
Mounted at /api/apps/auto/ by the app platform loader.
"""

import asyncio
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.auto import data as _dl

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()


# ---------------------------------------------------------------------------
# Vehicle list / search
# ---------------------------------------------------------------------------

@router.get("")
async def api_list_vehicles(q: str = ""):
    def _fetch():
        if q.strip():
            return _dl.search_vehicles(q.strip())
        return _dl.get_all_vehicles()
    vehicles = await asyncio.to_thread(_fetch)
    # Attach summary to each vehicle
    for v in vehicles:
        v["_summary"] = await asyncio.to_thread(_dl.get_vehicle_summary, v["id"])
    return {"vehicles": vehicles, "count": len(vehicles)}


# ---------------------------------------------------------------------------
# Vehicle CRUD
# ---------------------------------------------------------------------------

def _build_vehicle_name(year=None, make="", model="", trim_level="", color=""):
    """Auto-generate a display name from component fields."""
    parts = []
    if year:
        parts.append(str(year))
    if make:
        parts.append(make.strip())
    if model:
        parts.append(model.strip())
    if trim_level:
        parts.append(trim_level.strip())
    if color:
        parts.append(color.strip())
    return " ".join(parts) or "New Vehicle"


class CreateVehicleRequest(BaseModel):
    created_by: str = ""
    make: str = ""
    model: str = ""
    trim_level: str = ""
    year: int | None = None
    color: str = ""
    vin: str = ""
    license_plate: str = ""
    odometer: int | None = None
    notes: str = ""


@router.post("")
async def api_create_vehicle(request: CreateVehicleRequest, http_request: Request):
    request.created_by = _actor(http_request)
    veh_id = f"veh-{uuid.uuid4().hex[:8]}"
    vehicle = {
        "id": veh_id,
        "name": _build_vehicle_name(request.year, request.make, request.model, request.trim_level, request.color),
        "make": request.make.strip(),
        "model": request.model.strip(),
        "trim_level": request.trim_level.strip(),
        "year": request.year,
        "color": request.color.strip(),
        "vin": request.vin.strip(),
        "license_plate": request.license_plate.strip(),
        "odometer": request.odometer,
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_vehicle, vehicle)
    return await asyncio.to_thread(_dl.get_vehicle, veh_id)


@router.get("/{vehicle_id}")
async def api_get_vehicle(vehicle_id: str):
    vehicle = await asyncio.to_thread(_dl.get_vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    vehicle["_summary"] = await asyncio.to_thread(_dl.get_vehicle_summary, vehicle_id)
    return vehicle


class UpdateVehicleRequest(BaseModel):
    make: str | None = None
    model: str | None = None
    trim_level: str | None = None
    year: int | None = None
    color: str | None = None
    vin: str | None = None
    license_plate: str | None = None
    odometer: int | None = None
    notes: str | None = None
    responsible_user: str | None = None
    owner: str | None = None


@router.put("/{vehicle_id}")
async def api_update_vehicle(vehicle_id: str, request: UpdateVehicleRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    # Auto-regenerate name from component fields
    current = await asyncio.to_thread(_dl.get_vehicle, vehicle_id)
    if not current:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    merged = {**current, **updates}
    updates["name"] = _build_vehicle_name(
        merged.get("year"), merged.get("make", ""),
        merged.get("model", ""), merged.get("trim_level", ""),
        merged.get("color", ""),
    )
    ok = await asyncio.to_thread(_dl.update_vehicle, vehicle_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return await asyncio.to_thread(_dl.get_vehicle, vehicle_id)


@router.delete("/{vehicle_id}")
async def api_delete_vehicle(vehicle_id: str):
    ok = await asyncio.to_thread(_dl.delete_vehicle, vehicle_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Service Records
# ---------------------------------------------------------------------------

class LogServiceRequest(BaseModel):
    vehicle_id: str
    service_type: str
    created_by: str = ""
    date_performed: str = ""
    odometer_at_service: int | None = None
    cost: float | None = None
    shop_name: str = ""
    description: str = ""
    next_due_date: str = ""
    next_due_mileage: int | None = None
    notes: str = ""


@router.get("/{vehicle_id}/services")
async def api_get_services(vehicle_id: str):
    records = await asyncio.to_thread(_dl.get_service_records, vehicle_id)
    return {"services": records, "count": len(records)}


@router.post("/{vehicle_id}/services")
async def api_log_service(vehicle_id: str, request: LogServiceRequest, http_request: Request):
    request.created_by = _actor(http_request)
    svc_id = f"svc-{uuid.uuid4().hex[:8]}"
    record = {
        "id": svc_id,
        "vehicle_id": vehicle_id,
        "service_type": request.service_type.strip(),
        "description": request.description.strip(),
        "date_performed": request.date_performed.strip() if request.date_performed else date.today().isoformat(),
        "odometer_at_service": request.odometer_at_service,
        "cost": request.cost,
        "shop_name": request.shop_name.strip(),
        "next_due_date": request.next_due_date.strip() if request.next_due_date else None,
        "next_due_mileage": request.next_due_mileage,
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_service_record, record)
    if request.odometer_at_service and request.odometer_at_service > 0:
        await asyncio.to_thread(_dl.update_vehicle, vehicle_id, {"odometer": request.odometer_at_service})
    return await asyncio.to_thread(_dl.get_service_record, svc_id)


@router.put("/services/{svc_id}")
async def api_update_service(svc_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_service_record, svc_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Service record not found")
    return await asyncio.to_thread(_dl.get_service_record, svc_id)


@router.delete("/services/{svc_id}")
async def api_delete_service(svc_id: str):
    ok = await asyncio.to_thread(_dl.delete_service_record, svc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Service record not found")
    return {"ok": True}


@router.get("-upcoming")
async def api_upcoming_maintenance():
    records = await asyncio.to_thread(_dl.get_upcoming_maintenance)
    return {"upcoming": records, "count": len(records)}


# ---------------------------------------------------------------------------
# Vehicle Issues
# ---------------------------------------------------------------------------

class ReportIssueRequest(BaseModel):
    vehicle_id: str
    title: str
    created_by: str = ""
    severity: str = "minor"
    description: str = ""
    date_noticed: str = ""
    notes: str = ""


@router.get("/{vehicle_id}/issues")
async def api_get_issues(vehicle_id: str, status: str = ""):
    issues = await asyncio.to_thread(_dl.get_issues, vehicle_id, status if status else None)
    return {"issues": issues, "count": len(issues)}


@router.post("/{vehicle_id}/issues")
async def api_report_issue(vehicle_id: str, request: ReportIssueRequest, http_request: Request):
    request.created_by = _actor(http_request)
    issue_id = f"vis-{uuid.uuid4().hex[:8]}"
    issue = {
        "id": issue_id,
        "vehicle_id": vehicle_id,
        "title": request.title.strip(),
        "description": request.description.strip(),
        "severity": request.severity.strip(),
        "date_noticed": request.date_noticed.strip() if request.date_noticed else date.today().isoformat(),
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_issue, issue)
    return await asyncio.to_thread(_dl.get_issue, issue_id)


class UpdateIssueRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    severity: str | None = None
    fix_description: str | None = None
    date_fixed: str | None = None
    cost: float | None = None
    notes: str | None = None


@router.put("/issues/{issue_id}")
async def api_update_issue(issue_id: str, request: UpdateIssueRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_issue, issue_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Issue not found")
    return await asyncio.to_thread(_dl.get_issue, issue_id)


@router.delete("/issues/{issue_id}")
async def api_delete_issue(issue_id: str):
    ok = await asyncio.to_thread(_dl.delete_issue, issue_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Vehicle Valuations
# ---------------------------------------------------------------------------

class LogValuationRequest(BaseModel):
    private_party_value: float
    trade_in_value: float
    created_by: str = ""
    condition: str = "good"
    mileage_at_valuation: int | None = None
    source: str = "kbb"
    date_recorded: str = ""
    notes: str = ""


@router.get("/{vehicle_id}/valuations")
async def api_get_valuations(vehicle_id: str):
    vals = await asyncio.to_thread(_dl.get_valuations, vehicle_id)
    return {"valuations": vals, "count": len(vals)}


@router.post("/{vehicle_id}/valuations")
async def api_log_valuation(vehicle_id: str, request: LogValuationRequest, http_request: Request):
    request.created_by = _actor(http_request)
    val_id = f"vval-{uuid.uuid4().hex[:8]}"
    val = {
        "id": val_id,
        "vehicle_id": vehicle_id,
        "date_recorded": request.date_recorded.strip() if request.date_recorded else date.today().isoformat(),
        "private_party_value": request.private_party_value,
        "trade_in_value": request.trade_in_value,
        "condition": request.condition.strip(),
        "mileage_at_valuation": request.mileage_at_valuation,
        "source": request.source.strip(),
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_valuation, val)
    return val


@router.delete("/valuations/{val_id}")
async def api_delete_valuation(val_id: str):
    ok = await asyncio.to_thread(_dl.delete_valuation, val_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Vehicle Conditions
# ---------------------------------------------------------------------------

class LogConditionRequest(BaseModel):
    created_by: str = ""
    date_recorded: str = ""
    mileage_at_report: int | None = None
    brakes: str = "good"
    tires: str = "good"
    tire_tread_depth: float | None = None
    oil_life_pct: int | None = None
    battery: str = "good"
    exterior: str = "good"
    interior: str = "good"
    lights_signals: str = "all_working"
    fluids: str = "all_good"
    notes: str = ""


@router.get("/{vehicle_id}/conditions")
async def api_get_conditions(vehicle_id: str):
    conditions = await asyncio.to_thread(_dl.get_conditions, vehicle_id)
    return {"conditions": conditions, "count": len(conditions)}


@router.post("/{vehicle_id}/conditions")
async def api_log_condition(vehicle_id: str, request: LogConditionRequest, http_request: Request):
    request.created_by = _actor(http_request)
    cond_id = f"vcon-{uuid.uuid4().hex[:8]}"
    cond = {
        "id": cond_id,
        "vehicle_id": vehicle_id,
        "date_recorded": request.date_recorded.strip() if request.date_recorded else date.today().isoformat(),
        "mileage_at_report": request.mileage_at_report,
        "brakes": request.brakes.strip(),
        "tires": request.tires.strip(),
        "tire_tread_depth": request.tire_tread_depth,
        "oil_life_pct": request.oil_life_pct,
        "battery": request.battery.strip(),
        "exterior": request.exterior.strip(),
        "interior": request.interior.strip(),
        "lights_signals": request.lights_signals.strip(),
        "fluids": request.fluids.strip(),
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_condition, cond)
    if request.mileage_at_report and request.mileage_at_report > 0:
        await asyncio.to_thread(_dl.update_vehicle, vehicle_id, {"odometer": request.mileage_at_report})
    return cond


class UpdateConditionRequest(BaseModel):
    date_recorded: str | None = None
    mileage_at_report: int | None = None
    brakes: str | None = None
    tires: str | None = None
    tire_tread_depth: float | None = None
    oil_life_pct: int | None = None
    battery: str | None = None
    exterior: str | None = None
    interior: str | None = None
    lights_signals: str | None = None
    fluids: str | None = None
    notes: str | None = None


@router.put("/conditions/{cond_id}")
async def api_update_condition(cond_id: str, request: UpdateConditionRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_condition, cond_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Condition report not found")
    return await asyncio.to_thread(_dl.get_condition, cond_id)


@router.delete("/conditions/{cond_id}")
async def api_delete_condition(cond_id: str):
    ok = await asyncio.to_thread(_dl.delete_condition, cond_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Condition report not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Maintenance Schedules (platform schedules linked to vehicles)
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/maintenance")
async def api_get_vehicle_maintenance(vehicle_id: str):
    schedules = await asyncio.to_thread(_dl.get_vehicle_maintenance, vehicle_id)
    return {"schedules": schedules, "count": len(schedules)}


class CreateMaintenanceRequest(BaseModel):
    title: str
    recurrence_type: str = "interval"
    recurrence_rule: dict | None = None
    time_of_day: str | None = None
    start_date: str | None = None
    created_by: str = ""
    assigned_to: str = ""
    notify_channel: str = "both"
    reminder_mins: int = 60


@router.post("/{vehicle_id}/maintenance")
async def api_create_vehicle_maintenance(vehicle_id: str, req: CreateMaintenanceRequest, request: Request):
    req.created_by = _actor(request)
    def _create():
        from apps.schedules.data import create_schedule
        veh = _dl.get_vehicle(vehicle_id)
        veh_label = veh["name"] if veh else vehicle_id
        full_title = f"{req.title.strip()} — {veh_label}"
        return create_schedule(
            title=full_title,
            created_by=req.created_by.strip().lower() or "system",
            category="auto",
            assigned_to=req.assigned_to.strip().lower() or req.created_by.strip().lower(),
            recurrence_type=req.recurrence_type,
            recurrence_rule=req.recurrence_rule or {},
            time_of_day=req.time_of_day,
            start_date=req.start_date,
            linked_entity_id=vehicle_id,
            linked_entity_type="vehicle",
            reminder_mins=req.reminder_mins,
            notify_channel=req.notify_channel,
        )
    sch = await asyncio.to_thread(_create)
    return {"ok": True, "schedule": sch}


class CompleteMaintenanceRequest(BaseModel):
    completed_by: str = ""
    service_type: str = ""
    date_performed: str = ""
    odometer: int | None = None
    cost: float | None = None
    shop_name: str = ""
    notes: str = ""


@router.post("/{vehicle_id}/maintenance/{schedule_id}/complete")
async def api_complete_vehicle_maintenance(vehicle_id: str, schedule_id: str, req: CompleteMaintenanceRequest, request: Request):
    req.completed_by = _actor(request)
    def _complete():
        return _dl.complete_maintenance(
            schedule_id=schedule_id,
            vehicle_id=vehicle_id,
            completed_by=req.completed_by,
            service_type=req.service_type,
            date_performed=req.date_performed,
            odometer=req.odometer,
            cost=req.cost,
            shop_name=req.shop_name,
            notes=req.notes,
        )
    result = await asyncio.to_thread(_complete)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return {"ok": True, **result}


@router.delete("/maintenance/{schedule_id}")
async def api_delete_vehicle_maintenance(schedule_id: str):
    from apps.schedules.data import delete_schedule
    ok = await asyncio.to_thread(delete_schedule, schedule_id)
    return {"ok": ok}


# ---------------------------------------------------------------------------
# Oil Change Tracking
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/oil-tracking")
async def api_get_oil_tracking(vehicle_id: str):
    tracking = await asyncio.to_thread(_dl.get_oil_tracking, vehicle_id)
    return {"tracking": tracking}


class UpsertOilTrackingRequest(BaseModel):
    date_performed: str = ""
    odometer_at_service: int
    mileage_interval: int = 5000
    cooldown_months: int = 3
    service_record_id: str = ""


@router.post("/{vehicle_id}/oil-tracking")
async def api_create_oil_tracking(vehicle_id: str, req: UpsertOilTrackingRequest):
    data = {
        "date_performed": req.date_performed or date.today().isoformat(),
        "odometer_at_service": req.odometer_at_service,
        "mileage_interval": req.mileage_interval,
        "cooldown_months": req.cooldown_months,
        "service_record_id": req.service_record_id or None,
    }
    tracking = await asyncio.to_thread(_dl.upsert_oil_tracking, vehicle_id, data)
    return {"ok": True, "tracking": tracking}


class UpdateOilTrackingRequest(BaseModel):
    mileage_interval: int | None = None
    cooldown_months: int | None = None


@router.put("/{vehicle_id}/oil-tracking")
async def api_update_oil_tracking(vehicle_id: str, req: UpdateOilTrackingRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    tracking = await asyncio.to_thread(_dl.update_oil_tracking_settings, vehicle_id, updates)
    if not tracking:
        raise HTTPException(status_code=404, detail="No oil tracking found for this vehicle")
    return {"ok": True, "tracking": tracking}


@router.delete("/{vehicle_id}/oil-tracking")
async def api_delete_oil_tracking(vehicle_id: str):
    ok = await asyncio.to_thread(_dl.delete_oil_tracking, vehicle_id)
    return {"ok": ok}


class ReportMileageRequest(BaseModel):
    odometer: int


@router.post("/{vehicle_id}/mileage")
async def api_report_mileage(vehicle_id: str, req: ReportMileageRequest):
    tracking = await asyncio.to_thread(_dl.record_mileage_check, vehicle_id, req.odometer)
    if not tracking:
        raise HTTPException(status_code=404, detail="No oil tracking found for this vehicle")
    vehicle = await asyncio.to_thread(_dl.get_vehicle, vehicle_id)
    return {"ok": True, "tracking": tracking, "vehicle": vehicle}


# ---------------------------------------------------------------------------
# Vehicle Images
# ---------------------------------------------------------------------------

@router.get("/{vehicle_id}/images")
async def api_get_vehicle_images(vehicle_id: str):
    images = await asyncio.to_thread(_dl.get_vehicle_images, vehicle_id)
    return {"images": images, "count": len(images)}


@router.post("/{vehicle_id}/images/{image_id}/link")
async def api_link_image_to_vehicle(vehicle_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_image_to_vehicle, vehicle_id, image_id)
    return {"ok": True}


@router.get("/issues/{issue_id}/images")
async def api_get_issue_images(issue_id: str):
    images = await asyncio.to_thread(_dl.get_issue_images, issue_id)
    return {"images": images, "count": len(images)}


@router.post("/issues/{issue_id}/images/{image_id}/link")
async def api_link_image_to_issue(issue_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_image_to_issue, issue_id, image_id)
    return {"ok": True}


@router.post("/conditions/{condition_id}/images/{image_id}/link")
async def api_link_image_to_condition(condition_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_image_to_condition, condition_id, image_id)
    return {"ok": True}


@router.delete("/images/{image_id}/unlink")
async def api_unlink_image(image_id: str):
    await asyncio.to_thread(_dl.unlink_image, image_id)
    return {"ok": True}
