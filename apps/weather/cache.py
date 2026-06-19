"""In-process freshness cache for the weather tools.

All four Open-Meteo live fetches route through :func:`cached_fetch`, keyed by
the request URL — which already embeds the resolved lat/lon and that lookup's
parameters, so each distinct lookup / location / param-variant caches
INDEPENDENTLY and never collides. A background task (``apps/weather/background.py``)
pre-warms the home location through the same path, so common reads stay instant.

In-memory only (a module-level dict guarded by a Lock) — no DB, no migrations.
A process restart simply re-warms within one refresh interval.
"""

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# url -> (timestamp_seconds, value)
_ENTRIES: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()

# Injectable time source (overridden in tests via monkeypatch). Monotonic so a
# wall-clock jump can't make a fresh entry look stale or vice-versa.
_now = time.monotonic

# Floor (seconds) so a 0 / negative / misconfigured interval can neither disable
# freshness-serving nor hot-spin the background loop.
_MIN_TTL_SECONDS = 30


def effective_ttl(refresh_interval_minutes) -> int:
    """Clamp the configured interval to a sane floor, returned in seconds.

    Used for BOTH the freshness window and the background loop sleep, so a
    misconfigured interval (<=0 or non-numeric) falls back to ``_MIN_TTL_SECONDS``.
    """
    try:
        secs = int(refresh_interval_minutes) * 60
    except (TypeError, ValueError):
        secs = 0
    return max(secs, _MIN_TTL_SECONDS)


def cached_fetch(
    url: str,
    fetcher: Callable[[], Any],
    ttl_seconds: float,
    enabled: bool,
    label: str = "",
) -> Any:
    """Serve-if-fresh, else fetch live; degrade to stale on failure.

    - ``enabled=False`` bypasses the cache entirely (always live; no read, no
      write) — today's behavior.
    - Fresh hit (age < ``ttl_seconds``) returns the cached value with NO network
      call.
    - Miss / stale fetches live, stores ``(now, value)``, and returns it.
    - On a live-fetch exception with a value already stored, returns that last
      value (stale-but-useful — "stale beats nothing").
    - On a COLD miss (fetch raises, nothing stored) RE-RAISES the original
      exception (never returns ``None``) so the tool emits its existing error
      string unchanged.

    OBSERVABILITY: emits a plain INFO log line at each decision point so the
    operator can confirm caching live (a fresh hit, a miss → live fetch) and a
    WARNING when a stale value is served because a live fetch failed. ``label``
    is the human-readable lookup name shown in those lines (falls back to the
    URL); it has no effect on cache identity (the URL remains the key).
    """
    if not enabled:
        return fetcher()

    what = label or url
    now = _now()
    with _LOCK:
        entry = _ENTRIES.get(url)
    if entry is not None and (now - entry[0]) < ttl_seconds:
        logger.info("WEATHER-CACHE hit %s age %.0fs", what, now - entry[0])
        return entry[1]  # fresh hit

    # Miss or stale — fetch live OUTSIDE the lock (network I/O must not block
    # other readers/writers).
    logger.info("WEATHER-CACHE miss %s -> live fetch", what)
    try:
        value = fetcher()
    except Exception as exc:
        if entry is not None:
            # graceful degradation: serve the last stored value
            logger.warning(
                "WEATHER-CACHE stale-serve %s (live fetch failed: %r)", what, exc
            )
            return entry[1]
        raise  # cold miss -> propagate so the tool's try/except handles it
    with _LOCK:
        _ENTRIES[url] = (now, value)
    return value


def clear() -> None:
    """Drop all cached entries (test helper / manual reset)."""
    with _LOCK:
        _ENTRIES.clear()
