"""Platform Behaviors Service
============================
Stable contract that every other app and platform module uses to
read or mutate user behavior rules. Forwards to ``apps.behaviors.data``
(low-level CRUD), which keeps the schema-isolation rule intact.

Mirrors the ``app_platform.notifications`` / ``reminders`` /
``schedules`` / ``jobs`` / ``documents`` / ``folders`` patterns. Apps
use a short, stable import path —
``from app_platform.behaviors import get_active_behaviors_for_user`` —
that is documented in ``APP_PACKAGES.md`` as the way to talk to
behaviors.

Usage from chat / voice prompting code::

    from app_platform.behaviors import get_active_behaviors_for_user
    rules = get_active_behaviors_for_user("alice")
    # … inject rules unconditionally into the system prompt …
"""

from __future__ import annotations

from apps.behaviors.data import (
    create_behavior,
    get_behavior,
    list_behaviors,
    update_behavior,
    toggle_behavior,
    delete_behavior,
    get_active_behaviors_for_user,
)

__all__ = [
    "create_behavior",
    "get_behavior",
    "list_behaviors",
    "update_behavior",
    "toggle_behavior",
    "delete_behavior",
    "get_active_behaviors_for_user",
]
