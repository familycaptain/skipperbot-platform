"""Platform Notifications Service
=================================
Stable contract that every other app uses to record a notification.
Forwards to ``apps.notifications.store.create_notification`` (and
exposes a few read helpers).

The point of this shim is to give other apps a short, stable import
path — ``from app_platform.notifications import create_notification`` —
that is documented in `APP_PACKAGES.md` as **the** way to talk to
notifications. If we ever swap implementations (different package
name, different schema), all the consumers stay unchanged.

Usage from an app or platform module:

    from app_platform.notifications import create_notification

    create_notification(
        recipient="alice",
        message="Trash day tomorrow",
        source_type="reminder",
        source_id="r-abc12345",
        channel="discord",
    )
"""

from __future__ import annotations

# Re-export the canonical surface from the notifications app. Keep this
# list narrow — every additional export becomes a long-term contract.
from apps.notifications.store import (
    create_notification,
    get_notifications,
    format_notifications,
)
from apps.notifications.data import (
    get_notification,
    get_notifications_for_user,
    get_undelivered,
    get_all_undelivered,
    mark_delivered,
    delete_notification,
)

__all__ = [
    "create_notification",
    "get_notifications",
    "format_notifications",
    "get_notification",
    "get_notifications_for_user",
    "get_undelivered",
    "get_all_undelivered",
    "mark_delivered",
    "delete_notification",
]
