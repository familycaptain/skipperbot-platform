"""Generic in-process sliding-window rate limiter (per worker process).

Used to throttle brute-force-able endpoints (e.g. /auth/login). In-process is
sufficient for the single-worker home deployment; a multi-worker/clustered
deployment would back this with Redis instead.
"""

import time
from collections import deque
from threading import Lock

_WINDOWS: dict[str, deque] = {}
_LOCK = Lock()


def check_rate(key: str, max_events: int, window_seconds: int) -> int:
    """Sliding-window check.

    Returns the number of seconds to wait if ``key`` is already at its limit
    (the attempt is NOT recorded), or 0 if allowed (and records the event now).
    """
    now = time.monotonic()
    with _LOCK:
        dq = _WINDOWS.setdefault(key, deque())
        cutoff = now - window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_events:
            return max(1, int(dq[0] + window_seconds - now))
        dq.append(now)
    return 0
