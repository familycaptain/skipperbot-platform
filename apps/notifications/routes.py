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
#   * Naming ONE channel strips the others out of the target set, so a recipient whose
#     Discord copy is declined by the delivery policy has no push route left. That is
#     the caller removing its own fallback, not delivery dropping the message — and
#     from outside the two are indistinguishable. Hence the blank default.
#
# So: recipients are checked before anything is written, nobody unreachable gets a
# record claiming they were told something, and the response reports the delivery
# receipts per surface per person — the caller is expected to read them.
#
# It sends to everyone it CAN reach and names who it could not, rather than refusing
# the whole request over one bad name. The failure that bites an escalation path is
# drift, not a typo: a discord_id quietly unset months later, on a route nothing
# exercises until the emergency. One stale link must not silence the alert to the
# other two people, one of whom may be the only person who can act.
#
# The status code cannot say all of that, so the body is authoritative — but it is
# kept honest, because the one thing a careless caller must never see is a 200 over
# an alert that did not reach somebody.

MAX_RECIPIENTS = 20
MAX_MESSAGE_CHARS = 4000


class SendIn(BaseModel):
    recipients: list[str] = []
    recipient: str = ""           # singular convenience; merged with `recipients`
    message: str = ""
    source_type: str = "system"
    source_id: str = ""
    channel: str = ""             # blank = the platform's default_channels
    deliver: bool = True
    dry_run: bool = False         # report what WOULD happen; send nothing


def _requested_recipients(body: SendIn) -> list[str]:
    """The recipient list, normalised the way user names are stored, order kept."""
    out: list[str] = []
    for raw in [*(body.recipients or []), body.recipient]:
        name = str(raw or "").lower().strip()
        if name and name not in out:
            out.append(name)
    return out


def _dead_routes(user: dict, name: str, targets: set) -> dict:
    """target -> why it DEFINITELY cannot reach this person. Absent means it may work.

    Only positive knowledge belongs in here. Anything we cannot determine is left out,
    so an unanswerable question never becomes a reason to withhold a message.
    """
    dead = {}
    if "discord" in targets and not (user.get("discord_id") or "").strip():
        dead["discord"] = "no discord_id"
    if "pushover" in targets:
        try:
            from tools.pushover_tool import is_pushover_user
            if not is_pushover_user(name):
                dead["pushover"] = "Pushover not configured"
        except Exception:                      # noqa: BLE001 — unknown is not "dead"
            pass
    # mobile is deliberately absent: registered devices are not cheaply knowable here,
    # and guessing wrong would withhold a message over a route that might have worked.
    return dead


def _surface_states(name: str, user: dict, targets: set) -> dict:
    """What WOULD happen on each requested surface, without touching any of them.

    Three answers only, and the third is the important one:

      ready           — configured, and the delivery policy would send it
      declined        — configured, but the policy would not send it to this person
      not_configured  — there is positively no route here
      unknown         — we could not find out

    UNKNOWN IS NEVER READY. A rehearsal that assumes a surface works because it could
    not check is worth less than no rehearsal, because it is counted. Everything here
    is therefore conservative in the same direction: only positive evidence that a
    surface would carry the message earns "ready".
    """
    states = {}

    if "discord" in targets:
        if not (user.get("discord_id") or "").strip():
            states["discord"] = {"state": "not_configured", "detail": "no discord_id"}
        else:
            try:
                from app_platform.speak import (_discord_active, _discord_reachable,
                                                 _primary_surface)
                from app_platform.voice_policy import plan_discord
                would = plan_discord(primary_surface=_primary_surface(name),
                                     discord_active=_discord_active(name),
                                     discord_linked=_discord_reachable(name))
                states["discord"] = ({"state": "ready", "detail": "linked, policy would send"}
                                     if would else
                                     {"state": "declined",
                                      "detail": "linked, but they talk on the web and have not "
                                                "used Discord recently"})
            except Exception as exc:                   # noqa: BLE001
                states["discord"] = {"state": "unknown", "detail": f"could not evaluate: {exc}"}

    if "pushover" in targets:
        try:
            from tools.pushover_tool import is_pushover_user
            states["pushover"] = ({"state": "ready", "detail": "configured"}
                                  if is_pushover_user(name) else
                                  {"state": "not_configured",
                                   "detail": "no Pushover user key saved"})
        except Exception as exc:                       # noqa: BLE001
            states["pushover"] = {"state": "unknown", "detail": f"could not evaluate: {exc}"}

    if "mobile" in targets:
        try:
            from fcm_sender import is_enabled as fcm_enabled
            states["mobile"] = ({"state": "unknown",
                                 "detail": "push is set up; registered devices not checked here"}
                                if fcm_enabled() else
                                {"state": "not_configured", "detail": "mobile push not set up"})
        except Exception as exc:                       # noqa: BLE001
            states["mobile"] = {"state": "unknown", "detail": f"could not evaluate: {exc}"}

    return states


