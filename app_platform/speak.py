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
"""
import logging

logger = logging.getLogger(__name__)


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
