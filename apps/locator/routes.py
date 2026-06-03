"""Locator App API Routes
=========================
FastAPI router for item locator CRUD, storage locations, and image links.
Mounted at /api/apps/locator/ by the app platform loader.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.locator import data as _dl

router = APIRouter()


def _actor(request: Request) -> str:
    """The authenticated actor's name. Auth is unconditional, so a verified
    principal is always present; the client-supplied value is never trusted."""
    p = current_principal(request)
    return (p["name"] if p else "").lower().strip()


# ---------------------------------------------------------------------------
# Located Items — list / search
# ---------------------------------------------------------------------------

@router.get("")
async def api_list_located_items(location: str = "", category: str = "", q: str = ""):
    """List located items, optionally filtered by location, category, or search query."""
    def _fetch():
        if q.strip():
            return _dl.search_items(q.strip())
        if location.strip():
            return _dl.filter_by_location(location.strip())
        if category.strip():
            return _dl.filter_by_category(category.strip())
        return _dl.get_all_items()
    items = await asyncio.to_thread(_fetch)
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@router.get("/locations")
async def api_list_item_locations():
    locs = await asyncio.to_thread(_dl.get_all_locations_merged)
    return {"locations": locs}


class CreateLocationRequest(BaseModel):
    name: str
    description: str = ""


@router.post("/locations")
async def api_create_item_location(request: CreateLocationRequest):
    loc_id = f"iloc-{uuid.uuid4().hex[:8]}"
    loc = await asyncio.to_thread(_dl.create_location, loc_id, request.name.strip(), request.description.strip())
    if not loc:
        raise HTTPException(status_code=400, detail="Failed to create location (name may already exist)")
    return loc


@router.delete("/locations/{loc_id}")
async def api_delete_item_location(loc_id: str):
    ok = await asyncio.to_thread(_dl.delete_location, loc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Located Items — create
# ---------------------------------------------------------------------------

class CreateLocatedItemRequest(BaseModel):
    name: str
    created_by: str = ""
    location: str = ""
    sub_location: str = ""
    category: str = ""
    description: str = ""
    tags: list[str] = []
    quantity: int | None = None
    notes: str = ""


@router.post("")
async def api_create_located_item(request: CreateLocatedItemRequest, http_request: Request):
    request.created_by = _actor(http_request)
    item_id = f"loc-{uuid.uuid4().hex[:8]}"
    item = {
        "id": item_id,
        "name": request.name.strip(),
        "description": request.description.strip(),
        "location": request.location.strip(),
        "sub_location": request.sub_location.strip(),
        "category": request.category.strip(),
        "tags": request.tags,
        "quantity": request.quantity,
        "notes": request.notes.strip(),
        "created_by": request.created_by.strip(),
    }
    await asyncio.to_thread(_dl.save_item, item)
    return _dl.get_item(item_id)


# ---------------------------------------------------------------------------
# Located Items — CRUD (/{item_id} wildcard — keep AFTER all static routes)
# ---------------------------------------------------------------------------

@router.get("/{item_id}")
async def api_get_located_item(item_id: str):
    item = await asyncio.to_thread(_dl.get_item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


class UpdateLocatedItemRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    location: str | None = None
    sub_location: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    quantity: int | None = None
    notes: str | None = None


@router.put("/{item_id}")
async def api_update_located_item(item_id: str, request: UpdateLocatedItemRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await asyncio.to_thread(_dl.update_item, item_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return await asyncio.to_thread(_dl.get_item, item_id)


@router.delete("/{item_id}")
async def api_delete_located_item(item_id: str):
    ok = await asyncio.to_thread(_dl.delete_item, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Item Images
# ---------------------------------------------------------------------------

@router.get("/{item_id}/images")
async def api_get_item_images(item_id: str):
    images = await asyncio.to_thread(_dl.get_item_images, item_id)
    return {"images": images, "count": len(images)}


@router.post("/{item_id}/images/{image_id}/link")
async def api_link_image(item_id: str, image_id: str):
    await asyncio.to_thread(_dl.link_image, item_id, image_id)
    return {"ok": True}


@router.delete("/{item_id}/images/{image_id}/unlink")
async def api_unlink_image(item_id: str, image_id: str):
    await asyncio.to_thread(_dl.unlink_image, item_id, image_id)
    return {"ok": True}