def _rehearse(names: list[str], targets: set) -> list:
    """One result per recipient describing what a real send WOULD do. Sends nothing.

    Exists so the household can check that the people this endpoint exists to reach
    are still reachable, WITHOUT messaging them to find out. A check that costs three
    people a pointless notification gets run less often, and a readiness gate does not
    usually fail — it rots, by becoming expensive enough to skip.
    """
    from data_layer.users import get_user

    out = []
    for name in names:
        user = get_user(name)
        if not user:
            out.append({"recipient": name, "notification_id": None, "delivered": False,
                        "dry_run": True, "would_reach": [], "surfaces": {},
                        "error": "not a known user"})
            continue

        states = _surface_states(name, user, targets)
        ready = sorted(t for t, v in states.items() if v["state"] == "ready")
        unknown = sorted(t for t, v in states.items() if v["state"] == "unknown")

        if ready:
            error = None
        elif unknown:
            # NOT the same as having no route, and must not be reported as if it were.
            error = ("no surface could be confirmed; " +
                     "; ".join(f"{t}: {states[t]['detail']}" for t in sorted(states)))
        else:
            error = "; ".join(f"{t}: {states[t]['detail']}" for t in sorted(states)) or \
                    "no channel was requested"

        out.append({"recipient": name, "notification_id": None,
                    # ALWAYS false. Nothing was delivered, and no arrangement of this
                    # response may suggest otherwise.
                    "delivered": False,
                    "dry_run": True,
                    "would_reach": ready,
                    "surfaces": states,
                    "error": error})
    return out


