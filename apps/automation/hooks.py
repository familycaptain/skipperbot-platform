"""Automation App — Platform Hooks.

Spawns a background thread that keeps the Home Assistant device + entity
registry snapshot at apps/automation/devices.json fresh:
  - immediate fetch on startup (non-blocking — runs in its own thread)
  - re-fetch every REFRESH_INTERVAL_SECONDS thereafter
  - on failure, logs and falls back to the previous cached file; tries again
    on the next tick (so HA being down at boot doesn't kill the cache)
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 60 * 60  # 1 hour

# Singleton — register_hooks may be called more than once during hot-reloads;
# we only ever want one refresh thread running.
_refresh_thread: threading.Thread | None = None


def register_hooks() -> None:
    """Called by the app loader on startup."""
    global _refresh_thread
    if _refresh_thread and _refresh_thread.is_alive():
        logger.debug("AUTOMATION: device registry refresh thread already running")
        return
    _refresh_thread = threading.Thread(
        target=_refresh_loop,
        name="automation-device-registry-refresh",
        daemon=True,
    )
    _refresh_thread.start()
    logger.info("AUTOMATION: device registry refresh thread started (every %ds)",
                REFRESH_INTERVAL_SECONDS)


def _refresh_loop() -> None:
    # Defer the import so hooks.py loads even if `websockets` is missing
    # (we only blow up when we actually try to fetch).
    from apps.automation import devices as _dev
    while True:
        try:
            index = _dev.fetch_and_save()
            logger.info("AUTOMATION: device registry refreshed — %d device(s) cached",
                        len(index))
        except Exception as exc:
            logger.warning("AUTOMATION: device registry refresh failed (will retry in %dh): %s",
                           REFRESH_INTERVAL_SECONDS // 3600, exc)
        time.sleep(REFRESH_INTERVAL_SECONDS)
