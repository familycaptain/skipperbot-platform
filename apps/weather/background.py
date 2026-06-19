"""Weather app — background cache-refresh loop.

Registered as a platform background task via ``apps/weather/hooks.py``
(mirroring ``apps/reminders``). Every refresh interval it pre-warms the home
location's four standard lookups through the SAME cache the tools read, so the
common reads ("weather now", "rain today", "hourly", "this week") are instant
when warm. It no-ops when caching is disabled or no home location is configured,
and never dies on a per-iteration fetch error.

The blocking work (config read + each Open-Meteo fetch) runs via
``asyncio.to_thread`` so a slow fetch never stalls the shared event loop
(voice/chat/notifications).
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Fallback sleep (seconds) if the interval can't be read for some reason.
_FALLBACK_SLEEP = 300


def _refresh_once() -> None:
    """One synchronous pre-warm pass (run via ``asyncio.to_thread``).

    No-ops unless caching is enabled AND a home location resolves with
    coordinates. Each fetch is wrapped so a failure is swallowed — the loop
    must never die on a transient network error.
    """
    from apps.weather import tools

    enabled, ttl = tools._cache_settings()
    if not enabled:
        return
    place, err = tools._resolve_place()  # home location (no override)
    if err or not place:
        return

    # Pre-warm the four standard lookups at their DEFAULT params, through the
    # SAME cache path the tools use — identical URLs, so a warmed entry serves
    # the next real tool read.
    warmers = (
        ("current", lambda: tools._fetch_current(place)),
        ("rain-forecast", lambda: tools._forecast_for_place(place)),
        ("hourly", lambda: tools._hourly_forecast_for_place(place)),
        ("daily-7d", lambda: tools._daily_forecast_for_place(place, 7)),
    )
    warmed = []
    for name, warm in warmers:
        try:
            warm()
            warmed.append(name)
        except Exception as e:  # noqa: BLE001 — never let the loop die
            logger.warning("weather pre-warm fetch %s failed: %r", name, e)
    # Observability: one INFO line per pass so the operator can confirm the
    # background loop is actually pre-warming (which lookups, which location,
    # when the next pass runs) — previously only a DEBUG line on failure, so a
    # healthy loop was invisible.
    logger.info(
        "WEATHER-REFRESH pre-warmed %s for %s; next pass in %ds",
        warmed or "nothing", place.get("label") or "home location", ttl,
    )


async def start_weather_cache_loop() -> None:
    """Async worker: pre-warm on an interval; never blocks the event loop."""
    from apps.weather import tools

    while True:
        try:
            await asyncio.to_thread(_refresh_once)
        except Exception as e:  # noqa: BLE001 — defensive; _refresh_once already swallows
            logger.debug("weather refresh pass failed: %r", e)
        # Re-read the interval each pass so a Settings change takes effect within
        # one cycle; the clamp floors the sleep so a 0/negative interval can't
        # hot-spin.
        try:
            _enabled, ttl = await asyncio.to_thread(tools._cache_settings)
        except Exception:  # noqa: BLE001
            ttl = _FALLBACK_SLEEP
        await asyncio.sleep(ttl)
