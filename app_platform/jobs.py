"""Platform Jobs Service
=========================
Stable contract that every other app uses to talk to the jobs system.
Forwards to ``apps.jobs.dispatcher`` (handler registration + submission +
context), ``apps.jobs.data`` (CRUD), and ``apps.jobs.store`` (friendly
helpers that fire digest_record / log_entity_change).

This shim mirrors the ``app_platform.notifications`` /
``app_platform.reminders`` / ``app_platform.schedules`` patterns
established in earlier chunks. Apps use a short, stable import path
— ``from app_platform.jobs import submit_job, register_handler`` —
that is documented in ``APP_PACKAGES.md`` as the way to talk to jobs.
If we ever swap implementations, all consumers stay unchanged.

Usage from an app or platform module:

    from app_platform.jobs import register_handler, JobContext

    def _handle_my_job(job: dict, ctx: JobContext) -> str:
        ctx.update_progress(50)
        return "Done."

    register_handler("my_job_type", _handle_my_job, max_concurrent=1)

    # Submit a job
    from app_platform.jobs import submit_job
    job = submit_job(
        job_type="my_job_type",
        name="A friendly job name",
        created_by="alice",
        config={"my_param": "value"},
    )
"""

from __future__ import annotations

# Re-export the canonical surface. Keep this list narrow — every
# additional export becomes a long-term contract.

# ---- Dispatcher engine (handler registry + submit + context) ----
from apps.jobs.dispatcher import (
    register_handler,
    submit_job,
    JobContext,
    RequeueRequested,
    start_dispatcher,
    request_shutdown,
    is_shutting_down,
    get_active_job_ids,
)

# ---- Data layer (CRUD + queue engine) ----
from apps.jobs.data import (
    create_job as data_create_job,
    get_job,
    list_jobs,
    list_running,
    count_running,
    is_cancelled,
    claim_queued_jobs,
    update_progress,
    update_output,
    complete_job,
    fail_job,
    cancel_job as data_cancel_job,
    fail_stale_running,
    append_log,
    get_logs,
    # Simple CRUD (from the legacy data_layer/jobs.py side of the port)
    save_job,
    get_all_jobs,
    get_active_jobs,
    delete_job,
    save_all_jobs,
)

# ---- Store layer (friendly helpers — digest_record + auto_memory) ----
from apps.jobs.store import (
    create_job,
    update_job,
    record_run,
    cancel_job,
    create_research_job,
    create_print_job,
    create_recipe_print_job,
    create_refine_job,
    get_pending_research_jobs,
    get_pending_print_jobs,
    get_pending_refine_jobs,
    update_job_progress,
    format_jobs,
)

__all__ = [
    # Dispatcher engine
    "register_handler", "submit_job", "JobContext", "RequeueRequested",
    "start_dispatcher", "request_shutdown", "is_shutting_down",
    "get_active_job_ids",
    # Data layer
    "get_job", "list_jobs", "list_running", "count_running", "is_cancelled",
    "claim_queued_jobs", "update_progress", "update_output",
    "complete_job", "fail_job", "fail_stale_running",
    "append_log", "get_logs",
    "save_job", "get_all_jobs", "get_active_jobs", "delete_job", "save_all_jobs",
    # Store layer
    "create_job", "update_job", "record_run", "cancel_job",
    "create_research_job", "create_print_job", "create_recipe_print_job",
    "create_refine_job", "get_pending_research_jobs",
    "get_pending_print_jobs", "get_pending_refine_jobs",
    "update_job_progress", "format_jobs",
]
