"""Platform Time Service
========================
Single source of truth for time-of-day, timezone, and "now" across the
platform and every app.

**Hard rule:** no module — platform or app — may construct a `ZoneInfo`
with a hardcoded timezone literal or call `datetime.now()` without an
explicit timezone. Always go through this module.

The timezone is configured at onboarding and stored in
``public.app_config(scope='platform', key='timezone', value='...')``.
Default is ``Etc/UTC`` if not set.

Per-user timezone overrides live in ``public.users.timezone`` and the
helper signatures take an optional ``user_id`` argument so user-scoped
timestamps respect that override.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from app_platform.config import get as _config_get


DEFAULT_TZ = "Etc/UTC"


@lru_cache(maxsize=32)
def _zoneinfo(name: str) -> ZoneInfo:
    """Cache ZoneInfo instances. Falls back to UTC on invalid names."""
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def get_timezone(user_id: str | None = None) -> ZoneInfo:
    """Return the configured timezone as a ZoneInfo.

    If ``user_id`` is provided AND that user has a non-empty
    ``users.timezone`` value, return the user's override. Otherwise fall
    back to the platform-level setting from ``app_config``.

    Defaults to ``Etc/UTC`` if nothing is configured.
    """
    if user_id:
        user_tz = _user_timezone(user_id)
        if user_tz:
            return _zoneinfo(user_tz)

    platform_tz = _config_get(scope="platform", key="timezone", default=DEFAULT_TZ)
    return _zoneinfo(platform_tz)


def now(user_id: str | None = None) -> datetime:
    """Timezone-aware ``now`` in the configured timezone.

    Equivalent to ``datetime.now(get_timezone(user_id))``.
    """
    return datetime.now(get_timezone(user_id))


def utcnow() -> datetime:
    """Timezone-aware ``now`` in UTC. Use this for DB storage."""
    return datetime.now(ZoneInfo("UTC"))


def to_local(dt: datetime, user_id: str | None = None) -> datetime:
    """Convert a datetime (aware or naive-treated-as-UTC) to the configured timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(get_timezone(user_id))


def _user_timezone(user_id: str) -> str | None:
    """Lookup a user's timezone override. Returns None if not set or user missing."""
    # Lazy import to avoid a hard dependency on the users data layer during
    # bootstrap; this function is only called after the platform is running.
    try:
        from data_layer.users import get_user

        user = get_user(user_id)
        if user and user.get("timezone"):
            return str(user["timezone"]).strip() or None
    except Exception:
        pass
    return None
