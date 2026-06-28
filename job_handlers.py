"""Job Handlers — Bridges existing runners to the unified job dispatcher.

Each handler is an async function with signature:
    async def handler(job: dict, ctx: JobContext) -> str

Handlers are registered at import time via register_all_handlers().
"""

from config import logger
from app_platform.jobs import register_handler, JobContext


# ---------------------------------------------------------------------------
# Research handler
# ---------------------------------------------------------------------------

def _handle_research(job: dict, ctx: JobContext) -> str:
    """Run a research job (synchronous — runs in thread pool)."""
    from research_runner import _run_research_pipeline
    ctx.update_progress(5, "Starting research pipeline...")
    result = _run_research_pipeline(job)
    doc_id = result.get("doc_id", "")
    return f"Research complete: {doc_id}" if doc_id else "Research completed"


# ---------------------------------------------------------------------------
# Refine handler
# ---------------------------------------------------------------------------

def _handle_refine(job: dict, ctx: JobContext) -> str:
    """Run a refine job (synchronous — runs in thread pool)."""
    from research_runner import _run_refine_pipeline
    ctx.update_progress(5, "Starting refine pipeline...")
    result = _run_refine_pipeline(job)
    return f"Refine complete" if result.get("success") else f"Refine failed: {result.get('error', '?')}"


# ---------------------------------------------------------------------------
# Print handler
# ---------------------------------------------------------------------------

def _handle_print(job: dict, ctx: JobContext) -> str:
    """Run a print job (synchronous — runs in thread pool)."""
    from print_runner import _run_print_pipeline
    ctx.update_progress(10, "Printing...")
    result = _run_print_pipeline(job)
    if result.get("success"):
        return f"Printed via {result.get('method', '?')}"
    return f"Print failed: {result.get('error', '?')}"


# ---------------------------------------------------------------------------
# PM (Project Manager) handler
# ---------------------------------------------------------------------------

async def _handle_pm(job: dict, ctx: JobContext) -> str:
    """Run the Project Manager daily cycle."""
    from apps.goals.pm_runner import check_and_run_pm
    ctx.update_progress(10, "Running PM cycle...")
    await check_and_run_pm(force=True)
    return "PM cycle complete"


async def _handle_pm_check(job: dict, ctx: JobContext) -> str:
    """Run a lighter PM check-in between daily scrums."""
    from apps.goals.pm_runner import run_pm_check
    ctx.update_progress(10, "Running PM check-in...")
    await run_pm_check()
    return "PM check-in complete"


# ---------------------------------------------------------------------------
# Investment handler
# ---------------------------------------------------------------------------

async def _handle_investment(job: dict, ctx: JobContext) -> str:
    """Run the investment analysis pipeline (delegated to app package)."""
    from apps.investment.handlers import handle_investment
    return await handle_investment(job, ctx)


# ---------------------------------------------------------------------------
# Rebalance handler
# ---------------------------------------------------------------------------

async def _handle_rebalance(job: dict, ctx: JobContext) -> str:
    """Run a portfolio rebalance (delegated to app package)."""
    from apps.investment.handlers import handle_rebalance
    return await handle_rebalance(job, ctx)


# ---------------------------------------------------------------------------
# Backup handler
# ---------------------------------------------------------------------------

# Note: the backup + backup_check handlers were migrated to
# apps/backups/handlers.py as part of packaging the backups app.


# Email handler now auto-registered from apps/email/manifest.yaml


# ---------------------------------------------------------------------------
# Equity Curve handler
# ---------------------------------------------------------------------------

async def _handle_equity_curve(job: dict, ctx: JobContext) -> str:
    """Run an equity curve tick (delegated to app package)."""
    from apps.investment.handlers import handle_equity_curve
    return await handle_equity_curve(job, ctx)


# Note: the folder_intelligence handler was migrated to
# apps/folders/handlers.py as part of packaging the folders app.

# ---------------------------------------------------------------------------
# Meals — Dinner Check handler
# ---------------------------------------------------------------------------

def _handle_meals_dinner_check(job: dict, ctx: JobContext) -> str:
    """Check if tonight's dinner is logged; prompt Alice if not."""
    from apps.meals.handlers import handle_dinner_check
    return handle_dinner_check(job, ctx)


# ---------------------------------------------------------------------------
# Scriptures — nightly prefetch
# ---------------------------------------------------------------------------

def _handle_scripture_prefetch(job: dict, ctx: JobContext) -> str:
    """Pre-generate summary, people, and places for bookmarked chapters + 3 ahead.

    Scriptures is an OPTIONAL app — guard the import so the platform job system
    keeps working when it isn't installed (the job is only ever queued BY the app).
    """
    try:
        from apps.scriptures.prefetch import prefetch_scripture_summaries
    except ImportError:
        return "Scriptures app not installed — nothing to prefetch."
    return prefetch_scripture_summaries()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all_handlers():
    """Register all job handlers with the dispatcher. Call once at startup."""
    register_handler("research", _handle_research, max_concurrent=2)
    register_handler("refine", _handle_refine, max_concurrent=2)
    register_handler("print", _handle_print, max_concurrent=1)
    register_handler("pm", _handle_pm, max_concurrent=1)
    register_handler("pm_check", _handle_pm_check, max_concurrent=1)
    register_handler("investment", _handle_investment, max_concurrent=1, cancel_on_shutdown=False)
    register_handler("rebalance", _handle_rebalance, max_concurrent=1, cancel_on_shutdown=False)
    # backup + backup_check are registered by apps/backups/handlers.py.
    register_handler("equity_curve", _handle_equity_curve, max_concurrent=1, cancel_on_shutdown=False)
    # folder_intelligence is registered by apps/folders/handlers.py.
    register_handler("meals_dinner_check", _handle_meals_dinner_check, max_concurrent=1)
    register_handler("scripture_prefetch", _handle_scripture_prefetch, max_concurrent=1)
    logger.info("JOB_HANDLERS: All handlers registered")
