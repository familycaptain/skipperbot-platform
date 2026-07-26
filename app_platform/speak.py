"""Speak — putting Skipper's words in front of a person NOW.

NAMING: deliberately NOT `voice`. `app_platform/voice/` is the realtime AUDIO package
(the satellite relay, wake word, device announce). This is the text/chat side — one
voice in the editorial sense, across surfaces.


WHY THIS EXISTS
`consciousness.send_message` writes the log row and hands transport to the
notifications app, which delivers on the reminders tick — `CHECK_INTERVAL = 30`. That
is fine for a background nudge nobody is waiting on, and wrong for anything
conversational: Skipper finishes composing, and the person stares at a dead screen for
up to half a minute before the words appear. It also makes an honest typing indicator
impossible, because the turn is over long before the message is delivered.

So when the person is HERE, we hand it to them directly instead of leaving it in a
queue. The queue still runs and still owns the other surfaces; this is the fast path
for the one surface where somebody is actually watching.

The duplicate this could cause is already handled: the live frame carries the
consciousness-log id as `srv_id`, and the client renders one utterance once regardless
of how many times it is pushed.

THE ONE PATH
`speak()` is where everything Skipper says to a person should go. Producers decide
WHAT is worth saying; they do not decide where it lands or whether the person is
reachable. That judgement is made once, here, against the surface policy in
`voice_policy` — otherwise every new background feature reinvents it slightly
differently, which is how one utterance ends up arriving twice on one surface and not
at all on another.
"""
import logging

logger = logging.getLogger(__name__)


def _on_web(user_id: str) -> bool:
    """Is this person watching the web desktop right now?"""
    try:
        from connections import manager
        return user_id in {str(u).strip().lower() for u in manager.list_connected_users()}
    except Exception:
        # Unknown presence is treated as absent: reaching out to someone who turned out
        # to be present is recoverable, silence for someone who was never there is not.
        logger.debug("SPEAK: presence unknown for %s", user_id, exc_info=True)
        return False


def _conversation_lock(user_id: str):
    """The surface this person last SPOKE on, if recent enough to still be a
    conversation. Derived from the log, which already records every inbound message and
    the surface it arrived on — no extra state to keep in sync."""
    from app_platform.voice_policy import lock_from_last_inbound
    try:
        from data_layer.db import fetch_one
        row = fetch_one(
            "SELECT surface, EXTRACT(EPOCH FROM (now() - created_at)) AS age "
            "FROM consciousness_log WHERE kind='message' AND who_from=%s "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        if not row:
            return None
        return lock_from_last_inbound(row.get("surface"), row.get("age"))
    except Exception:
        # No lock means "reach out normally" — the safe direction. Failing the other way
        # would silently confine an utterance to a surface nobody is reading.
        logger.debug("SPEAK: lock lookup failed for %s", user_id, exc_info=True)
        return None


def _plan_and_record(user: str, content: str, domain: str, urgent: bool,
                     log_kwargs: dict):
    """Decide the surfaces and write the record. Synchronous, so both entry points
    share ONE copy of the policy application — a second copy is how the sync and async
    paths would quietly drift apart."""
    from app_platform.consciousness import send_message
    from app_platform.voice_policy import plan_surfaces

    plan = plan_surfaces(on_web=_on_web(user), lock=_conversation_lock(user),
                         urgent=urgent)

    # External transport only for the surfaces the plan chose. The web is deliberately
    # absent: the log write IS its durability, and `web_live` is the direct hand-off.
    channels = []
    if plan.discord:
        channels.append("discord")
    if plan.push:
        channels += ["pushover", "mobile"]

    # "none", never "" — an EMPTY channel string is not "no surfaces", it means
    # "unset", and the delivery layer answers that with the Settings default
    # (discord+pushover). Sending "" here would quietly do the exact thing the policy
    # just decided against: mirroring a web conversation into Discord.
    row = send_message(who_to=user, content=content, domain=domain,
                       channel=(",".join(channels) if channels else "none"),
                       **log_kwargs)
    logger.info("SPEAK: %s -> %s (%s)", user, plan.surfaces or ("log-only",), plan.reason)
    return row, plan


async def speak(*, who_to: str, content: str, domain: str, urgent: bool = False,
                **log_kwargs) -> dict:
    """Say something to a person, on whichever surfaces actually make sense.

    Returns the consciousness-log row — the record of having said it, written whether
    or not any surface turned out to be reachable.
    """
    import asyncio as _aio
    user = (who_to or "").strip().lower()
    row, plan = await _aio.to_thread(
        _plan_and_record, user, content, domain, urgent, log_kwargs)
    if plan.web_live:
        await deliver_now(user, content, srv_id=row["id"])
    return row


def speak_sync(*, who_to: str, content: str, domain: str, urgent: bool = False,
               **log_kwargs) -> dict:
    """The same thing from synchronous code (job handlers, schedulers).

    Identical policy and record. The only difference is the live web hand-off: from a
    worker thread there is no event loop to push on, so a watching person gets it from
    the delivery tick instead of instantly. That is the honest trade for not blocking —
    and it is never a LOSS, because the log already holds the message.
    """
    user = (who_to or "").strip().lower()
    row, _plan = _plan_and_record(user, content, domain, urgent, log_kwargs)
    return row


async def deliver_now(user_id: str, text: str, srv_id: str = "") -> bool:
    """Push an utterance straight onto a connected person's screen.

    Returns True if a live socket took it. False simply means they are not watching —
    the log already holds the message, so it will be there when they return, and the
    delivery queue still covers the surfaces they might come back to.
    """
    user_id = (user_id or "").strip().lower()
    if not user_id or not text:
        return False
    try:
        from datetime import datetime as _dt, timezone as _tz
        from connections import manager
        return bool(await manager.send_to_user(user_id, {
            "type": "chat_response",
            "response": text,
            "user_id": user_id,
            "ts": _dt.now(_tz.utc).isoformat(),
            "srv_id": srv_id or "",
        }))
    except Exception:
        # Never let a delivery hiccup break the turn that produced the words — they are
        # already in the log, which is the record.
        logger.debug("VOICE: live delivery to %s failed", user_id, exc_info=True)
        return False
