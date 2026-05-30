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


# Cache the platform timezone *name* in-process. Onboarding writes it
# once; later changes via the Settings app take effect after a restart
# (or by calling ``invalidate_platform_timezone_cache`` from the setter).
# Storing only the resolved name (not the DB read result) means a "no row
# yet" outcome is NOT cached — we'll re-check next call so a freshly
# completed onboarding starts working without a restart.
_PLATFORM_TZ_NAME: str | None = None


def invalidate_platform_timezone_cache() -> None:
    """Drop the cached platform timezone name so the next call re-reads
    ``app_config``. Call this from any code path that mutates the
    platform-scoped ``timezone`` setting (e.g. the Settings app)."""
    global _PLATFORM_TZ_NAME
    _PLATFORM_TZ_NAME = None


def get_timezone(user_id: str | None = None) -> ZoneInfo:
    """Return the configured timezone as a ZoneInfo.

    Resolution order:
      1. The user's ``users.timezone`` override (if user_id given).
      2. The platform-level setting in ``app_config`` (set during
         onboarding; editable via the Settings app).
      3. ``Etc/UTC``.
    """
    global _PLATFORM_TZ_NAME

    if user_id:
        user_tz = _user_timezone(user_id)
        if user_tz:
            return _zoneinfo(user_tz)

    if _PLATFORM_TZ_NAME is not None:
        return _zoneinfo(_PLATFORM_TZ_NAME)

    try:
        platform_tz = _config_get(scope="platform", key="timezone", default=None)
    except Exception:
        platform_tz = None

    if platform_tz:
        # Persist for subsequent calls. Skip caching when unset so that a
        # freshly onboarded install picks up the new value immediately.
        _PLATFORM_TZ_NAME = str(platform_tz)
        return _zoneinfo(_PLATFORM_TZ_NAME)

    return _zoneinfo(DEFAULT_TZ)


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
