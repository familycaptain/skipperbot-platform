"""Homeopathy App API Routes
==============================
FastAPI router for homeopathy inventory CRUD.
Mounted at /api/apps/homeopathy/ by the app platform loader.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request

from apps.homeopathy import data as _dl

router = APIRouter()


# --- Sources ---

@router.get("/sources")
async def api_homeo_list_sources():
    sources = await asyncio.to_thread(_dl.get_all_sources)
    return {"sources": sources, "count": len(sources)}


@router.post("/sources")
async def api_homeo_create_source(request: Request):
    body = await request.json()
    src_id = f"hsrc-{uuid.uuid4().hex[:8]}"
    _dl.save_source({"id": src_id, **body})
    return await asyncio.to_thread(_dl.get_source, src_id)


@router.put("/sources/{src_id}")
async def api_homeo_update_source(src_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_source, src_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found")
    return await asyncio.to_thread(_dl.get_source, src_id)


@router.delete("/sources/{src_id}")
async def api_homeo_delete_source(src_id: str):
    ok = await asyncio.to_thread(_dl.delete_source, src_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"ok": True}


# --- Medicines ---

@router.get("/medicines")
async def api_homeo_list_medicines():
    meds = await asyncio.to_thread(_dl.get_all_medicines)
    return {"medicines": meds, "count": len(meds)}


@router.post("/medicines")
async def api_homeo_create_medicine(request: Request):
    body = await request.json()
    med_id = f"hmed-{uuid.uuid4().hex[:8]}"
    _dl.save_medicine({"id": med_id, **body})
    return await asyncio.to_thread(_dl.get_medicine, med_id)


@router.put("/medicines/{med_id}")
async def api_homeo_update_medicine(med_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_medicine, med_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return await asyncio.to_thread(_dl.get_medicine, med_id)


@router.delete("/medicines/{med_id}")
async def api_homeo_delete_medicine(med_id: str):
    ok = await asyncio.to_thread(_dl.delete_medicine, med_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return {"ok": True}


# --- Remedies ---

@router.get("/remedies")
async def api_homeo_list_remedies(medicine_id: str = ""):
    remedies = await asyncio.to_thread(_dl.get_all_remedies, medicine_id if medicine_id else None)
    return {"remedies": remedies, "count": len(remedies)}


@router.post("/remedies")
async def api_homeo_create_remedy(request: Request):
    body = await request.json()
    rem_id = f"hrem-{uuid.uuid4().hex[:8]}"
    _dl.save_remedy({"id": rem_id, **body})
    return await asyncio.to_thread(_dl.get_remedy, rem_id)


@router.put("/remedies/{rem_id}")
async def api_homeo_update_remedy(rem_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_remedy, rem_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Remedy not found")
    return await asyncio.to_thread(_dl.get_remedy, rem_id)


@router.delete("/remedies/{rem_id}")
async def api_homeo_delete_remedy(rem_id: str):
    ok = await asyncio.to_thread(_dl.delete_remedy, rem_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Remedy not found")
    return {"ok": True}


# --- Bottle Sizes ---

@router.get("/sizes")
async def api_homeo_list_sizes():
    sizes = await asyncio.to_thread(_dl.get_all_bottle_sizes)
    return {"sizes": sizes, "count": len(sizes)}


@router.post("/sizes")
async def api_homeo_create_size(request: Request):
    body = await request.json()
    size_id = f"hsize-{uuid.uuid4().hex[:8]}"
    _dl.save_bottle_size({"id": size_id, **body})
    return {"id": size_id, **body}


@router.put("/sizes/{size_id}")
async def api_homeo_update_size(size_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_bottle_size, size_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Bottle size not found")
    return {"ok": True, "id": size_id}


@router.delete("/sizes/{size_id}")
async def api_homeo_delete_size(size_id: str):
    ok = await asyncio.to_thread(_dl.delete_bottle_size, size_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Bottle size not found")
    return {"ok": True}


# --- Locations ---

@router.get("/locations")
async def api_homeo_list_locations():
    locs = await asyncio.to_thread(_dl.get_all_locations)
    return {"locations": locs, "count": len(locs)}


@router.post("/locations")
async def api_homeo_create_location(request: Request):
    body = await request.json()
    loc_id = f"hloc-{uuid.uuid4().hex[:8]}"
    _dl.save_location({"id": loc_id, **body})
    return {"id": loc_id, **body}


@router.put("/locations/{loc_id}")
async def api_homeo_update_location(loc_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_location, loc_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"ok": True, "id": loc_id}


@router.delete("/locations/{loc_id}")
async def api_homeo_delete_location(loc_id: str):
    ok = await asyncio.to_thread(_dl.delete_location, loc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"ok": True}


# --- Bottles (inventory) ---

@router.get("/bottles")
async def api_homeo_list_bottles(location_id: str = "", low: bool = False,
                                  remedy_id: str = "", strength: str = ""):
    bottles = await asyncio.to_thread(
        _dl.get_all_bottles,
        location_id=location_id if location_id else None,
        low_only=low,
        remedy_id=remedy_id if remedy_id else None,
        strength=strength if strength else None,
    )
    return {"bottles": bottles, "count": len(bottles)}


@router.get("/bottles/grouped")
async def api_homeo_bottles_grouped(low: bool = False):
    grouped = await asyncio.to_thread(_dl.get_bottles_grouped_by_strength, low_only=low)
    return grouped


@router.post("/bottles")
async def api_homeo_create_bottle(request: Request):
    body = await request.json()
    bot_id = f"hbot-{uuid.uuid4().hex[:8]}"
    _dl.save_bottle({"id": bot_id, **body})
    return await asyncio.to_thread(_dl.get_bottle, bot_id)


@router.put("/bottles/{bot_id}")
async def api_homeo_update_bottle(bot_id: str, request: Request):
    body = await request.json()
    ok = await asyncio.to_thread(_dl.update_bottle, bot_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Bottle not found")
    return await asyncio.to_thread(_dl.get_bottle, bot_id)


@router.patch("/bottles/{bot_id}/check")
async def api_homeo_check_bottle(bot_id: str, request: Request):
    body = await request.json()
    fullness = body.get("fullness", 100)
    ok = await asyncio.to_thread(_dl.check_bottle, bot_id, fullness)
    if not ok:
        raise HTTPException(status_code=404, detail="Bottle not found")
    return await asyncio.to_thread(_dl.get_bottle, bot_id)


@router.post("/bottles/bulk-check")
async def api_homeo_bulk_check(request: Request):
    body = await request.json()
    bottle_ids = body.get("bottle_ids", [])
    fullness_map = body.get("fullness_map", {})
    await asyncio.to_thread(_dl.bulk_check, bottle_ids, fullness_map if fullness_map else None)
    return {"ok": True, "checked": len(bottle_ids)}


@router.delete("/bottles/{bot_id}")
async def api_homeo_delete_bottle(bot_id: str):
    ok = await asyncio.to_thread(_dl.delete_bottle, bot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Bottle not found")
    return {"ok": True}


# --- Reorder / Search ---

@router.get("/reorder")
async def api_homeo_reorder():
    bottles = await asyncio.to_thread(_dl.get_reorder_list)
    return {"bottles": bottles, "count": len(bottles)}


@router.get("/search")
async def api_homeo_search(q: str = ""):
    if not q.strip():
        return {"bottles": [], "count": 0}
    bottles = await asyncio.to_thread(_dl.search_bottles, q.strip())
    return {"bottles": bottles, "count": len(bottles)}
