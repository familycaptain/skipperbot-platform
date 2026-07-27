"""Backups App — Platform Hooks
===============================
Registers the backup-schedule seeder as a lifecycle background task so it runs ONCE
**after all apps have loaded**.

Why not at import time: backups loads before schedules alphabetically, so the
``app_schedules`` tables may not exist yet. Lifecycle background tasks are started by the
platform after ``load_all_apps()`` (see ``app_platform/lifecycle.py``). The seeder is
fail-closed and guards a not-yet-created table, so boot can never crash on it.

Called by the app loader during startup via ``register_hooks()``.
"""


def register_hooks():
    """Register the one-shot backup-schedule seeder with the platform lifecycle."""
    from app_platform.lifecycle import register_background_task
    from apps.backups.schedule import seed_schedules

    # Pass the coroutine FUNCTION (zero-arg factory), NOT seed_schedules().
    register_background_task("backups_schedule_seed", seed_schedules)
