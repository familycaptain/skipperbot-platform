"""
Research Tools — Start, monitor, and cancel background research jobs.
Research runs asynchronously and produces a d-* document with curated findings.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app_platform.jobs import (
    create_research_job as _create_research_job,
    create_refine_job as _create_refine_job,
    get_job as _get_job,
    list_jobs as _list_jobs,
    cancel_job as _cancel_job,
    format_jobs as _format_jobs,
)


def start_research(
    query: str,
    requested_by: str,
    num_sources: str = "5",
    scheduled_for: str = "",
    related_entity_id: str = "",
    notify_user: str = "",
    tags: str = "",
    spec_doc_id: str = "",
) -> str:
    """Start a background research job. The system will search the web, read sources,
    summarize findings, and create a document (d-*) with the results.

    Research runs in the background — you'll be notified when it's done.
    The output document will contain sourced summaries, key findings, and next steps.

    An intelligent research planner analyzes the query (and optional specification
    document) to generate strategic, targeted web search queries before searching.
    This ensures high-quality results even for complex, multi-faceted topics.

    Args:
        query: What to research (e.g. "best solar panels for residential use 2026").
               Can be short or detailed — the planner will generate optimized
               search queries regardless.
        requested_by: Who is requesting this research (e.g. "alice").
        num_sources: How many web sources to read, 1-20. Defaults to "5".
        scheduled_for: ISO datetime to start the research. Leave empty to start immediately.
                       Example: "2026-02-09T08:00:00-06:00" to start tomorrow morning.
        related_entity_id: Optional entity to link the output doc to (e.g. "p-abc123").
        notify_user: Who to notify when complete. Defaults to requested_by.
        tags: Comma-separated tags for the output document (e.g. "solar,home,research").
        spec_doc_id: Optional document ID (d-*) containing detailed research
                     specifications. When provided, the planner reads this document
                     and uses its content to generate more targeted search queries.
                     Use this when the user has written up detailed requirements,
                     criteria, or a research brief in a Document.

    Returns:
        Confirmation with job ID and status.

    Ack: Queuing research job...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."
        if not requested_by or not requested_by.strip():
            return "Error: requested_by is required."

        try:
            n = int(num_sources)
        except (ValueError, TypeError):
            n = 5

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        job = _create_research_job(
            query=query.strip(),
            requested_by=requested_by.strip(),
            num_sources=n,
            scheduled_for=scheduled_for.strip() if scheduled_for else "",
            related_entity_id=related_entity_id.strip() if related_entity_id else "",
            notify_user=notify_user.strip() if notify_user else "",
            tags=tag_list,
            spec_doc_id=spec_doc_id.strip() if spec_doc_id else "",
        )

        sched_msg = ""
        if job.get("scheduled_for"):
            sched_msg = f"\n  Scheduled for: {job['scheduled_for']}"
        else:
            sched_msg = "\n  Starting: immediately (next scheduler cycle)"

        link_msg = ""
        if job.get("config", {}).get("related_entity_id"):
            link_msg = f"\n  Linked to: {job['config']['related_entity_id']}"

        spec_msg = ""
        if job.get("config", {}).get("spec_doc_id"):
            spec_msg = f"\n  Spec doc: {job['config']['spec_doc_id']}"

        return (
            f"Research job queued ({job['id']})\n"
            f"  Query: {job['config']['query'][:120]}\n"
            f"  Sources: {job['config']['num_sources']}"
            f"{sched_msg}"
            f"\n  Notify: {job['notify_user']}"
            f"{link_msg}"
            f"{spec_msg}\n"
            f"The research planner will generate strategic search queries "
            f"and I'll notify you when the research is complete."
        )

    except Exception as e:
        return f"Error in start_research: {str(e)}"


