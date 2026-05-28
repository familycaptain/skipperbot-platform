"""Platform Reminders Service
=============================
Stable contract that every other app uses to set a reminder or query
reminder state. Forwards to ``apps.reminders.store`` /
``apps.reminders.data``.

This shim mirrors the ``app_platform.notifications`` pattern: apps use
a short, stable import path — ``from app_platform.reminders import
create_reminder`` — that is documented in `APP_PACKAGES.md` as **the**
way to talk to reminders. If we ever swap implementations, all
consumers stay unchanged.

Usage from an app or platform module:

    from app_platform.reminders import create_reminder

    create_reminder(
        user_id="alice",
        message="Trash day tomorrow",
        remind_at="2026-05-30T07:00:00+00:00",
        recurrence=None,                # or RRULE string
    )
"""

from __future__ import annotations

# Re-export the canonical surface from the reminders app. Keep this
# list narrow — every additional export becomes a long-term contract.
from apps.reminders.store import (
    create_reminder,
    create_nag,
    list_reminders,
    get_reminder,
    cancel_reminder,
    modify_reminder,
    snooze_reminder,
    get_due_reminders,
    mark_delivered,
    assign_nag_times,
    compute_next_occurrence,
    # Private bulk-CRUD escape hatch used by the goals autonag refresh
    # path. Don't add new callers; reach for ``modify_reminder`` instead.
    _load_reminders,
    _save_reminders,
    _rrule_to_schedule_params,
)
from apps.reminders.data import (
    save_reminder,
    get_all_reminders,
    get_active_reminders,
    get_user_reminders,
    delete_reminder,
    next_sort_order,
    reorder_reminder,
)

__all__ = [
    # store API (high-level)
    "create_reminder",
    "create_nag",
    "list_reminders",
    "get_reminder",
    "cancel_reminder",
    "modify_reminder",
    "snooze_reminder",
    "get_due_reminders",
    "mark_delivered",
    "assign_nag_times",
    "compute_next_occurrence",
    # data API (low-level CRUD; rarely needed by other apps)
    "save_reminder",
    "get_all_reminders",
    "get_active_reminders",
    "get_user_reminders",
    "delete_reminder",
    "next_sort_order",
    "reorder_reminder",
]
