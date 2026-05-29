"""Prioritize app.

Owns the per-user *focus slots* table (max 3 active priorities) and
the *backlog aggregator* that pulls actionable items from every app
that registers a backlog provider (goals, reminders, schedules,
todo, plus optional apps like ``auto``).

Single table in ``app_prioritize.priority_focus``. Cross-app reads
flow through the platform shims (``app_platform.reminders`` /
``schedules`` / ``todo``) so this app has no hard dependency on the
internal table layout of any other app.
"""
