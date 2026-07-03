"""Home App API Routes
======================
FastAPI router for home maintenance tasks, task categories, and home issues.
Mounted at /api/apps/home/ by the app platform loader.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.home import data as _dl

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()


# ---------------------------------------------------------------------------
# Home Issues
# ---------------------------------------------------------------------------

class CreateIssueRequest(BaseModel):
    title: str
    description: str = ""
    location: str = ""
    sub_location: str = ""
    category: str = "General"
    severity: str = "minor"
    date_noticed: str | None = None
    notes: str = ""
    created_by: str = ""


@router.get("/issues")
async def api_list_home_issues(status: str = "", location: str = ""):
    issues = await asyncio.to_thread(
        _dl.get_all_issues,
        status if status else None,
        location if location else None,
    )
    locations = await asyncio.to_thread(_dl.get_issue_locations)
    all_locs = await asyncio.to_thread(_dl.get_all_locations_merged)
    return {
        "issues": issues,
        "count": len(issues),
        "locations": locations,
        "all_locations": [loc["name"] for loc in all_locs],
    }


@router.post("/issues")
async def api_create_home_issue(request: CreateIssueRequest, http_request: Request):
    request.created_by = _actor(http_request)
    issue_id = f"hi-{uuid.uuid4().hex[:8]}"
    issue = {
        "id": issue_id,
        "title": request.title.strip(),
        "description": request.description.strip(),
        "location": request.location.strip(),
        "sub_location": request.sub_location.strip(),
        "category": request.category.strip() or "General",
        "severity": request.severity,
        "date_noticed": request.date_noticed or None,
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    result = await asyncio.to_thread(_dl.create_issue, issue)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create issue")
    return result


@router.get("/issues/{issue_id}")
async def api_get_home_issue(issue_id: str):
    issue = await asyncio.to_thread(_dl.get_issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    images = await asyncio.to_thread(_dl.get_issue_images, issue_id)
    return {**issue, "images": images}


class UpdateIssueRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    location: str | None = None
    sub_location: str | None = None
    category: str | None = None
    severity: str | None = None
    status: str | None = None
    date_noticed: str | None = None
    date_fixed: str | None = None
    fix_description: str | None = None
    cost: float | None = None
    notes: str | None = None


@router.put("/issues/{issue_id}")
async def api_update_home_issue(issue_id: str, request: UpdateIssueRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_issue, issue_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue = await asyncio.to_thread(_dl.get_issue, issue_id)
    images = await asyncio.to_thread(_dl.get_issue_images, issue_id)
    return {**issue, "images": images}


@router.delete("/issues/{issue_id}")
async def api_delete_home_issue(issue_id: str):
    ok = await asyncio.to_thread(_dl.delete_issue, issue_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Issue not found")
    return {"ok": True}


@router.get("/issues/{issue_id}/images")
async def api_get_home_issue_images(issue_id: str):
    images = await asyncio.to_thread(_dl.get_issue_images, issue_id)
    return {"images": images, "count": len(images)}


@router.post("/issues/{issue_id}/images/{image_id}/link")
async def api_link_home_issue_image(issue_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_issue_image, issue_id, image_id)
    return {"ok": True}


@router.delete("/issues/{issue_id}/images/{image_id}/unlink")
async def api_unlink_home_issue_image(issue_id: str, image_id: str):
    await asyncio.to_thread(_dl.unlink_issue_image, issue_id, image_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Home Appliances
# ---------------------------------------------------------------------------

class CreateApplianceRequest(BaseModel):
    name: str
    appliance_type: str = "General"
    brand: str = ""
    model: str = ""
    serial_number: str = ""
    location: str = ""
    purchase_date: str | None = None
    purchase_price: float | None = None
    warranty_expires: str | None = None
    notes: str = ""
    created_by: str = ""


@router.get("/appliances")
async def api_list_home_appliances(q: str = "", appliance_type: str = "", location: str = ""):
    def _fetch():
        if q.strip():
            return _dl.search_appliances(q.strip())
        return _dl.get_all_appliances(
            appliance_type if appliance_type else None,
            location if location else None,
        )
    appliances = await asyncio.to_thread(_fetch)
    types = await asyncio.to_thread(_dl.get_appliance_types)
    locations = await asyncio.to_thread(_dl.get_appliance_locations)
    return {
        "appliances": appliances,
        "count": len(appliances),
        "types": types,
        "all_locations": locations,
    }


@router.post("/appliances")
async def api_create_home_appliance(request: CreateApplianceRequest, http_request: Request):
    request.created_by = _actor(http_request)
    appliance_id = f"ha-{uuid.uuid4().hex[:8]}"
    appliance = {
        "id": appliance_id,
        "name": request.name.strip(),
        "appliance_type": request.appliance_type.strip() or "General",
        "brand": request.brand.strip(),
        "model": request.model.strip(),
        "serial_number": request.serial_number.strip(),
        "location": request.location.strip(),
        "purchase_date": request.purchase_date or None,
        "purchase_price": request.purchase_price,
        "warranty_expires": request.warranty_expires or None,
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    result = await asyncio.to_thread(_dl.create_appliance, appliance)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create appliance")
    return result


@router.get("/appliances/{appliance_id}")
async def api_get_home_appliance(appliance_id: str):
    appliance = await asyncio.to_thread(_dl.get_appliance, appliance_id)
    if not appliance:
        raise HTTPException(status_code=404, detail="Appliance not found")
    images = await asyncio.to_thread(_dl.get_appliance_images, appliance_id)
    return {**appliance, "images": images}


class UpdateApplianceRequest(BaseModel):
    name: str | None = None
    appliance_type: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    location: str | None = None
    purchase_date: str | None = None
    purchase_price: float | None = None
    warranty_expires: str | None = None
    notes: str | None = None


@router.put("/appliances/{appliance_id}")
async def api_update_home_appliance(appliance_id: str, request: UpdateApplianceRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_appliance, appliance_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Appliance not found")
    appliance = await asyncio.to_thread(_dl.get_appliance, appliance_id)
    images = await asyncio.to_thread(_dl.get_appliance_images, appliance_id)
    return {**appliance, "images": images}


@router.delete("/appliances/{appliance_id}")
async def api_delete_home_appliance(appliance_id: str):
    ok = await asyncio.to_thread(_dl.delete_appliance, appliance_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Appliance not found")
    return {"ok": True}


@router.get("/appliances/{appliance_id}/images")
async def api_get_home_appliance_images(appliance_id: str):
    images = await asyncio.to_thread(_dl.get_appliance_images, appliance_id)
    return {"images": images, "count": len(images)}


@router.post("/appliances/{appliance_id}/images/{image_id}/link")
async def api_link_home_appliance_image(appliance_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_appliance_image, appliance_id, image_id)
    return {"ok": True}


@router.delete("/appliances/{appliance_id}/images/{image_id}/unlink")
async def api_unlink_home_appliance_image(appliance_id: str, image_id: str):
    await asyncio.to_thread(_dl.unlink_appliance_image, appliance_id, image_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Home Contractors
# ---------------------------------------------------------------------------

def _norm_rating(val):
    """Coerce a rating to an int in 1..5, else None."""
    try:
        r = int(val)
    except (TypeError, ValueError):
        return None
    return r if 1 <= r <= 5 else None


class CreateContractorRequest(BaseModel):
    name: str
    trade: str = "General"
    company: str = ""
    phone: str = ""
    email: str = ""
    rating: int | None = None
    last_used: str | None = None
    jobs_history: str = ""
    notes: str = ""
    created_by: str = ""


@router.get("/contractors")
async def api_list_home_contractors(q: str = "", trade: str = ""):
    def _fetch():
        if q.strip():
            return _dl.search_contractors(q.strip())
        return _dl.get_all_contractors(trade if trade else None)
    contractors = await asyncio.to_thread(_fetch)
    trades = await asyncio.to_thread(_dl.get_contractor_trades)
    return {
        "contractors": contractors,
        "count": len(contractors),
        "trades": trades,
    }


@router.post("/contractors")
async def api_create_home_contractor(request: CreateContractorRequest, http_request: Request):
    request.created_by = _actor(http_request)
    contractor_id = f"hc-{uuid.uuid4().hex[:8]}"
    contractor = {
        "id": contractor_id,
        "name": request.name.strip(),
        "trade": request.trade.strip() or "General",
        "company": request.company.strip(),
        "phone": request.phone.strip(),
        "email": request.email.strip(),
        "rating": _norm_rating(request.rating),
        "last_used": request.last_used or None,
        "jobs_history": request.jobs_history.strip(),
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    result = await asyncio.to_thread(_dl.create_contractor, contractor)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create contractor")
    return result


@router.get("/contractors/{contractor_id}")
async def api_get_home_contractor(contractor_id: str):
    contractor = await asyncio.to_thread(_dl.get_contractor, contractor_id)
    if not contractor:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return contractor


class UpdateContractorRequest(BaseModel):
    name: str | None = None
    trade: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    rating: int | None = None
    last_used: str | None = None
    jobs_history: str | None = None
    notes: str | None = None


@router.put("/contractors/{contractor_id}")
async def api_update_home_contractor(contractor_id: str, request: UpdateContractorRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "rating" in updates:
        updates["rating"] = _norm_rating(updates["rating"])
    ok = await asyncio.to_thread(_dl.update_contractor, contractor_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Contractor not found")
    contractor = await asyncio.to_thread(_dl.get_contractor, contractor_id)
    return contractor


@router.delete("/contractors/{contractor_id}")
async def api_delete_home_contractor(contractor_id: str):
    ok = await asyncio.to_thread(_dl.delete_contractor, contractor_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Home Insurance Policies
# ---------------------------------------------------------------------------

class CreatePolicyRequest(BaseModel):
    provider: str
    policy_number: str = ""
    policy_type: str = "Home"
    coverage_amount: float | None = None
    premium: float | None = None
    premium_period: str = "annual"
    deductible: float | None = None
    renewal_date: str | None = None
    insured_assets: str = ""
    notes: str = ""
    created_by: str = ""


@router.get("/insurance")
async def api_list_home_policies(q: str = "", policy_type: str = ""):
    def _fetch():
        if q.strip():
            return _dl.search_policies(q.strip())
        return _dl.get_all_policies(policy_type if policy_type else None)
    policies = await asyncio.to_thread(_fetch)
    types = await asyncio.to_thread(_dl.get_policy_types)
    return {
        "policies": policies,
        "count": len(policies),
        "types": types,
    }


@router.post("/insurance")
async def api_create_home_policy(request: CreatePolicyRequest, http_request: Request):
    request.created_by = _actor(http_request)
    policy_id = f"hip-{uuid.uuid4().hex[:8]}"
    policy = {
        "id": policy_id,
        "provider": request.provider.strip(),
        "policy_number": request.policy_number.strip(),
        "policy_type": request.policy_type.strip() or "Home",
        "coverage_amount": request.coverage_amount,
        "premium": request.premium,
        "premium_period": request.premium_period.strip() or "annual",
        "deductible": request.deductible,
        "renewal_date": request.renewal_date or None,
        "insured_assets": request.insured_assets.strip(),
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    result = await asyncio.to_thread(_dl.create_policy, policy)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create policy")
    return result


@router.get("/insurance/{policy_id}")
async def api_get_home_policy(policy_id: str):
    policy = await asyncio.to_thread(_dl.get_policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    images = await asyncio.to_thread(_dl.get_policy_images, policy_id)
    return {**policy, "images": images}


class UpdatePolicyRequest(BaseModel):
    provider: str | None = None
    policy_number: str | None = None
    policy_type: str | None = None
    coverage_amount: float | None = None
    premium: float | None = None
    premium_period: str | None = None
    deductible: float | None = None
    renewal_date: str | None = None
    insured_assets: str | None = None
    notes: str | None = None


@router.put("/insurance/{policy_id}")
async def api_update_home_policy(policy_id: str, request: UpdatePolicyRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_policy, policy_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Policy not found")
    policy = await asyncio.to_thread(_dl.get_policy, policy_id)
    images = await asyncio.to_thread(_dl.get_policy_images, policy_id)
    return {**policy, "images": images}


@router.delete("/insurance/{policy_id}")
async def api_delete_home_policy(policy_id: str):
    ok = await asyncio.to_thread(_dl.delete_policy, policy_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"ok": True}


@router.get("/insurance/{policy_id}/images")
async def api_get_home_policy_images(policy_id: str):
    images = await asyncio.to_thread(_dl.get_policy_images, policy_id)
    return {"images": images, "count": len(images)}


@router.post("/insurance/{policy_id}/images/{image_id}/link")
async def api_link_home_policy_image(policy_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_policy_image, policy_id, image_id)
    return {"ok": True}


@router.delete("/insurance/{policy_id}/images/{image_id}/unlink")
async def api_unlink_home_policy_image(policy_id: str, image_id: str):
    await asyncio.to_thread(_dl.unlink_policy_image, policy_id, image_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Maintenance Tasks
# ---------------------------------------------------------------------------

@router.get("/maintenance/tasks")
async def api_list_tasks(category: str = "", q: str = "", include_inactive: bool = False):
    """List home maintenance tasks."""
    def _fetch():
        if q.strip():
            return _dl.search_tasks(q.strip())
        if category.strip():
            return _dl.get_tasks_by_category(category.strip())
        return _dl.get_all_tasks(include_inactive=include_inactive)
    tasks = await asyncio.to_thread(_fetch)
    categories = await asyncio.to_thread(_dl.get_task_categories)
    return {"tasks": tasks, "count": len(tasks), "categories": categories}


@router.get("/maintenance/tasks/categories")
async def api_task_categories():
    cats = await asyncio.to_thread(_dl.get_task_categories)
    return {"categories": cats}


@router.get("/maintenance/log")
async def api_recent_log(limit: int = 20):
    entries = await asyncio.to_thread(_dl.get_recent_log, limit)
    return {"entries": entries}


# ---------------------------------------------------------------------------
# Maintenance Task Categories
# ---------------------------------------------------------------------------

@router.get("/maintenance/categories")
async def api_list_task_categories():
    cats = await asyncio.to_thread(_dl.get_all_task_categories)
    return {"categories": cats}


class CreateTaskCategoryRequest(BaseModel):
    name: str
    color: str = "slate"


@router.post("/maintenance/categories")
async def api_create_task_category(request: CreateTaskCategoryRequest):
    cat_id = f"htcat-{uuid.uuid4().hex[:8]}"
    cat = await asyncio.to_thread(_dl.create_task_category, cat_id, request.name.strip(), request.color)
    if not cat:
        raise HTTPException(status_code=400, detail="Failed to create category (name may already exist)")
    return cat


class UpdateTaskCategoryRequest(BaseModel):
    name: str | None = None
    color: str | None = None
    sort_order: int | None = None


@router.put("/maintenance/categories/{cat_id}")
async def api_update_task_category(cat_id: str, request: UpdateTaskCategoryRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_task_category, cat_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Category not found")
    cats = await asyncio.to_thread(_dl.get_all_task_categories)
    return next((c for c in cats if c["id"] == cat_id), {"ok": True})


@router.delete("/maintenance/categories/{cat_id}")
async def api_delete_task_category(cat_id: str):
    ok = await asyncio.to_thread(_dl.delete_task_category, cat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"ok": True}


class CreateTaskRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "General"
    task_type: str = "recurring"
    interval_days: int | None = None
    next_due_at: str | None = None
    last_done_at: str | None = None
    notes: str = ""
    created_by: str = ""


@router.post("/maintenance/tasks")
async def api_create_task(request: CreateTaskRequest, http_request: Request):
    request.created_by = _actor(http_request)
    task_id = f"hmt-{uuid.uuid4().hex[:8]}"
    task = {
        "id": task_id,
        "name": request.name.strip(),
        "description": request.description.strip(),
        "category": request.category.strip() or "General",
        "task_type": request.task_type,
        "interval_days": request.interval_days,
        "next_due_at": request.next_due_at or None,
        "last_done_at": request.last_done_at or None,
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    result = await asyncio.to_thread(_dl.create_task, task)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to create task")
    return result


@router.get("/maintenance/tasks/{task_id}")
async def api_get_task(task_id: str):
    task = await asyncio.to_thread(_dl.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    log = await asyncio.to_thread(_dl.get_task_log, task_id)
    return {**task, "log": log}


class UpdateTaskRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    task_type: str | None = None
    interval_days: int | None = None
    next_due_at: str | None = None
    last_done_at: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.put("/maintenance/tasks/{task_id}")
async def api_update_task(task_id: str, request: UpdateTaskRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_task, task_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    task = await asyncio.to_thread(_dl.get_task, task_id)
    log = await asyncio.to_thread(_dl.get_task_log, task_id)
    return {**task, "log": log}


@router.delete("/maintenance/tasks/{task_id}")
async def api_delete_task(task_id: str):
    ok = await asyncio.to_thread(_dl.delete_task, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


class CompleteTaskRequest(BaseModel):
    completed_at: str = ""
    completed_by: str = ""
    notes: str = ""


@router.post("/maintenance/tasks/{task_id}/complete")
async def api_complete_task(task_id: str, request: CompleteTaskRequest, http_request: Request):
    request.completed_by = _actor(http_request)
    result = await asyncio.to_thread(
        _dl.complete_task,
        task_id,
        request.completed_at,
        request.completed_by,
        request.notes,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/maintenance/tasks/{task_id}/log")
async def api_task_log(task_id: str, limit: int = 50):
    log = await asyncio.to_thread(_dl.get_task_log, task_id, limit)
    return {"log": log, "count": len(log)}


@router.delete("/maintenance/log/{log_id}")
async def api_delete_log_entry(log_id: str):
    ok = await asyncio.to_thread(_dl.delete_log_entry, log_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return {"ok": True}


