"""Meals App — Platform Hooks
==============================
Registers the nightly-dinner-check seeder as a lifecycle background task so it
runs ONCE **after all apps have loaded**.

Why not seed at import/module-load time: meals loads before schedules
alphabetically, so at meals-load time the ``app_schedules`` schema/tables may
not exist yet. Lifecycle background tasks are started by the platform AFTER
``load_all_apps()`` (see ``app_platform/lifecycle.py``), by which point the
schedules app has run its migrations. The seeder itself (reconcile) is
fail-closed and guards a not-yet-created table, so boot can never crash on it.

Called by the app loader during startup via ``register_hooks()``.
"""


def register_hooks():
    """Register the one-shot dinner-schedule seeder with the platform lifecycle."""
    from app_platform.lifecycle import register_background_task
    # App importing its own module — allowed (the rule is platform-must-not-import-apps).
    from apps.meals.schedule import seed_dinner_schedule

    # Pass the coroutine FUNCTION (zero-arg factory), NOT seed_dinner_schedule().
    register_background_task("meals_dinner_seed", seed_dinner_schedule)
