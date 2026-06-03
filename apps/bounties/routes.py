"""Bounties App API Routes
==========================
FastAPI router for bounties, templates, balances, transactions, categories, config.
Mounted at /api/apps/bounties/ by the app platform loader.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import current_principal
from apps.bounties import data as _dl
from apps.bounties import store as _store
from data_layer import users as _users

router = APIRouter()


def _actor(request: Request, fallback: str) -> str:
    """The authoritative actor name.

    When auth is enforced a verified principal is present and we trust *it*,
    never the client-supplied actor field — otherwise a kid could spoof a
    parent's name to pass ``_require_parent_actor`` (or submit/claim a bounty
    as someone else). When auth is dormant (no principal) we fall back to the
    legacy body/query value so behavior is unchanged.
    """
    p = current_principal(request)
    return p["name"] if p else (fallback or "")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateBountyRequest(BaseModel):
    title: str
    value_cents: int
    created_by: str
    category: str = ""
    description: str = ""
    expires_at: Optional[str] = None


class UpdateBountyRequest(BaseModel):
    updated_by: str
    title: Optional[str] = None
    description: Optional[str] = None
    value_cents: Optional[int] = None
    category: Optional[str] = None
    expires_at: Optional[str] = None


class SubmitBountyRequest(BaseModel):
    submitted_by: str
    note: str = ""


class ReviewBountyRequest(BaseModel):
    reviewed_by: str
    note: str = ""


class CreateTemplateRequest(BaseModel):
    title: str
    value_cents: int
    created_by: str
    recurrence_days: int = 7
    category: str = ""
    description: str = ""


class UpdateTemplateRequest(BaseModel):
    updated_by: str
    title: Optional[str] = None
    description: Optional[str] = None
    value_cents: Optional[int] = None
    category: Optional[str] = None
    recurrence_days: Optional[int] = None
    is_active: Optional[bool] = None


class SkipBountyRequest(BaseModel):
    skipped_by: str


class RecordPaymentRequest(BaseModel):
    amount_cents: int
    recorded_by: str
    payment_method: str = ""
    note: str = ""


class CreateCategoryRequest(BaseModel):
    name: str
    icon: str = ""
    created_by: str


class UpdateConfigRequest(BaseModel):
    updated_by: str
    min_payout_cents: Optional[int] = None


def _require_parent_actor(user_id: str, detail: str) -> None:
    actor = _users.get_user(user_id)
    if not actor:
        raise HTTPException(status_code=400, detail=f"Unknown user: {user_id}")
    if not _users.has_any_role(actor, "parent", "admin"):
        raise HTTPException(status_code=403, detail=detail)


# ---------------------------------------------------------------------------
# Bounties
# ---------------------------------------------------------------------------

@router.get("")
async def api_list_bounties(status: str = "", category: str = ""):
    bounties = await asyncio.to_thread(_dl.get_all_bounties, status=status, category=category)
    return {"bounties": bounties, "count": len(bounties)}


@router.post("")
async def api_create_bounty(req: CreateBountyRequest, request: Request):
    req.created_by = _actor(request, req.created_by)
    await asyncio.to_thread(_require_parent_actor, req.created_by, "Only parents can create bounties")
    bounty_data = req.model_dump(exclude_none=True)
    bounty = await asyncio.to_thread(_dl.create_bounty, bounty_data)
    if not bounty:
        raise HTTPException(status_code=400, detail="Failed to create bounty")

    # Notify + emit
    await asyncio.to_thread(
        _store._notify_non_parents,
        f"🆕 New bounty: **{bounty['title']}** — ${bounty['value_cents']/100:.2f}",
        "bounty_created", bounty["id"],
    )
    await asyncio.to_thread(
        _store._emit, "bounty.created",
        {"id": bounty["id"], "title": bounty["title"],
         "value_cents": bounty["value_cents"], "created_by": bounty["created_by"]},
    )
    return bounty


@router.get("/bounty/{bounty_id}")
async def api_get_bounty(bounty_id: str):
    bounty = await asyncio.to_thread(_dl.get_bounty, bounty_id)
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    return bounty


@router.patch("/bounty/{bounty_id}")
async def api_update_bounty(bounty_id: str, req: UpdateBountyRequest, request: Request):
    req.updated_by = _actor(request, req.updated_by)
    await asyncio.to_thread(_require_parent_actor, req.updated_by, "Only parents can edit bounties")
    updates = {
        k: v for k, v in req.model_dump().items()
        if v is not None and k != "updated_by"
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    ok = await asyncio.to_thread(_dl.update_bounty, bounty_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Bounty not found or no changes")
    return await asyncio.to_thread(_dl.get_bounty, bounty_id)


@router.delete("/bounty/{bounty_id}")
async def api_delete_bounty(bounty_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent_actor, acted_by, "Only parents can delete bounties")
    ok = await asyncio.to_thread(_dl.delete_bounty, bounty_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Bounty not found")
    return {"ok": True}


@router.post("/bounty/{bounty_id}/submit")
async def api_submit_bounty(bounty_id: str, req: SubmitBountyRequest, request: Request):
    req.submitted_by = _actor(request, req.submitted_by)
    result = await asyncio.to_thread(_store.submit_bounty, bounty_id, req.submitted_by, req.note)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/bounty/{bounty_id}/approve")
async def api_approve_bounty(bounty_id: str, req: ReviewBountyRequest, request: Request):
    req.reviewed_by = _actor(request, req.reviewed_by)
    await asyncio.to_thread(_require_parent_actor, req.reviewed_by, "Only parents can approve bounties")
    result = await asyncio.to_thread(_store.approve_bounty, bounty_id, req.reviewed_by, req.note)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/bounty/{bounty_id}/reject")
async def api_reject_bounty(bounty_id: str, req: ReviewBountyRequest, request: Request):
    req.reviewed_by = _actor(request, req.reviewed_by)
    await asyncio.to_thread(_require_parent_actor, req.reviewed_by, "Only parents can reject bounties")
    result = await asyncio.to_thread(_store.reject_bounty, bounty_id, req.reviewed_by, req.note)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/bounty/{bounty_id}/skip")
async def api_skip_bounty(bounty_id: str, req: SkipBountyRequest, request: Request):
    req.skipped_by = _actor(request, req.skipped_by)
    await asyncio.to_thread(_require_parent_actor, req.skipped_by, "Only parents can skip bounties")
    result = await asyncio.to_thread(_store.skip_bounty, bounty_id, req.skipped_by)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.get("/templates")
async def api_list_templates(active_only: bool = True):
    templates = await asyncio.to_thread(_dl.get_all_templates, active_only=active_only)
    return {"templates": templates, "count": len(templates)}


@router.post("/templates")
async def api_create_template(req: CreateTemplateRequest, request: Request):
    req.created_by = _actor(request, req.created_by)
    await asyncio.to_thread(_require_parent_actor, req.created_by, "Only parents can create templates")
    result = await asyncio.to_thread(_store.create_template, req.model_dump())
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/templates/{tpl_id}")
async def api_get_template(tpl_id: str):
    tpl = await asyncio.to_thread(_dl.get_template, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.patch("/templates/{tpl_id}")
async def api_update_template(tpl_id: str, req: UpdateTemplateRequest, request: Request):
    req.updated_by = _actor(request, req.updated_by)
    await asyncio.to_thread(_require_parent_actor, req.updated_by, "Only parents can edit templates")
    updates = {
        k: v for k, v in req.model_dump().items()
        if v is not None and k != "updated_by"
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    result = await asyncio.to_thread(_store.update_template, tpl_id, updates)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/templates/{tpl_id}")
async def api_delete_template(tpl_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent_actor, acted_by, "Only parents can delete templates")
    ok = await asyncio.to_thread(_dl.delete_template, tpl_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@router.post("/templates/{tpl_id}/generate")
async def api_generate_from_template(tpl_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent_actor, acted_by, "Only parents can generate bounties from templates")
    bounty = await asyncio.to_thread(_store.generate_from_template, tpl_id)
    if not bounty:
        raise HTTPException(status_code=400, detail="Template not found or inactive")
    return bounty


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------

@router.get("/balances")
async def api_list_balances():
    balances = await asyncio.to_thread(_dl.get_all_balances)
    return {"balances": balances, "count": len(balances)}


@router.get("/balances/{user_id}")
async def api_get_balance(user_id: str):
    balance = await asyncio.to_thread(_dl.get_balance, user_id)
    recent_txns = await asyncio.to_thread(_dl.get_transactions, user_id, 20)
    return {"balance": balance, "recent_transactions": recent_txns}


@router.get("/balances/{user_id}/transactions")
async def api_get_transactions(user_id: str, limit: int = 50):
    txns = await asyncio.to_thread(_dl.get_transactions, user_id, limit)
    return {"transactions": txns, "count": len(txns)}


@router.post("/balances/{user_id}/pay")
async def api_record_payment(user_id: str, req: RecordPaymentRequest, request: Request):
    req.recorded_by = _actor(request, req.recorded_by)
    await asyncio.to_thread(_require_parent_actor, req.recorded_by, "Only parents can record payments")
    result = await asyncio.to_thread(
        _store.record_payment,
        user_id, req.amount_cents, req.payment_method, req.note, req.recorded_by,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.get("/categories")
async def api_list_categories():
    cats = await asyncio.to_thread(_dl.get_all_categories)
    return {"categories": cats}


@router.post("/categories")
async def api_create_category(req: CreateCategoryRequest, request: Request):
    req.created_by = _actor(request, req.created_by)
    await asyncio.to_thread(_require_parent_actor, req.created_by, "Only parents can create categories")
    cat = await asyncio.to_thread(_dl.create_category, req.name.strip(), req.icon.strip())
    if not cat:
        raise HTTPException(status_code=400, detail="Failed to create category (name may already exist)")
    return cat


@router.delete("/categories/{cat_id}")
async def api_delete_category(cat_id: str, request: Request, acted_by: str = ""):
    acted_by = _actor(request, acted_by)
    await asyncio.to_thread(_require_parent_actor, acted_by, "Only parents can delete categories")
    ok = await asyncio.to_thread(_dl.delete_category, cat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@router.get("/leaderboard")
async def api_leaderboard(period: str = "all"):
    leaders = await asyncio.to_thread(_dl.get_leaderboard, period)
    return {"leaderboard": leaders, "period": period}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@router.get("/config")
async def api_get_config():
    return await asyncio.to_thread(_dl.get_config)


@router.put("/config")
async def api_update_config(req: UpdateConfigRequest, request: Request):
    req.updated_by = _actor(request, req.updated_by)
    await asyncio.to_thread(_require_parent_actor, req.updated_by, "Only parents can update bounty settings")
    updates = {
        k: v for k, v in req.model_dump().items()
        if v is not None and k != "updated_by"
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    ok = await asyncio.to_thread(_dl.update_config, updates)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to update config")
    return await asyncio.to_thread(_dl.get_config)
