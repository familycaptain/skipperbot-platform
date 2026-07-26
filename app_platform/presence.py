"""Presence — telling a person that Skipper is composing something for them.

Why this is server-side (specs/CONSCIOUSNESS.md §15): the typing indicator must mean
"a turn is running that may speak to you". The web client used to SIMULATE it — arm a
2s timer on arrival, show dots, and fail open after 15s — which is a guess about server
behaviour, so it is wrong in both directions: dots appear when nothing is being composed,
and a message can land with no dots at all when the turn starts before the timer is armed.

Presence is cosmetic, so every call here FAILS OPEN: a transport hiccup must never take
down the turn that was trying to speak.
"""
import logging

logger = logging.getLogger(__name__)


async def set_typing(user_id: str, on: bool) -> None:
    """Show/hide the composing indicator for `user_id` on the web surface.

    Safe to call when the person is not connected — the manager simply finds no
    socket and it is a no-op.
    """
    user_id = (user_id or "").strip().lower()
    if not user_id:
        return
    try:
        from connections import manager
        await manager.send_to_user(user_id, {"type": "typing", "status": bool(on)})
    except Exception:
        logger.debug("PRESENCE: typing=%s for %s not delivered", on, user_id, exc_info=True)
