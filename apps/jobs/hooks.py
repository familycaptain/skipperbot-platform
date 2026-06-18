"""Jobs App — Platform Hooks
=============================
Registers the job runner as a platform background task so the platform core no
longer imports ``apps.jobs`` directly (see specs/platform/loader/lifecycle-hooks).

Jobs has NO graceful shutdown — the runner is cancel-only, so no shutdown hook
is registered.

Called by the app loader during startup via ``register_hooks()``.
"""


def register_hooks():
    """Register the jobs runner as a platform background task."""
    from app_platform.lifecycle import register_background_task
    # App importing its own module — allowed.
    from apps.jobs.runner import start_job_runner

    # Pass the function itself (zero-arg factory), NOT start_job_runner().
    register_background_task("jobs_runner", start_job_runner)
