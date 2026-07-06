"""Chores App API Routes — FastAPI router for kids/zones/chores/completions.

Mounted at /api/apps/chores/ by the app platform loader.
"""

import asyncio
import datetime as dt
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.chores import data as _dl
from apps.chores import store as _store
from data_layer import users as _users

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateKidRequest(BaseModel):
    # Optional: when linking a household account (the dropdown add flow) the kid's
    # display name is derived from the account. Freeform callers still pass a name.
    name: Optional[str] = None
    color: str = "#888888"
    sort_order: int = 0
    user_id: Optional[str] = None
    notify_morning: bool = True
    notify_evening: bool = False
    acted_by: str


class UpdateKidRequest(BaseModel):
    acted_by: str
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    user_id: Optional[str] = None
    notify_morning: Optional[bool] = None
    notify_evening: Optional[bool] = None
    active: Optional[bool] = None


class CreateZoneRequest(BaseModel):
    name: str
    rotation_start: str  # YYYY-MM-DD
    description: str = ""
    sort_order: int = 0
    member_kid_ids: list[str] = []
    acted_by: str


class UpdateZoneRequest(BaseModel):
    acted_by: str
    name: Optional[str] = None
    description: Optional[str] = None
    rotation_start: Optional[str] = None
    sort_order: Optional[int] = None
    member_kid_ids: Optional[list[str]] = None


class CreateChoreRequest(BaseModel):
    zone_id: str
    dow: int
    name: str
    note: str = ""
    position: Optional[int] = None
    acted_by: str


class UpdateChoreRequest(BaseModel):
    acted_by: str
    name: Optional[str] = None
    note: Optional[str] = None
    dow: Optional[int] = None
    position: Optional[int] = None
    active: Optional[bool] = None


class CompleteChoreRequest(BaseModel):
    chore_id: str
    kid_id: str
    date: Optional[str] = None  # default: today
    acted_by: str
    note: str = ""


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _actor(request: Request, fallback: str = "") -> str:
    """The authoritative actor name, taken from the verified principal.

    Auth is unconditional, so a principal is always present on this route; the
    client-supplied ``acted_by`` is never trusted (otherwise a kid could spoof a
    parent's name to pass ``_require_parent``). ``fallback`` is vestigial.
    """
    p = current_principal(request)
    return p["name"] if p else ""


def _get_actor(user_id: str) -> dict:
    actor = _users.get_user(user_id)
    if not actor:
        raise HTTPException(status_code=400, detail=f"Unknown user: {user_id}")
    return actor


def _is_parent(actor: dict) -> bool:
    return _users.has_any_role(actor, "parent", "admin")


def _require_parent(user_id: str, detail: str) -> dict:
    actor = _get_actor(user_id)
    if not _is_parent(actor):
        raise HTTPException(status_code=403, detail=detail)
    return actor


def _can_act_on_kid(actor: dict, kid: dict) -> bool:
    """Parents can act on any kid; a kid can only act on themselves."""
    if _is_parent(actor):
        return True
    return kid.get("user_id") == actor["name"]


# ---------------------------------------------------------------------------
# Today / Week
# ---------------------------------------------------------------------------

@router.get("/today")
async def api_today(date: str = ""):
    target_date = dt.date.fromisoformat(date) if date else _store.today_local()
    return await asyncio.to_thread(_store.today_by_kid, target_date)


@router.get("/week")
async def api_week(start: str = ""):
    start_date = dt.date.fromisoformat(start) if start else None
    return await asyncio.to_thread(_store.week_by_kid, start_date)


# ---------------------------------------------------------------------------
# Kids
# ---------------------------------------------------------------------------

@router.get("/kids")
async def api_list_kids(include_inactive: bool = False):
    kids = await asyncio.to_thread(_dl.list_kids, active_only=not include_inactive)
    return {"kids": kids, "count": len(kids)}


@router.get("/kids/{kid_id}")
async def api_get_kid(kid_id: str):
    kid = await asyncio.to_thread(_dl.get_kid, kid_id)
    if not kid:
        raise HTTPException(status_code=404, detail="Kid not found")
    return kid


@router.get("/members/eligible")
async def api_eligible_members(request: Request):
    """Household accounts eligible to link as a NEW kid (the add-kid dropdown):
    every non-bot human account (get_human_users already excludes bots) MINUS any
    account already linked to an ACTIVE kid. Label = display name (fallback
    username). There is no 'kid' role today (#80 adds richer roles), so parents/
    admins/primary humans all qualify — the only exclusion is the bot."""
    members = await asyncio.to_thread(_dl.eligible_member_accounts)
    return {"members": members, "count": len(members)}


