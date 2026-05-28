"""
Nag Registry
=============
Generic nag provider registry for app packages. App packages register
async callbacks that return nag items; the platform calls all providers
in the reminder scheduler loop and handles dedup, random timing, and
notification creation.

This module only creates notification records (delivered=False). Actual
delivery is handled by the centralized notification_delivery module.
"""

import asyncio
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE, NAG_WAKE_HOUR, NAG_SLEEP_HOUR
from notification_store import create_notification
from data_layer.db import fetch_one as _db_fetch_one

CENTRAL_TZ = ZoneInfo(TIMEZONE)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_nag_providers: dict[str, callable] = {}


def register_nag_provider(key: str, fn: callable):
    """Register an app-package nag provider.

    Args:
        key:  Unique name (e.g. "vehicle_nag")
        fn:   async Callable() -> list[dict], where each dict has:
              - recipient: str (user name)
              - message: str (formatted nag text)
              - source_type: str (for notification dedup)
              - source_id: str (for notification dedup)
    """
    _nag_providers[key] = fn
    logger.info("NAG_REGISTRY: Registered provider '%s'", key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(CENTRAL_TZ)


def _has_nag_today(recipient: str, source_type: str) -> bool:
    """Check if a nag was already created for this recipient+source_type today."""
    today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    row = _db_fetch_one(
        "SELECT 1 FROM notifications WHERE recipient = %s AND source_type = %s AND created_at >= %s LIMIT 1",
        (recipient, source_type, today_start),
    )
    return row is not None


def _nag_time_for_today(seed_key: str) -> datetime:
    """Compute a deterministic random time during waking hours for today.

    Uses hash(seed_key + date) so the time is stable throughout the day
    but varies day-to-day.
    """
    today = _now().date()
    window_start = NAG_WAKE_HOUR * 60
    window_end = NAG_SLEEP_HOUR * 60
    total_minutes = window_end - window_start

    seed = hashlib.md5(f"{seed_key}:{today.isoformat()}".encode()).hexdigest()
    random_offset = int(seed, 16) % max(total_minutes, 1)
    fire_minute = window_start + random_offset

    return datetime(
        today.year, today.month, today.day,
        fire_minute // 60, fire_minute % 60,
        tzinfo=CENTRAL_TZ,
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_all_nag_providers():
    """Call all registered nag providers and create notifications.

    For each nag item returned by a provider:
    1. Dedup — skip if already sent today for this recipient+source_type
    2. Random time gate — skip if the deterministic time hasn't arrived
    3. Determine delivery channel
    4. Create notification record (delivered=False)
    """
    if not _nag_providers:
        return

    for key, provider_fn in _nag_providers.items():
        try:
            items = await provider_fn()
            if not items:
                continue

            for item in items:
                recipient = item.get("recipient", "")
                message = item.get("message", "")
                source_type = item.get("source_type", key)
                source_id = item.get("source_id", "")

                if not recipient or not message:
                    continue

                # Dedup — one per recipient+source_type per day
                if _has_nag_today(recipient, source_type):
                    continue

                # Random time gate
                seed_key = f"{source_type}:{recipient}"
                nag_time = _nag_time_for_today(seed_key)
                if _now() < nag_time:
                    continue

                # Delivery channel
                try:
                    from tools.pushover_tool import is_pushover_user
                    channel = "both" if is_pushover_user(recipient) else "discord"
                except Exception:
                    channel = "discord"

                create_notification(
                    recipient=recipient,
                    message=message,
                    source_type=source_type,
                    source_id=source_id,
                    channel=channel,
                    delivered=False,
                )
                logger.info("NAG_REGISTRY: Created '%s' nag for %s", source_type, recipient)

        except Exception as e:
            logger.error("NAG_REGISTRY: Error running provider '%s': %s", key, e, exc_info=True)
