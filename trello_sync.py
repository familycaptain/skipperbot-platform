"""Trello Sync Scheduler
======================
Background async loop that polls Trello-linked lists and updates local cache.
Trello is the source of truth for linked lists.

Also runs Task ↔ Card sync for projects linked to Trello boards.
"""

import asyncio
import time
from config import logger
from apps.lists.store import sync_all_trello_lists


def _sync_interval() -> int:
    """Poll interval (seconds), from the Lists app settings. Default 5 minutes."""
    try:
        from app_platform import settings as _settings
        val = _settings.get("trello_sync_interval_seconds", scope="app:lists", default=300)
        return int(val)
    except Exception:
        return 300


# Resolved once at import; restart to apply a change.
SYNC_INTERVAL = _sync_interval()


async def sync_cycle():
    """Run one sync cycle for all Trello-linked lists and project tasks."""
    # --- List sync (shopping, chores, etc.) ---
    try:
        t0 = time.monotonic()
        result = await asyncio.to_thread(sync_all_trello_lists)
        elapsed = time.monotonic() - t0
        if "No Trello-linked lists" not in result:
            logger.info("TRELLO_SYNC: lists %.1fs | %s", elapsed, result.replace("\n", " | "))
    except Exception as e:
        logger.error("TRELLO_SYNC: List sync error: %s", str(e))

    # --- Task sync (project-linked boards) ---
    try:
        from trello_task_sync import sync_all_project_tasks
        t0 = time.monotonic()
        result = await asyncio.to_thread(sync_all_project_tasks)
        elapsed = time.monotonic() - t0
        if result:
            logger.info("TRELLO_SYNC: tasks %.1fs | %s", elapsed, result)
    except Exception as e:
        logger.error("TRELLO_SYNC: Task sync error: %s", str(e))


async def start_trello_sync():
    """Run the Trello sync loop forever. Start as an asyncio task."""
    logger.info("TRELLO_SYNC: Scheduler started (polling every %ds)", SYNC_INTERVAL)
    while True:
        await sync_cycle()
        await asyncio.sleep(SYNC_INTERVAL)
