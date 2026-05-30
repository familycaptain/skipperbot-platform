"""Platform Backups Service
===========================
Stable contract for everything that needs to read or mutate the
backups audit table, or trigger / verify a backup run. Forwards to
``apps.backups.data`` (CRUD), ``apps.backups.runner`` (the two job
handlers), and exposes a small ``config`` helper so the UI can flip
toggles without hard-coding the scope string.

Mirrors the ``app_platform.notifications`` / ``reminders`` /
``schedules`` / ``jobs`` / ``documents`` / ``folders`` /
``behaviors`` / ``prioritize`` shims.

Usage from any caller::

    from app_platform.backups import list_backups, run_backup
    backups = list_backups(limit=50)
"""

from __future__ import annotations

from typing import Any

from apps.backups.data import (
    create_backup,
    complete_backup,
    skip_backup,
    fail_backup,
    get_backup,
    list_backups,
    delete_backup,
    prune_old_records,
    list_today,
)
from apps.backups.runner import (
    run_backup,
    run_backup_check,
)
from app_platform import config as _config

CONFIG_SCOPE = "app:backups"


# All config keys declared in apps/backups/manifest.yaml — used by the
# UI to render the cog wheel and by the REST endpoints to round-trip
# safely.
CONFIG_KEYS: tuple[str, ...] = (
    "enabled",
    "cron",
    "retention",
    "filesystem_enabled",
    "filesystem_path",
    "gdrive_enabled",
    "gdrive_impersonate_email",
    # gdrive_service_account_json is a SECRET — managed only through the
    # Settings → Backups panel (encrypted at rest), never the legacy config API.
)


def get_config() -> dict[str, Any]:
    """Return the current ``app:backups`` config as a dict.

    Missing keys fall back to the manifest defaults from the data layer's
    point of view (i.e. ``_config.get`` returns ``None`` for unset keys).
    The REST endpoint coerces them to the documented types.
    """
    return {k: _config.get(k, scope=CONFIG_SCOPE) for k in CONFIG_KEYS}


def set_config(updates: dict[str, Any], *, by: str = "") -> dict[str, Any]:
    """Patch one or more keys in the ``app:backups`` config and return the new dict."""
    for key, value in updates.items():
        if key not in CONFIG_KEYS:
            raise ValueError(f"unknown backups config key: {key!r}")
        _config.set(key, value, scope=CONFIG_SCOPE, by=by)
    return get_config()


__all__ = [
    # Data layer
    "create_backup", "complete_backup", "skip_backup", "fail_backup",
    "get_backup", "list_backups", "delete_backup", "prune_old_records",
    "list_today",
    # Job handlers (exposed so the system app's "Run backup now" UI
    # can also call run_backup synchronously when it wants to).
    "run_backup", "run_backup_check",
    # Config
    "CONFIG_SCOPE", "CONFIG_KEYS", "get_config", "set_config",
]
