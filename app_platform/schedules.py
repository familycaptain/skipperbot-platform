"""Platform Schedules Service
=============================
Stable contract that every other app uses to read or mutate
schedules. Forwards to ``apps.schedules.data`` (which also houses the
recurrence engine).

This shim mirrors the ``app_platform.notifications`` and
``app_platform.reminders`` patterns: apps use a short, stable import
path — ``from app_platform.schedules import create_schedule`` — that
is documented in ``APP_PACKAGES.md`` as the way to talk to schedules.
If we ever swap implementations, all consumers stay unchanged.

Usage from an app or platform module:

    from app_platform.schedules import (
        create_schedule, complete_schedule, get_due_schedules,
        get_calendar_events, describe_recurrence, compute_next_due,
    )
"""

from __future__ import annotations

# Re-export the canonical surface from the schedules app. Keep this
# list narrow — every additional export becomes a long-term contract.
from apps.schedules.data import (
    # CRUD
    create_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
    delete_schedule,
    complete_schedule,
    get_completions,
    # Queries
    get_due_schedules,
    get_calendar_events,
    # Recurrence engine
    compute_next_due,
    describe_recurrence,
    # Legacy/internal escape hatches kept stable for callers that
    # reach in for row-dict normalization or RRULE iteration helpers.
    _row_to_dict,
    _expand_rrule_occurrences,
    # Module-local timezone (a small handful of agent.py call sites
    # import this).
    CENTRAL_TZ,
)

__all__ = [
    "create_schedule",
    "get_schedule",
    "list_schedules",
    "update_schedule",
    "delete_schedule",
    "complete_schedule",
    "get_completions",
    "get_due_schedules",
    "get_calendar_events",
    "compute_next_due",
    "describe_recurrence",
    "CENTRAL_TZ",
]
