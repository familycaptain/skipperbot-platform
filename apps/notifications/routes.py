"""Notifications — REST API router.

Mounted by the platform loader at ``/api/apps/notifications``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from . import data as _data

router = APIRouter()


@router.get("")
async def list_notifications(recipient: str = "", limit: int = 50):
    """List notifications for a recipient, newest first. Backs the history UI."""
    notifications = await asyncio.to_thread(_data.get_notifications_for_user, recipient, limit)
    return {"notifications": notifications}


# ---------------------------------------------------------------------------
# Pushover per-user opt-in
# ---------------------------------------------------------------------------

@router.get("/pushover")
async def pushover_status(user_id: str = ""):
    """Is Pushover set up for this user? Never returns the actual key."""
    if not user_id.strip():
        return {"app_token_configured": False, "configured": False, "enabled": False, "device": ""}
    return await asyncio.to_thread(_data.get_pushover_status, user_id)


class PushoverIn(BaseModel):
    user_id: str
    user_key: str = ""       # blank = keep existing
    device: str = ""
    enabled: bool = True


@router.post("/pushover")
async def pushover_save(body: PushoverIn):
    """Save a user's Pushover opt-in (user key encrypted at rest)."""
    if not body.user_id.strip():
        return {"ok": False, "error": "user_id is required"}
    await asyncio.to_thread(
        _data.save_pushover_subscription, body.user_id, body.user_key, body.device, body.enabled,
    )
    status = await asyncio.to_thread(_data.get_pushover_status, body.user_id)
    return {"ok": True, **status}


@router.delete("/pushover")
async def pushover_delete(user_id: str = ""):
    """Remove a user's Pushover opt-in entirely."""
    if not user_id.strip():
        return {"ok": False, "error": "user_id is required"}
    await asyncio.to_thread(_data.delete_pushover_subscription, user_id)
    return {"ok": True}


@router.post("/pushover/test")
async def pushover_test(body: PushoverIn):
    """Send a test Pushover notification to confirm setup."""
    if not body.user_id.strip():
        return {"ok": False, "error": "user_id is required"}

    def _send():
        from tools.pushover_tool import is_pushover_user, send_pushover_notification
        if not is_pushover_user(body.user_id):
            return {"ok": False, "error": "Not configured — save your user key (and ask your admin to set the app token) first."}
        result = send_pushover_notification(body.user_id, "✅ Skipper Pushover test — you're all set!", cooldown_seconds=0)
        ok = result.lower().startswith("sent")
        return {"ok": ok, "message": result}

    return await asyncio.to_thread(_send)
