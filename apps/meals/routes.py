"""Meals App API Routes
=======================
FastAPI router for meals, components, cuisines, and tags CRUD + discover.
Mounted at /api/apps/meals/ by the app platform loader.
"""

import asyncio
import json
import random
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.meals import data as _dl

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()

# ---------------------------------------------------------------------------
# SSE broadcast
# ---------------------------------------------------------------------------

_sse_clients: set[asyncio.Queue] = set()


def _broadcast(event_type: str, meal_id: str, meal_name: str) -> None:
    data = json.dumps({"type": event_type, "id": meal_id, "name": meal_name})
    for q in list(_sse_clients):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


@router.get("/events")
async def meal_events():
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    _sse_clients.add(queue)

    async def stream():
        try:
            yield "data: {\"type\":\"connected\"}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _sse_clients.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateTagRequest(BaseModel):
    name: str

class CreateComponentRequest(BaseModel):
    name: str
    type: str = "other"
    description: str = ""
    tags: list[str] = []
    recipe_id: str | None = None

class UpdateComponentRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    recipe_id: str | None = None

class CreateMealRequest(BaseModel):
    name: str
    effort: str = "medium"
    description: str = ""
    tags: list[str] = []
    notes: str = ""
    rating: int | None = None
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    recipe_doc_id: str | None = None
    created_by: str = "user"

class UpdateMealRequest(BaseModel):
    name: str | None = None
    effort: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    rating: int | None = None
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    recipe_doc_id: str | None = None

class ComponentLinkItem(BaseModel):
    component_id: str
    role: str = "side"
    sort_order: int = 0
    notes: str = ""

class SetMealComponentsRequest(BaseModel):
    components: list[ComponentLinkItem]

class DiscoverFilter(BaseModel):
    type: str    # cuisine | effort | tag | component
    mode: str    # include | exclude
    value: str

class DiscoverRequest(BaseModel):
    filters: list[DiscoverFilter] = []


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@router.get("/tag-cloud")
async def api_tag_cloud():
    tags = await asyncio.to_thread(_dl.tag_cloud)
    return {"tags": tags}


@router.get("/tags")
async def api_list_tags(with_counts: bool = False):
    tags = await asyncio.to_thread(_dl.list_tags, with_counts)
    return {"tags": tags}


@router.post("/tags")
async def api_create_tag(req: CreateTagRequest):
    if not req.name.strip():
        raise HTTPException(400, "name is required")
    tag_id = f"mtg-{uuid.uuid4().hex[:8]}"
    tag = await asyncio.to_thread(_dl.create_tag, tag_id, req.name.strip())
    if not tag:
        raise HTTPException(500, "Failed to create tag")
    return tag


@router.delete("/tags/{tag_id}")
async def api_delete_tag(tag_id: str):
    ok = await asyncio.to_thread(_dl.delete_tag, tag_id)
    if not ok:
        raise HTTPException(404, "Tag not found")
    return {"deleted": tag_id}


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

@router.get("/components")
async def api_list_components(q: str = "", type: str = ""):
    components = await asyncio.to_thread(_dl.list_components, q, type)
    return {"components": components, "count": len(components)}


@router.post("/components")
async def api_create_component(req: CreateComponentRequest):
    if not req.name.strip():
        raise HTTPException(400, "name is required")
    comp_id = f"mc-{uuid.uuid4().hex[:8]}"
    comp = await asyncio.to_thread(
        _dl.create_component, comp_id, req.name.strip(), req.type,
        req.description, req.tags, req.recipe_id)
    if not comp:
        raise HTTPException(500, "Failed to create component")
    return comp


@router.get("/components/{component_id}")
async def api_get_component(component_id: str):
    comp = await asyncio.to_thread(_dl.get_component, component_id)
    if not comp:
        raise HTTPException(404, "Component not found")
    return comp


@router.put("/components/{component_id}")
async def api_update_component(component_id: str, req: UpdateComponentRequest):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    comp = await asyncio.to_thread(_dl.update_component, component_id, **fields)
    if not comp:
        raise HTTPException(404, "Component not found")
    return comp


@router.delete("/components/{component_id}")
async def api_delete_component(component_id: str):
    ok = await asyncio.to_thread(_dl.delete_component, component_id)
    if not ok:
        raise HTTPException(404, "Component not found")
    return {"deleted": component_id}


# ---------------------------------------------------------------------------
# Meals — list + create
# ---------------------------------------------------------------------------

@router.get("")
async def api_list_meals(effort: str = "", q: str = "", tag: str = "", include_photos: bool = False):
    meals = await asyncio.to_thread(_dl.list_meals, effort, q, tag)
    if include_photos and meals:
        meal_ids = [m["id"] for m in meals]
        photos_by_meal = await asyncio.to_thread(_dl.get_photos_for_meals, meal_ids)
        for m in meals:
            m["photos"] = photos_by_meal.get(m["id"], [])
    return {"meals": meals, "count": len(meals)}


@router.post("")
async def api_create_meal(req: CreateMealRequest, request: Request):
    req.created_by = _actor(request)
    if not req.name.strip():
        raise HTTPException(400, "name is required")
    if req.effort not in ("low", "medium", "high"):
        raise HTTPException(400, "effort must be low, medium, or high")
    if not req.tags:
        raise HTTPException(400, "at least one tag is required (include a cuisine tag like 'american', 'italian', etc.)")

    meal_id = f"ml-{uuid.uuid4().hex[:8]}"
    meal = await asyncio.to_thread(
        _dl.create_meal,
        meal_id, req.name.strip(), req.created_by,
        req.effort, req.description, req.tags,
        req.notes, req.rating, req.prep_time_min, req.cook_time_min,
        req.recipe_doc_id)
    if not meal:
        raise HTTPException(500, "Failed to create meal")
    _broadcast("meal_created", meal["id"], meal["name"])
    return meal


