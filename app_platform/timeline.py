"""Platform Timeline Service
============================
Stable contract that every other app uses to read or mutate timeline
posts. Forwards to ``apps.timeline.data`` (CRUD + photos + tag index).

The platform's auto-activity log (``app_platform/activity.py``) does
*not* go through this shim — it writes directly into
``app_timeline.timeline_posts`` to avoid a circular import at boot. So
this shim is the canonical contract for *non-activity-log* callers
(the chat tools, the REST routes, future apps).

Mirrors the ``app_platform.notifications`` / ``reminders`` /
``schedules`` / ``jobs`` / ``documents`` / ``folders`` /
``behaviors`` / ``prioritize`` / ``backups`` shims.
"""

from __future__ import annotations

from apps.timeline.data import (
    create_post,
    get_post,
    list_posts,
    update_post,
    delete_post,
    toggle_pin,
    add_photo,
    remove_photo,
    list_authors,
    list_tags,
)

__all__ = [
    "create_post",
    "get_post",
    "list_posts",
    "update_post",
    "delete_post",
    "toggle_pin",
    "add_photo",
    "remove_photo",
    "list_authors",
    "list_tags",
]
