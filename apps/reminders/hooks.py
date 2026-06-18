"""Reminders App — Platform Hooks
==================================
Registers the reminder scheduler as a platform background task and its
graceful-shutdown signal as a shutdown hook, so the platform core no longer
imports ``apps.reminders`` directly (see specs/platform/loader/lifecycle-hooks).

Called by the app loader during startup via ``register_hooks()``.
"""


def register_hooks():
    """Register the reminders scheduler + graceful shutdown with the platform."""
    from app_platform.lifecycle import (
        register_background_task,
        register_shutdown_hook,
    )
    # App importing its own module — allowed (the rule is platform-must-not-import-apps).
    from apps.reminders.scheduler import start_reminder_scheduler, request_shutdown

    # Pass the function itself (zero-arg factory), NOT start_reminder_scheduler().
    register_background_task("reminders_scheduler", start_reminder_scheduler)
    register_shutdown_hook(request_shutdown)
