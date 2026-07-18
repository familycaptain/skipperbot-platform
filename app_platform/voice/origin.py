"""Request-origin context for voice.

Lets a tool discover it was invoked from a VOICE session (and on which device),
so a producer can route its side effects back to voice — e.g. a timer created by
voice announces itself by voice when it fires, instead of only hitting the push
channels. The voice tool runtime sets this around each tool call (tools run
in-process, so the contextvar is visible to the tool and to any task it spawns at
create time). Off the voice path (chat, UI, background jobs) it's None.
"""
from __future__ import annotations

import contextvars

_voice_origin: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "voice_origin", default=None)


def set_voice_origin(device_id: str = "", room: str = ""):
    """Mark the current context as originating from a voice session. Returns a token
    to pass to reset_voice_origin()."""
    return _voice_origin.set({"device_id": device_id or "", "room": room or ""})


def reset_voice_origin(token) -> None:
    try:
        _voice_origin.reset(token)
    except Exception:
        pass


def get_voice_origin() -> dict | None:
    """The voice origin ({device_id, room}) for the current context, or None if this
    isn't a voice-initiated call."""
    return _voice_origin.get()
