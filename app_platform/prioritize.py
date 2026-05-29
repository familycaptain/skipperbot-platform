"""Platform Prioritize Service
==============================
Stable contract that every other app and platform module uses to
read or mutate user focus slots and the cross-app backlog. Forwards
to ``apps.prioritize.data`` (CRUD + backlog aggregator + provider
registries).

Mirrors the ``app_platform.notifications`` / ``reminders`` /
``schedules`` / ``jobs`` / ``documents`` / ``folders`` /
``behaviors`` patterns. Apps use a short, stable import path —
``from app_platform.prioritize import …`` — that is documented in
``APP_PACKAGES.md`` as the way to talk to prioritize.

Other apps register their backlog contributions and activity checks
at load time::

    from app_platform.prioritize import register_backlog_provider
    register_backlog_provider("auto_issues", _auto_issues_for_user)
"""

from __future__ import annotations

from apps.prioritize.data import (
    # Focus slot CRUD
    get_focus_slots,
    set_focus,
    promote_to_focus,
    clear_focus,
    clear_focus_by_source,
    reorder_focus,
    cleanup_stale_focus,
    # Backlog aggregator
    get_backlog,
    # Focus-nag preference (stored on platform-owned users table)
    get_focus_nag_enabled,
    set_focus_nag_enabled,
    # Provider registries
    register_backlog_provider,
    register_activity_checker,
)

__all__ = [
    "get_focus_slots",
    "set_focus",
    "promote_to_focus",
    "clear_focus",
    "clear_focus_by_source",
    "reorder_focus",
    "cleanup_stale_focus",
    "get_backlog",
    "get_focus_nag_enabled",
    "set_focus_nag_enabled",
    "register_backlog_provider",
    "register_activity_checker",
]
