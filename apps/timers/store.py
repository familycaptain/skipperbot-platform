"""Timers — in-memory registry of active timers.

Timers are short-lived (seconds to minutes), so they live only in process
memory — they evaporate on restart. The notification that fires when a timer
expires is the persisted artifact.

State is mutated only from the asyncio event loop (timer tasks and async tool
functions), so no locking is required.
"""

import uuid
from datetime import datetime
from typing import Optional

from app_platform.time import get_timezone

# Active timers, keyed by "tm-xxxxxxxx" id. Each value:
#   {
#     "id": str,
#     "user_id": str,
#     "name": str,
#     "duration_seconds": int,
#     "started_at": ISO str,
#     "expires_at": ISO str,
#     "task": asyncio.Task,
#   }
_TIMERS: dict[str, dict] = {}


def new_timer_id() -> str:
    return f"tm-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(get_timezone())


def register(timer_id: str, user_id: str, name: str, duration_seconds: int, task) -> dict:
    """Add a timer record. The task is the asyncio.Task running the sleep+fire."""
    from datetime import timedelta
    now = _now()
    record = {
        "id": timer_id,
        "user_id": user_id,
        "name": name,
        "duration_seconds": duration_seconds,
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=duration_seconds)).isoformat(),
        "task": task,
    }
    _TIMERS[timer_id] = record
    return record


def get(timer_id: str) -> Optional[dict]:
    return _TIMERS.get(timer_id)


def pop(timer_id: str) -> Optional[dict]:
    return _TIMERS.pop(timer_id, None)


def list_active(user_id: Optional[str] = None) -> list[dict]:
    """Return active timer records, optionally filtered by user."""
    if user_id:
        clean = user_id.lower().strip()
        return [t for t in _TIMERS.values() if t["user_id"] == clean]
    return list(_TIMERS.values())


def all_records() -> list[dict]:
    return list(_TIMERS.values())


def clear():
    _TIMERS.clear()


def seconds_remaining(record: dict) -> float:
    """Seconds left until expiry. Negative means already past expiry."""
    expires = datetime.fromisoformat(record["expires_at"])
    return (expires - _now()).total_seconds()
