"""Newsletter App — FastAPI routes.

Mounted at /api/apps/newsletter/ by the app platform loader.
"""

import asyncio
import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.newsletter import data as _dl

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Editions
# ---------------------------------------------------------------------------

@router.get("/editions")
async def api_list_editions(limit: int = 30):
    editions = await asyncio.to_thread(_dl.list_editions, limit)
    return {"editions": editions, "count": len(editions)}


@router.get("/editions/{edition_id}")
async def api_get_edition(edition_id: str):
    edition = await asyncio.to_thread(_dl.get_edition, edition_id)
    if not edition:
        raise HTTPException(404, "Edition not found")
    return edition


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@router.get("/config")
async def api_get_config():
    cfg = await asyncio.to_thread(_dl.get_config)
    return cfg or {}


class ConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    delivery_time_et: str | None = None
    from_address: str | None = None
    from_name: str | None = None
    product_name: str | None = None
    product_tagline: str | None = None
    disclosure_short: str | None = None
    disclosure_long: str | None = None
    primary_signal_label: str | None = None
    outlook_label: str | None = None
    chart_output_dir: str | None = None
    performance_lookback_days: int | None = None
    performance_tickers: list[str] | None = None
    test_email: str | None = None


@router.put("/config")
async def api_update_config(body: ConfigUpdateRequest):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await asyncio.to_thread(_dl.update_config, **updates)
    cfg = await asyncio.to_thread(_dl.get_config)
    return cfg or {}


# ---------------------------------------------------------------------------
# Run / Test-Run
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    edition_date: str | None = None
    created_by: str = "ui"


@router.post("/run")
async def api_run_newsletter(body: RunRequest):
    """Submit a newsletter_generate job (full run → all active subscribers)."""
    from apps.jobs.dispatcher import submit_job
    target_date = body.edition_date or str(date.today())
    job = submit_job(
        job_type="newsletter_generate",
        name=f"Newsletter Generate — {target_date}",
        config={"date": target_date},
        created_by=body.created_by,
        notify_user=body.created_by,
    )
    logger.info("NEWSLETTER API: Run triggered by %s for %s, job_id=%s",
                body.created_by, target_date, job["id"])
    return {"ok": True, "job_id": job["id"], "edition_date": target_date}


@router.post("/run-test")
async def api_run_newsletter_test(body: RunRequest):
    """Submit a newsletter_generate job in test mode (sends only to test_email)."""
    cfg = await asyncio.to_thread(_dl.get_config)
    test_email = ((cfg or {}).get("test_email") or "").strip()
    if not test_email:
        raise HTTPException(400, "No test_email configured — set it in the Config tab first")

    from apps.jobs.dispatcher import submit_job
    target_date = body.edition_date or str(date.today())
    job = submit_job(
        job_type="newsletter_generate",
        name=f"Newsletter Generate TEST — {target_date}",
        config={"date": target_date, "test_email": test_email},
        created_by=body.created_by,
        notify_user=body.created_by,
    )
    logger.info("NEWSLETTER API: TEST run triggered by %s for %s → %s, job_id=%s",
                body.created_by, target_date, test_email, job["id"])
    return {"ok": True, "job_id": job["id"], "edition_date": target_date, "test_email": test_email}


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------

@router.get("/subscribers")
async def api_list_subscribers(include_inactive: bool = True):
    subs = await asyncio.to_thread(_dl.list_subscribers, include_inactive)
    return {"subscribers": subs, "count": len(subs)}


class AddSubscriberRequest(BaseModel):
    email: str
    name: str = ""
    level: str = "free"
    notes: str = ""


@router.post("/subscribers")
async def api_add_subscriber(body: AddSubscriberRequest):
    if not body.email.strip():
        raise HTTPException(400, "email is required")
    if body.level not in ("free", "paid"):
        raise HTTPException(400, "level must be 'free' or 'paid'")
    sub = await asyncio.to_thread(
        _dl.add_subscriber, body.email, body.name, body.level, body.notes
    )
    return sub


class UpdateSubscriberRequest(BaseModel):
    name: str | None = None
    level: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.patch("/subscribers/{sub_id}")
async def api_update_subscriber(sub_id: str, body: UpdateSubscriberRequest):
    existing = await asyncio.to_thread(_dl.get_subscriber, sub_id)
    if not existing:
        raise HTTPException(404, "Subscriber not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await asyncio.to_thread(_dl.update_subscriber, sub_id, **updates)
    return await asyncio.to_thread(_dl.get_subscriber, sub_id)


@router.delete("/subscribers/{sub_id}")
async def api_delete_subscriber(sub_id: str):
    existing = await asyncio.to_thread(_dl.get_subscriber, sub_id)
    if not existing:
        raise HTTPException(404, "Subscriber not found")
    await asyncio.to_thread(_dl.delete_subscriber, sub_id)
    return {"ok": True}