# ---------------------------------------------------------------------------
# Meals — discover (MUST come before /{meal_id} to avoid route capture)
# ---------------------------------------------------------------------------

@router.post("/discover")
async def api_discover_meals(req: DiscoverRequest):
    filters = [f.model_dump() for f in req.filters]
    meals = await asyncio.to_thread(_dl.discover_meals, filters)
    return {"meals": meals, "count": len(meals)}


@router.post("/discover/random")
async def api_discover_random(req: DiscoverRequest):
    filters = [f.model_dump() for f in req.filters]
    meals = await asyncio.to_thread(_dl.discover_meals, filters)
    if not meals:
        return {"meal": None, "total": 0}
    return {"meal": random.choice(meals), "total": len(meals)}


# ---------------------------------------------------------------------------
# Meal Log (MUST come before /{meal_id} to avoid route capture)
# ---------------------------------------------------------------------------

class MealLogRequest(BaseModel):
    description: str
    meal_type: str = "dinner"
    meal_id: str | None = None
    logged_by: str = "user"
    notes: str = ""
    logged_date: str = ""


@router.get("/meal-log")
async def api_get_meal_log(days: int = 30, meal_type: str = ""):
    entries = await asyncio.to_thread(_dl.get_meal_log, days, meal_type)
    return {"entries": entries, "count": len(entries)}


@router.get("/meal-log/today")
async def api_get_today_meals():
    from datetime import date
    today = date.today().isoformat()
    dinner = await asyncio.to_thread(_dl.get_meal_log_for_date, today, "dinner")
    lunch = await asyncio.to_thread(_dl.get_meal_log_for_date, today, "lunch")
    return {"dinner": dinner or None, "lunch": lunch or None,
            "dinner_logged": bool(dinner), "lunch_logged": bool(lunch)}


@router.post("/meal-log")
async def api_create_meal_log(req: MealLogRequest, request: Request):
    req.logged_by = _actor(request)
    from datetime import date
    logged_date = req.logged_date.strip() if req.logged_date else date.today().isoformat()
    meal_type = req.meal_type if req.meal_type in ("dinner", "lunch", "breakfast", "snack") else "dinner"
    log_id = f"dl-{uuid.uuid4().hex[:8]}"
    entry = await asyncio.to_thread(
        _dl.create_meal_log,
        log_id, logged_date, req.description,
        req.logged_by, req.meal_id, req.notes, meal_type,
    )
    if not entry:
        raise HTTPException(400, "Could not create meal log entry (date/type may already be logged)")
    return entry


# ---------------------------------------------------------------------------
# Meals — single item CRUD (wildcard /{meal_id} MUST be last)
# ---------------------------------------------------------------------------

@router.get("/{meal_id}")
async def api_get_meal(meal_id: str):
    meal = await asyncio.to_thread(_dl.get_meal, meal_id)
    if not meal:
        raise HTTPException(404, "Meal not found")
    return meal


@router.put("/{meal_id}")
async def api_update_meal(meal_id: str, req: UpdateMealRequest):
    existing = await asyncio.to_thread(_dl.get_meal, meal_id)
    if not existing:
        raise HTTPException(404, "Meal not found")
    if req.effort and req.effort not in ("low", "medium", "high"):
        raise HTTPException(400, "effort must be low, medium, or high")
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    meal = await asyncio.to_thread(_dl.update_meal, meal_id, **fields)
    return meal


@router.delete("/{meal_id}")
async def api_delete_meal(meal_id: str):
    ok = await asyncio.to_thread(_dl.delete_meal, meal_id)
    if not ok:
        raise HTTPException(404, "Meal not found")
    return {"deleted": meal_id}


# ---------------------------------------------------------------------------
# Meal Photos
# ---------------------------------------------------------------------------

@router.get("/{meal_id}/photos")
async def api_get_meal_photos(meal_id: str):
    existing = await asyncio.to_thread(_dl.get_meal, meal_id)
    if not existing:
        raise HTTPException(404, "Meal not found")
    photos = await asyncio.to_thread(_dl.get_meal_photos, meal_id)
    return {"photos": photos, "count": len(photos)}


@router.post("/{meal_id}/photos/{image_id}/link")
async def api_link_meal_photo(meal_id: str, image_id: str):
    existing = await asyncio.to_thread(_dl.get_meal, meal_id)
    if not existing:
        raise HTTPException(404, "Meal not found")
    await asyncio.to_thread(_dl.link_meal_photo, meal_id, image_id)
    return {"ok": True}


@router.delete("/{meal_id}/photos/{image_id}/unlink")
async def api_unlink_meal_photo(meal_id: str, image_id: str):
    await asyncio.to_thread(_dl.unlink_meal_photo, meal_id, image_id)
    return {"ok": True}


@router.post("/{meal_id}/photos/{image_id}/set-primary")
async def api_set_meal_photo_primary(meal_id: str, image_id: str):
    await asyncio.to_thread(_dl.set_meal_photo_primary, meal_id, image_id)
    return {"ok": True}


@router.put("/{meal_id}/components")
async def api_set_meal_components(meal_id: str, req: SetMealComponentsRequest):
    existing = await asyncio.to_thread(_dl.get_meal, meal_id)
    if not existing:
        raise HTTPException(404, "Meal not found")
    components = [c.model_dump() for c in req.components]
    links = await asyncio.to_thread(_dl.set_meal_components, meal_id, components)
    return {"components": links, "count": len(links)}
