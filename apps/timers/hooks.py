"""Timers App — Platform Hooks
===============================
Registers timer graceful-shutdown with the platform so the platform core no
longer imports ``apps.timers`` directly (see specs/platform/loader/lifecycle-hooks).

Timers has NO startup/background worker — timers are created on demand by the
``start_timer`` tool (not event-driven). Only the shutdown hook is registered,
so in-flight timers are cancelled cleanly at shutdown.

Called by the app loader during startup via ``register_hooks()``.
"""


def register_hooks():
    """Register timer shutdown with the platform (no background worker)."""
    from app_platform.lifecycle import register_shutdown_hook
    # App importing its own module — allowed.
    from apps.timers.scheduler import shutdown_all_timers

    register_shutdown_hook(shutdown_all_timers)
