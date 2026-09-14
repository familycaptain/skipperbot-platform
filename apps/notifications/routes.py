"""Notifications — REST API router.

Mounted by the platform loader at ``/api/apps/notifications``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app_platform.auth import scope_user
from . import data as _data

router = APIRouter()


@router.get("")
async def list_notifications(request: Request, recipient: str = "", limit: int = 50):
    """List notifications for a recipient, newest first. Backs the history UI."""
    recipient = scope_user(request, recipient)
    notifications = await asyncio.to_thread(_data.get_notifications_for_user, recipient, limit)
    return {"notifications": notifications}


# ---------------------------------------------------------------------------
# Pushover per-user opt-in
# ---------------------------------------------------------------------------

@router.get("/pushover")
async def pushover_status(request: Request, user_id: str = ""):
    """Is Pushover set up for this user? Never returns the actual key."""
    user_id = scope_user(request, user_id)
    if not user_id.strip():
        return {"app_token_configured": False, "configured": False, "enabled": False, "device": ""}
    return await asyncio.to_thread(_data.get_pushover_status, user_id)


class PushoverIn(BaseModel):
    user_id: str
    user_key: str = ""       # blank = keep existing
    device: str = ""
    enabled: bool = True


@router.post("/pushover")
async def pushover_save(body: PushoverIn, request: Request):
    """Save a user's Pushover opt-in (user key encrypted at rest)."""
    body.user_id = scope_user(request, body.user_id)
    if not body.user_id.strip():
        return {"ok": False, "error": "user_id is required"}
    await asyncio.to_thread(
        _data.save_pushover_subscription, body.user_id, body.user_key, body.device, body.enabled,
    )
    status = await asyncio.to_thread(_data.get_pushover_status, body.user_id)
    return {"ok": True, **status}


@router.delete("/pushover")
async def pushover_delete(request: Request, user_id: str = ""):
    """Remove a user's Pushover opt-in entirely."""
    user_id = scope_user(request, user_id)
    if not user_id.strip():
        return {"ok": False, "error": "user_id is required"}
    await asyncio.to_thread(_data.delete_pushover_subscription, user_id)
    return {"ok": True}


@router.post("/pushover/test")
async def pushover_test(body: PushoverIn, request: Request):
    """Send a test Pushover notification to confirm setup."""
    body.user_id = scope_user(request, body.user_id)
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


# ---------------------------------------------------------------------------
# Direct send — the route that makes Skipper actually tell somebody something
# ---------------------------------------------------------------------------
#
# Everything else in the platform raises a notification by importing
# `app_platform.notifications.create_notification`, which only a process running ON
# the box can do. A caretaker watching from somewhere else — another machine, a
# monitor loop, a cron on a different host — had no way in at all: this router could
# LIST notifications and configure Pushover, and could not send one.
#
# It is written to fail loudly, because the thing it is for is the escalation of last
# resort. Two habits of the surrounding code would otherwise swallow a failure whole:
#
#   * create_notification() returns {} for a name that belongs to nobody, logging at
#     debug. Called blind, an alert addressed to a typo is indistinguishable from one
#     that was delivered.
#   * _deliver_one() marks a row delivered once it has TRIED, whatever came back. The
#     row is a record that we attempted, never evidence that anyone was reached.
#
# So: recipients are checked before anything is written, the whole request is refused
# if any of them is unreachable, and the response reports the delivery receipts per
# surface per person. The status code agrees with the body — a caller that checks
# only `resp.ok` still cannot mistake an undelivered alert for a delivered one.

MAX_RECIPIENTS = 20
MAX_MESSAGE_CHARS = 4000


class SendIn(BaseModel):
    recipients: list[str] = []
    recipient: str = ""           # singular convenience; merged with `recipients`
    message: str = ""
    source_type: str = "system"
    source_id: str = ""
    channel: str = "discord"
    deliver: bool = True


def _requested_recipients(body: SendIn) -> list[str]:
    """The recipient list, normalised the way user names are stored, order kept."""
    out: list[str] = []
    for raw in [*(body.recipients or []), body.recipient]:
        name = str(raw or "").lower().strip()
        if name and name not in out:
            out.append(name)
    return out


