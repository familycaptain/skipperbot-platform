"""Reminders — required core app.

Owns the ``app_reminders.reminders`` table and the scheduler loop that
fires due reminders. A reminder is a per-user "tell me X at time Y"
record; recurring reminders use RFC-5545 RRULE strings and (in v1)
optionally back themselves with a Schedules-app entity for richer
recurrence tracking.

Other apps that want to set a reminder for the user (Goals' due-date
nudges, Trello card due dates, etc.) go through the
``app_platform.reminders`` shim — same pattern that
``app_platform.notifications`` uses.
"""
