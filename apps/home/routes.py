"""Home App API Routes
======================
FastAPI router for home maintenance tasks, task categories, and home issues.
Mounted at /api/apps/home/ by the app platform loader.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.home import data as _dl

router = APIRouter()


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
async def api_create_home_issue(request: CreateIssueRequest):
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
async def api_create_task(request: CreateTaskRequest):
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
async def api_complete_task(task_id: str, request: CompleteTaskRequest):
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