def _unreachable(names: list[str], targets: set) -> list[str]:
    """Why each name cannot be reached — empty list means every one of them can.

    Checked UP FRONT, for all of them, before a single row is written. A partial send
    that 200s with a list of who missed out reads as success to anything that tests
    the status code, and this is the path that matters most when it is read wrong.
    """
    from data_layer.users import get_user

    problems = []
    for name in names:
        user = get_user(name)
        if not user:
            problems.append(f"{name!r} is not a known user")
        elif "discord" in targets and not (user.get("discord_id") or "").strip():
            problems.append(f"{name!r} has no discord_id — Discord cannot reach them")
    return problems


@router.post("")
async def send_notification(body: SendIn, request: Request):
    """Record a notification for each recipient and (by default) deliver it now.

    Requires an admin principal: sending as Skipper to any member of the household is
    not something a member's own credential should be able to do. Off-box callers use
    a service token minted with `--role admin` (scripts/service_token.py).
    """
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse

    from app_platform.auth import require_admin
    from .delivery import _deliver_one, _resolve_external_channels
    from .store import create_notification

    require_admin(request)

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"message is longer than {MAX_MESSAGE_CHARS} characters")

    recipients = _requested_recipients(body)
    if not recipients:
        raise HTTPException(400, "at least one recipient is required")
    if len(recipients) > MAX_RECIPIENTS:
        raise HTTPException(400, f"no more than {MAX_RECIPIENTS} recipients per request")

    channel = (body.channel or "discord").strip()
    targets = _resolve_external_channels(channel)

    problems = await asyncio.to_thread(_unreachable, recipients, targets)
    if problems:
        # 4xx, naming names, nothing written. The caller can fix the list and retry;
        # what it must never do is walk away believing the alert went out.
        raise HTTPException(400, "Cannot send: " + "; ".join(problems))

    results = []
    for name in recipients:
        notif = await asyncio.to_thread(
            create_notification,
            name, message, body.source_type or "system", body.source_id or "",
            channel, False,
        )
        if not notif:
            # Pre-flight said this name was fine, so getting here means it stopped
            # being fine in between. Report it rather than drop it.
            results.append({"recipient": name, "notification_id": None,
                            "delivered": False, "receipts": {},
                            "error": "the record could not be created"})
            continue

        if not body.deliver:
            results.append({"recipient": name, "notification_id": notif["id"],
                            "delivered": False, "receipts": {},
                            "error": None, "note": "recorded only (deliver=false)"})
            continue

        try:
            # honor_surface_policy=False: this caller named the surface, and is not
            # mirroring a conversation. See the comment at that check in delivery.py.
            receipts = await _deliver_one(notif, honor_surface_policy=False) or {}
        except Exception as exc:                       # noqa: BLE001 — reported, not raised
            results.append({"recipient": name, "notification_id": notif["id"],
                            "delivered": False, "receipts": {},
                            "error": f"delivery raised: {exc}"})
            continue

        # Delivered means a surface the CALLER ASKED FOR reported success. The web
        # console is always written to and would otherwise make every send look fine.
        reached = sorted(t for t in targets if receipts.get(t, {}).get("ok"))
        missed = sorted(t for t in targets if not receipts.get(t, {}).get("ok"))
        results.append({
            "recipient": name,
            "notification_id": notif["id"],
            "delivered": bool(reached),
            "channels_reached": reached,
            "receipts": receipts,
            "error": None if reached else
                     ("; ".join(f"{t}: {receipts.get(t, {}).get('detail') or 'not attempted'}"
                                for t in missed) or "no channel was attempted"),
        })

    ok = all(r["delivered"] for r in results) if body.deliver else all(
        r["notification_id"] for r in results)
    # The status code has to agree with the body. A caller that only checks resp.ok
    # is the one this endpoint exists to protect.
    return JSONResponse(
        status_code=200 if ok else 502,
        content={"ok": ok, "requested": len(recipients), "channel": channel,
                 "delivered_via": sorted(targets), "results": results},
    )
