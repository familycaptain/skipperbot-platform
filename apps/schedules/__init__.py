"""Schedules — required core app.

Owns the ``app_schedules.schedules`` and ``app_schedules.schedule_completions``
tables and the engine that computes "what's next" for recurring chores,
maintenance, school, auto, medical, and general events.

The Reminders app references schedules from its ``schedule_id`` column
(plain TEXT, no FK) when a recurring reminder is backed by a schedule.
Other apps that want to "fire something every Tuesday at 7" go through
the ``app_platform.schedules`` shim.
"""