@router.post("/kids")
async def api_create_kid(req: CreateKidRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    await asyncio.to_thread(_require_parent, req.acted_by, "Only parents can create kids")
    # Dropdown add flow: derive the kid's display name from the linked account.
    name = (req.name or "").strip()
    if req.user_id and not name:
        name = await asyncio.to_thread(_users.display_name_for, req.user_id)
    if not name:
        raise HTTPException(status_code=400, detail="A kid name (or a linked account) is required")
    kid = await asyncio.to_thread(
        _dl.create_kid,
        name=name, color=req.color, sort_order=req.sort_order,
        user_id=req.user_id, notify_morning=req.notify_morning,
        notify_evening=req.notify_evening, by=req.acted_by,
    )
    _store._emit("kid.added", {"kid_id": kid["id"], "name": kid["name"]})
    return kid


@router.patch("/kids/{kid_id}")
async def api_update_kid(kid_id: str, req: UpdateKidRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    await asyncio.to_thread(_require_parent, req.acted_by, "Only parents can edit kids")
    fields = {k: v for k, v in req.model_dump().items() if k != "acted_by"}
    kid = await asyncio.to_thread(_dl.update_kid, kid_id, by=req.acted_by, **fields)
    if not kid:
        raise HTTPException(status_code=404, detail="Kid not found")
    _store._emit("kid.updated", {"kid_id": kid["id"], "fields": list(fields.keys())})
    return kid


@router.delete("/kids/{kid_id}")
async def api_delete_kid(kid_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent, acted_by, "Only parents can remove kids")
    ok = await asyncio.to_thread(_dl.soft_delete_kid, kid_id, by=acted_by)
    if not ok:
        raise HTTPException(status_code=404, detail="Kid not found")
    _store._emit("kid.removed", {"kid_id": kid_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@router.get("/zones")
async def api_list_zones():
    zones = await asyncio.to_thread(_dl.list_zones)
    for z in zones:
        z["members"] = await asyncio.to_thread(_dl.get_zone_members, z["id"])
        z["chore_count"] = len(await asyncio.to_thread(_dl.list_chores, z["id"]))
    return {"zones": zones, "count": len(zones)}


@router.get("/zones/{zone_id}")
async def api_get_zone(zone_id: str):
    zone = await asyncio.to_thread(_dl.get_zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone["members"] = await asyncio.to_thread(_dl.get_zone_members, zone_id)
    zone["chores"] = await asyncio.to_thread(_dl.list_chores, zone_id)
    return zone


@router.post("/zones")
async def api_create_zone(req: CreateZoneRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    await asyncio.to_thread(_require_parent, req.acted_by, "Only parents can create zones")
    zone = await asyncio.to_thread(
        _dl.create_zone,
        name=req.name, rotation_start=req.rotation_start,
        description=req.description, sort_order=req.sort_order, by=req.acted_by,
    )
    if req.member_kid_ids:
        await asyncio.to_thread(_dl.set_zone_members, zone["id"], req.member_kid_ids)
    _store._emit("zone.added", {
        "zone_id": zone["id"], "name": zone["name"],
        "member_kid_ids": req.member_kid_ids,
    })
    zone["members"] = await asyncio.to_thread(_dl.get_zone_members, zone["id"])
    return zone


@router.patch("/zones/{zone_id}")
async def api_update_zone(zone_id: str, req: UpdateZoneRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    await asyncio.to_thread(_require_parent, req.acted_by, "Only parents can edit zones")
    updates = {k: v for k, v in req.model_dump().items()
               if k not in ("acted_by", "member_kid_ids") and v is not None}
    if updates:
        zone = await asyncio.to_thread(_dl.update_zone, zone_id, by=req.acted_by, **updates)
        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")
    else:
        zone = await asyncio.to_thread(_dl.get_zone, zone_id)
        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")
    if req.member_kid_ids is not None:
        await asyncio.to_thread(_dl.set_zone_members, zone_id, req.member_kid_ids)
    zone["members"] = await asyncio.to_thread(_dl.get_zone_members, zone_id)
    _store._emit("zone.updated", {
        "zone_id": zone_id,
        "fields": list(updates.keys()) + (["members"] if req.member_kid_ids is not None else []),
    })
    return zone


@router.delete("/zones/{zone_id}")
async def api_delete_zone(zone_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent, acted_by, "Only parents can delete zones")
    try:
        ok = await asyncio.to_thread(_dl.delete_zone, zone_id, by=acted_by)
    except Exception as e:
        # FK from chore_completions blocks delete if there's history
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete zone — completions reference its chores. {e}",
        )
    if not ok:
        raise HTTPException(status_code=404, detail="Zone not found")
    _store._emit("zone.removed", {"zone_id": zone_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chores
# ---------------------------------------------------------------------------

@router.get("/chores")
async def api_list_chores(zone_id: str = "", include_inactive: bool = False):
    chores = await asyncio.to_thread(
        _dl.list_chores,
        zone_id=zone_id or None,
        active_only=not include_inactive,
    )
    return {"chores": chores, "count": len(chores)}


@router.get("/chores/{chore_id}")
async def api_get_chore(chore_id: str):
    chore = await asyncio.to_thread(_dl.get_chore, chore_id)
    if not chore:
        raise HTTPException(status_code=404, detail="Chore not found")
    return chore


@router.post("/chores")
async def api_create_chore(req: CreateChoreRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    await asyncio.to_thread(_require_parent, req.acted_by, "Only parents can create chores")
    chore = await asyncio.to_thread(
        _dl.create_chore,
        zone_id=req.zone_id, dow=req.dow,
        name=req.name, note=req.note, position=req.position, by=req.acted_by,
    )
    _store._emit("chore.added", {
        "chore_id": chore["id"], "zone_id": chore["zone_id"],
        "dow": chore["dow"], "position": chore["position"], "name": chore["name"],
    })
    return chore


@router.patch("/chores/{chore_id}")
async def api_update_chore(chore_id: str, req: UpdateChoreRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    await asyncio.to_thread(_require_parent, req.acted_by, "Only parents can edit chores")
    fields = {k: v for k, v in req.model_dump().items()
              if k != "acted_by" and v is not None}
    chore = await asyncio.to_thread(_dl.update_chore, chore_id, by=req.acted_by, **fields)
    if not chore:
        raise HTTPException(status_code=404, detail="Chore not found")
    _store._emit("chore.updated", {"chore_id": chore_id, "fields": list(fields.keys())})
    return chore


@router.delete("/chores/{chore_id}")
async def api_delete_chore(chore_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent, acted_by, "Only parents can delete chores")
    ok = await asyncio.to_thread(_dl.soft_delete_chore, chore_id, by=acted_by)
    if not ok:
        raise HTTPException(status_code=404, detail="Chore not found")
    _store._emit("chore.removed", {"chore_id": chore_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Completions (check-off)
# ---------------------------------------------------------------------------

@router.post("/complete")
async def api_complete(req: CompleteChoreRequest, request: Request):
    req.acted_by = _actor(request, req.acted_by)
    actor = await asyncio.to_thread(_get_actor, req.acted_by)
    kid = await asyncio.to_thread(_dl.get_kid, req.kid_id)
    if not kid:
        raise HTTPException(status_code=404, detail="Kid not found")
    if not _can_act_on_kid(actor, kid):
        raise HTTPException(
            status_code=403,
            detail="You can only check off your own chores.",
        )
    chore_date = req.date or _store.today_local().isoformat()
    completion = await asyncio.to_thread(
        _store.complete_chore,
        chore_id=req.chore_id, kid_id=req.kid_id, chore_date=chore_date,
        completed_by=req.acted_by, note=req.note,
    )
    return completion


@router.delete("/complete/{completion_id}")
async def api_uncomplete(completion_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    actor = await asyncio.to_thread(_get_actor, acted_by)
    # We need the completion to find its kid for permission check
    removed = await asyncio.to_thread(_dl.delete_completion, completion_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Completion not found")
    kid = await asyncio.to_thread(_dl.get_kid, removed["kid_id"])
    if kid and not _can_act_on_kid(actor, kid):
        # Re-create the deleted row since the actor wasn't allowed
        await asyncio.to_thread(
            _dl.upsert_completion,
            chore_id=removed["chore_id"], kid_id=removed["kid_id"],
            chore_date=removed["chore_date"],
            completed_by=removed["completed_by"], status=removed["status"],
            note=removed["note"],
        )
        raise HTTPException(
            status_code=403,
            detail="You can only uncomplete your own chores.",
        )
    _store._emit("chore.uncompleted", {
        "completion_id": removed["id"],
        "chore_id": removed["chore_id"],
        "kid_id": removed["kid_id"],
        "date": removed["chore_date"],
    })
    return {"ok": True, "removed": removed}


@router.get("/history")
async def api_history(kid_id: str = "", date_from: str = "", date_to: str = "",
                      limit: int = 100):
    today = _store.today_local()
    df = dt.date.fromisoformat(date_from) if date_from else today - dt.timedelta(days=30)
    dt_ = dt.date.fromisoformat(date_to) if date_to else today
    rows = await asyncio.to_thread(
        _dl.list_completions_in_range,
        date_from=df.isoformat(), date_to=dt_.isoformat(),
        kid_id=kid_id or None, limit=limit,
    )
    return {"completions": rows, "count": len(rows)}
