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
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Plan:
    """What actually happened, for the caller and the log line. The web is not
    represented as optional because it is not — it always receives."""
    web_live: bool
    discord: bool


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


def _discord_reachable(user_id: str) -> bool:
    """Can we reach this person on Discord at all — linked account, Discord enabled?

    Not "are they online there": a DM waits until it is read, and nothing in the system
    tracks Discord presence. Reachability is the question that actually decides whether
    sending is right.
    """
    try:
        from config import DISCORD_ENABLED
        if not DISCORD_ENABLED:
            return False
    except Exception:
        pass
    try:
        from data_layer.db import fetch_one
        row = fetch_one("SELECT discord_id FROM users WHERE name = %s", (user_id,))
        return bool(row and row.get("discord_id"))
    except Exception:
        # Assume reachable on error: a Discord DM that turns out to be undeliverable is
        # recoverable noise, whereas wrongly deciding someone is unreachable silently
        # drops their only off-screen route.
        logger.debug("SPEAK: discord reachability unknown for %s", user_id, exc_info=True)
        return True


def _primary_surface(user_id: str) -> str:
    """Where this person says they mainly talk to Skipper ('web' by default)."""
    try:
        from data_layer.users import get_primary_surface
        return get_primary_surface(user_id)
    except Exception:
        # Default to web: it is the surface that always works, so an unknown preference
        # can never strand someone on a third-party service we cannot verify.
        logger.debug("SPEAK: primary surface unknown for %s", user_id, exc_info=True)
        return "web"


def _discord_active(user_id: str) -> bool:
    """Has this person sent something FROM Discord recently enough that Discord is
    still a live place to answer them?

    Read off their own messages, refreshed by each one — which is the honest version of
    the question. Discord PRESENCE is untrackable, but "are they using Discord right
    now" is written plainly in the log.
    """
    from app_platform.voice_policy import DISCORD_ACTIVE_SECONDS
    try:
        from data_layer.db import fetch_one
        row = fetch_one(
            "SELECT EXTRACT(EPOCH FROM (now() - created_at)) AS age "
            "FROM consciousness_log WHERE kind='message' AND who_from=%s "
            "  AND surface='discord' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        return bool(row and row.get("age") is not None
                    and float(row["age"]) <= DISCORD_ACTIVE_SECONDS)
    except Exception:
        # Treat as inactive: this only ever ADDS a surface, and the console still has
        # the message either way, so the quiet failure is the harmless one.
        logger.debug("SPEAK: discord activity unknown for %s", user_id, exc_info=True)
        return False



def _plan_and_record(user: str, content: str, domain: str, urgent: bool,
                     log_kwargs: dict):
    """Decide the surfaces and write the record. Synchronous, so both entry points
    share ONE copy of the policy application — a second copy is how the sync and async
    paths would quietly drift apart."""
    from app_platform.consciousness import send_message
    from app_platform.voice_policy import plan_discord

    on_web = _on_web(user)

    # THE WEB ALWAYS RECEIVES. Not a decision — the log write below is unconditional,
    # and the console projects from it, so the message is there whether or not anyone
    # is watching. `on_web` only decides whether to also PUSH it onto a live screen.
    #
    # Discord is the only real choice, and it is additive: switching it on never takes
    # the web away. It is settled by what the person told us plus whether they are
    # actually using Discord right now — never by trying to detect presence we cannot
    # see.
    to_discord = plan_discord(
        primary_surface=_primary_surface(user),
        discord_active=_discord_active(user),
        discord_linked=_discord_reachable(user),
    )

    # External transport only. The web is deliberately absent from this list: the log
    # write IS its durability, and the live push is handled separately.
    channels = []
    if to_discord:
        channels.append("discord")
    # A shoulder-tap only when nobody is at a screen — buzzing someone's phone about
    # something already in front of them is noise, not urgency.
    if urgent and not on_web:
        channels += ["pushover", "mobile"]

    # "none", never "" — an EMPTY channel string is not "no surfaces", it means
    # "unset", and the delivery layer answers that with the Settings default
    # (discord+pushover). Sending "" here would quietly do the exact thing the policy
    # just decided against: mirroring a web conversation into Discord.
    row = send_message(who_to=user, content=content, domain=domain,
                       channel=(",".join(channels) if channels else "none"),
                       **log_kwargs)
    logger.info("SPEAK: %s -> web(log%s)%s", user,
                "+live" if on_web else "", " + discord" if to_discord else "")
    return row, _Plan(web_live=on_web, discord=to_discord)


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