def _unreachable(names: list[str], targets: set) -> dict:
    """Map each name that CANNOT be reached to the reason why. Reachable names absent.

    Checked up front, for everyone, before a single row is written — a name that has
    no route to a person must not get a record claiming it was told something.

    Unreachable means EVERY requested channel is known to be dead for them, not that
    one of them is. This distinction was a bug once: the check asked only whether they
    had a discord_id, which was the whole story while this route pinned itself to
    Discord, and became wrong the moment it stopped. A recipient with Pushover set up
    but no Discord link was reported unreachable and never contacted, over a route
    that would have buzzed their phone. Withholding a message because ONE of several
    surfaces is dead is precisely the failure this endpoint exists to avoid.

    What it does NOT do is stop the send to anybody else. The failure that bites here
    is not a typo in a hardcoded list, which fails loudly on its first smoke test; it
    is DRIFT — a discord_id that quietly becomes unset months later, on a path nothing
    exercises until the emergency. Letting one stale link silence the alert to the
    other two people, one of whom may be the only person who can act, would be a far
    worse failure than an incomplete send that says exactly who it missed.
    """
    from data_layer.users import get_user

    problems = {}
    for name in names:
        user = get_user(name)
        if not user:
            problems[name] = "not a known user"
            continue
        if not targets:
            continue                    # no external delivery asked for; record only
        dead = _dead_routes(user, name, targets)
        if set(dead) >= targets:
            problems[name] = "; ".join(f"{t}: {dead[t]}" for t in sorted(targets))
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

    # Blank on purpose. Naming a single channel STRIPS the others out of the target
    # set — asking for "discord" alone means a recipient whose Discord copy is declined
    # has no push route left, which is how a caller talks itself into believing the
    # delivery policy dropped the message when it was the caller that removed the
    # alternative. Blank takes Settings -> default_channels ("discord,pushover"), so a
    # phone is still reached whatever Discord decides. A caretaker who wants every
    # route asks for "all".
    channel = (body.channel or "").strip()
    targets = _resolve_external_channels(channel)

    if body.dry_run:
        results = await asyncio.to_thread(_rehearse, recipients, targets)
        ready = [r for r in results if r["would_reach"]]
        unready = [r for r in results if not r["would_reach"]]
        # NOTE THE ABSENT `ok`. A rehearsal must not be mistakable for a delivery, and
        # the likeliest way that happens is a caller reading the field it always reads.
        # Its absence makes `body.get("ok")` falsy here, so a check written for a real
        # send treats a dry run as a failure — the safe direction. The rehearsal's own
        # verdict is `ready`, which a caller has to have asked for to find.
        return JSONResponse(
            status_code=200 if not unready else (207 if ready else 502),
            content={"dry_run": True,
                     "ready": not unready,
                     "requested": len(recipients),
                     "reachable": len(ready),
                     "unreachable": len(unready),
                     "channel": channel,
                     "delivered_via": sorted(targets),
                     "results": results},
        )

    problems = await asyncio.to_thread(_unreachable, recipients, targets)

    results = []
    for name in recipients:
        if name in problems:
            # No row: a record addressed to somebody we have no route to would be a
            # claim that they were told something. Reported per-recipient instead, so
            # the people we CAN reach still get the message.
            results.append({"recipient": name, "notification_id": None,
                            "delivered": False, "channels_reached": [], "receipts": {},
                            "error": problems[name]})
            continue

        notif = await asyncio.to_thread(
            create_notification,
            name, message, body.source_type or "system", body.source_id or "",
            channel, False,
        )
        if not notif:
            # Pre-flight said this name was fine, so getting here means it stopped
            # being fine in between. Report it rather than drop it.
            results.append({"recipient": name, "notification_id": None,
                            "delivered": False, "channels_reached": [], "receipts": {},
                            "error": "the record could not be created"})
            continue

        if not body.deliver:
            results.append({"recipient": name, "notification_id": notif["id"],
                            "delivered": False, "channels_reached": [], "receipts": {},
                            "error": None, "note": "recorded only (deliver=false)"})
            continue

        try:
            receipts = await _deliver_one(notif) or {}
        except Exception as exc:                       # noqa: BLE001 — reported, not raised
            results.append({"recipient": name, "notification_id": notif["id"],
                            "delivered": False, "channels_reached": [], "receipts": {},
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

    # "Succeeded" is per-person, and every person was asked for. deliver=false is a
    # different job, so it is judged on whether the record was written.
    def _ok(r):
        return bool(r["notification_id"]) if not body.deliver else r["delivered"]

    succeeded = [r for r in results if _ok(r)]
    failed = [r for r in results if not _ok(r)]

    # THE STATUS CODE IS NOT THE ANSWER — the per-recipient results are, and a caller
    # must read them. It is kept honest anyway, because the one thing a careless
    # caller must never see is a 200 over an alert that did not reach somebody:
    #   200  every requested recipient was reached
    #   207  some were, some were not — partial, and the body says who
    #   502  nobody was reached at all
    # Note 207 is "successful" to most HTTP clients (requests' resp.ok is True), which
    # is exactly why `ok` in the body is the authoritative field.
    if not failed:
        status = 200
    elif succeeded:
        status = 207
    else:
        status = 502

    return JSONResponse(
        status_code=status,
        content={"ok": not failed,
                 "requested": len(recipients),
                 "succeeded": len(succeeded),
                 "failed": len(failed),
                 "channel": channel,
                 "delivered_via": sorted(targets),
                 "results": results},
    )