def check_research(job_id: str) -> str:
    """Check the status and progress of a research job.

    Args:
        job_id: The job ID (e.g. "j-abc12345").

    Returns:
        Current status, progress, and output details.

    Ack: Checking research status...
    """
    try:
        if not job_id or not job_id.strip():
            return "Error: job_id is required."

        job = _get_job(job_id.strip())
        if not job:
            return f"Error: Job '{job_id}' not found."

        if job.get("job_type") != "research":
            return f"Error: Job '{job_id}' is not a research job (type: {job.get('job_type', 'shell')})."

        config = job.get("config", {})
        output = job.get("output", {})
        status = job.get("status", "?").upper()

        lines = [
            f"Research Job: {job['id']} — {status}",
            f"  Query: {config.get('query', '?')}",
            f"  Progress: {job.get('progress', '?')}",
            f"  Sources: {output.get('sources_read', 0)}/{output.get('sources_found', 0)} read",
        ]

        if output.get("doc_id"):
            lines.append(f"  Document: {output['doc_id']}")

        if job.get("scheduled_for"):
            lines.append(f"  Scheduled for: {job['scheduled_for']}")

        lines.append(f"  Created: {job.get('created_at', '?')[:16]} by {job.get('created_by', '?')}")

        if job.get("last_run_at"):
            lines.append(f"  Last run: {job['last_run_at'][:16]}")

        if job.get("last_result"):
            lines.append(f"  Result: {job['last_result'][:200]}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error in check_research: {str(e)}"


def cancel_research(job_id: str, cancelled_by: str = "") -> str:
    """Cancel a queued or running research job.

    If the research is currently in progress, it will stop after completing
    the current source (won't create the final document).

    Args:
        job_id: The job ID to cancel (e.g. "j-abc12345").
        cancelled_by: Who is cancelling.

    Returns:
        Confirmation or error.

    Ack: Cancelling research job...
    """
    try:
        if not job_id or not job_id.strip():
            return "Error: job_id is required."

        return _cancel_job(
            job_id=job_id.strip(),
            cancelled_by=cancelled_by.strip() if cancelled_by else "",
        )

    except Exception as e:
        return f"Error in cancel_research: {str(e)}"


def list_research_jobs(
    status_filter: str = "",
    requested_by: str = "",
) -> str:
    """List all research jobs with optional filters.

    Args:
        status_filter: Filter by status: "queued", "running", "completed", "failed", "cancelled".
        requested_by: Filter by who requested.

    Returns:
        Formatted list of research jobs.

    Ack: Listing research jobs...
    """
    try:
        all_jobs = _list_jobs(
            status_filter=status_filter.strip() if status_filter else "",
            created_by=requested_by.strip().lower() if requested_by else "",
        )
        # Filter to research jobs only
        research_jobs = [j for j in all_jobs if j.get("job_type") == "research"]

        if not research_jobs:
            return "No research jobs found."

        lines = [f"Research Jobs ({len(research_jobs)}):"]
        for j in research_jobs:
            config = j.get("config", {})
            output = j.get("output", {})
            status = j.get("status", "?").upper()
            doc = f" → {output['doc_id']}" if output.get("doc_id") else ""
            sched = f" [scheduled: {j['scheduled_for'][:16]}]" if j.get("scheduled_for") else ""
            lines.append(
                f"  [{j['id']}] {status}{sched} — {config.get('query', '?')[:60]}{doc}"
            )
            lines.append(
                f"    Progress: {j.get('progress', '?')} | "
                f"Sources: {output.get('sources_read', 0)}/{output.get('sources_found', 0)} | "
                f"By: {j.get('created_by', '?')}"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_research_jobs: {str(e)}"


def refine_research(
    doc_id: str,
    instructions: str,
    requested_by: str,
    num_sources: str = "3",
    notify_user: str = "",
) -> str:
    """Refine an existing research document with additional targeted research.

    This does NOT modify the original document. Instead it:
    1. Reads the existing document
    2. Generates focused search queries based on your instructions
    3. Searches the web for additional information
    4. Produces a NEW versioned document (v2, v3, etc.) with the improvements

    The original document is always preserved. Use this when a research doc
    needs more detail on a specific section, missed an angle, or needs updating.

    Args:
        doc_id: The document ID to refine (e.g. "d-abc12345").
        instructions: What to expand, improve, or focus on.
                      Examples: "expand the section on side effects",
                      "add more information about pricing and availability",
                      "the vacuum bell section needs more clinical studies".
        requested_by: Who is requesting this refinement (e.g. "alice").
        num_sources: How many additional web sources to research, 1-10. Defaults to "3".
        notify_user: Who to notify when complete. Defaults to requested_by.

    Returns:
        Confirmation with job ID.

    Ack: Queuing research refinement...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."
        if not instructions or not instructions.strip():
            return "Error: instructions are required — tell me what to expand or improve."
        if not requested_by or not requested_by.strip():
            return "Error: requested_by is required."

        doc_id = doc_id.strip()
        if not doc_id.startswith("d-"):
            return f"Error: '{doc_id}' doesn't look like a document ID (expected d-*)."

        try:
            n = int(num_sources)
        except (ValueError, TypeError):
            n = 3

        job = _create_refine_job(
            doc_id=doc_id,
            instructions=instructions.strip(),
            requested_by=requested_by.strip(),
            num_sources=n,
            notify_user=notify_user.strip() if notify_user else "",
        )

        return (
            f"Research refinement queued ({job['id']})\n"
            f"  Document: {doc_id}\n"
            f"  Instructions: {instructions[:100]}\n"
            f"  Additional sources: {n}\n"
            f"  Starting: next scheduler cycle (~30 seconds)\n"
            f"The original document will be preserved. "
            f"I'll create a new version with the improvements and notify you."
        )

    except Exception as e:
        return f"Error in refine_research: {str(e)}"
