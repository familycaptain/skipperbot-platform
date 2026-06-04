"""Shared rate limiter for outbound-message tools.

Prompt-injected content reaching the tool-bearing model could otherwise drive
``send_skipper_email`` / ``send_pushover_notification`` into a mass-send (spam,
or slow exfiltration of data the model can see). A per-process sliding-window
cap bounds the blast radius regardless of what the model is told to do.
(Security audit finding #17.)
"""

import time
from collections import deque
from threading import Lock

_WINDOWS: dict[str, deque] = {}
_LOCK = Lock()


def rate_limit(key: str, max_events: int, window_seconds: int) -> str | None:
    """Sliding-window limiter.

    Returns an error string if the limit for ``key`` is already reached (and does
    NOT record the attempt), else records the event now and returns None.
    """
    now = time.monotonic()
    with _LOCK:
        dq = _WINDOWS.setdefault(key, deque())
        cutoff = now - window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_events:
            retry = int(dq[0] + window_seconds - now)
            mins = max(1, window_seconds // 60)
            return (f"Error: outbound rate limit reached ({max_events} per {mins} min). "
                    f"Try again in ~{max(1, retry)}s.")
        dq.append(now)
    return None
