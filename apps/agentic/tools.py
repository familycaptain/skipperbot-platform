"""Tools for creating + managing autonomous scheduled tasks (#109).

`create_agentic_task` sets up the whole thing in one call: it writes the PROMPT
to a d-* document, then creates a public.schedules row whose job_config carries
the spec (prompt_doc_id, tool_categories, needs_attention, tier) and whose
linked_entity points at the `agentic` job type. When due, the schedule fires the
agentic job (see agentic.py). Edit a task's prompt by editing its document (in
chat or the Documents app); manage the schedule with the list/toggle/run tools.
"""
import re
import logging

logger = logging.getLogger("apps.agentic.tools")

_VALID_RECURRENCE = {"daily", "weekly", "monthly", "yearly", "interval", "cron", "rrule"}


def create_agentic_task(
    name: str,
    prompt: str,
    created_by: str,
    tool_categories: str = "",
    recurrence_type: str = "daily",
    time_of_day: str = "",
    needs_attention: bool = False,
    tier: str = "smart",
) -> str:
    """Set up an AUTONOMOUS SCHEDULED TASK — Skipper running a prompt on its own
    on a schedule.

    Use when a household member asks Skipper to do something automatically /
    on a schedule going forward (e.g. "every morning, check my calendar and
    draft a summary", "each Friday, review the chore log and note who's behind").

    Args:
        name: Short human name for the task (e.g. "Morning calendar summary").
        prompt: The full instructions Skipper should follow each time it runs —
            written as a task for Skipper to execute. Be specific about what to
            produce (a document, updates, findings). This is saved as a document
            you can edit later.
        created_by: Who is setting it up (a person's name).
        tool_categories: Comma-separated tool categories the task needs loaded to
            start (e.g. "app:goals,web,documents"). Skipper can request more at
            run time; `core` is always available. Leave empty for a
            prompt-only/thinking task.
        recurrence_type: daily | weekly | monthly | yearly (default daily).
        time_of_day: Local HH:MM for when it runs (e.g. "07:00"). Optional.
        needs_attention: True if the family should hear the RESULT each run
            (delivered in Skipper's voice). False for silent background work.
        tier: "smart" (default) or "fast" model tier for the task.

    Returns:
        Confirmation with the task's schedule id and prompt-document id.
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        if not prompt or not prompt.strip():
            return "Error: prompt is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."
        rtype = recurrence_type.strip().lower()
        if rtype not in _VALID_RECURRENCE:
            rtype = "daily"

        # 1. Save the prompt as a document (editable later, in chat or the doc app).
        from apps.documents.tools import create_doc
        doc_result = create_doc(
            title=f"{name.strip()} — task prompt",
            created_by=created_by.strip(),
            content=prompt.strip(),
            tags="agentic-task",
        )
        m = re.search(r"d-[0-9a-f]+", doc_result)
        if not m:
            return f"Error: could not create the prompt document ({doc_result[:120]})"
        doc_id = m.group(0)

        # 2. Parse the initial tool categories.
        cats = [c.strip() for c in (tool_categories or "").split(",") if c.strip()]

        # 3. Create the schedule; its job_config IS the agentic task spec.
        from apps.schedules.data import create_schedule
        sch = create_schedule(
            title=name.strip(),
            created_by=created_by.strip(),
            category="agentic",
            recurrence_type=rtype,
            time_of_day=(time_of_day.strip() or None),
            linked_entity_type="job",
            linked_entity_id="agentic",
            job_config={
                "prompt_doc_id": doc_id,
                "tool_categories": cats,
                "needs_attention": bool(needs_attention),
                "tier": (tier or "smart"),
            },
        )
        sid = sch.get("id", "?")
        when = f"{rtype}" + (f" at {time_of_day.strip()}" if time_of_day.strip() else "")
        return (
            f"Autonomous task created: '{name.strip()}' ({sid}).\n"
            f"  Runs: {when}\n"
            f"  Tools: {', '.join(cats) if cats else 'core only (request more at run time)'}\n"
            f"  Notifies family: {'yes' if needs_attention else 'no (silent)'}\n"
            f"  Prompt document: {doc_id} (edit it to change what the task does)."
        )
    except Exception as e:
        return f"Error in create_agentic_task: {e}"


def list_agentic_tasks() -> str:
    """List the autonomous scheduled tasks Skipper is set up to run."""
    try:
        from apps.schedules.data import list_schedules
        rows = [s for s in list_schedules(active_only=False, limit=500)
                if s.get("linked_entity_type") == "job" and s.get("linked_entity_id") == "agentic"]
        if not rows:
            return "No autonomous tasks are set up."
        lines = [f"{len(rows)} autonomous task(s):"]
        for s in rows:
            jc = s.get("job_config") or {}
            state = "active" if s.get("active") else "OFF"
            lines.append(
                f"  - {s.get('title','(untitled)')} ({s.get('id')}) — {state}, "
                f"{s.get('recurrence_type','?')}"
                + (f" @ {s.get('time_of_day')}" if s.get("time_of_day") else "")
                + (", notifies" if jc.get("needs_attention") else "")
                + f" · prompt {jc.get('prompt_doc_id','?')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_agentic_tasks: {e}"


def set_agentic_task_active(schedule_id: str, active: bool) -> str:
    """Turn an autonomous task on or off (off = it stops running but is kept)."""
    try:
        from apps.schedules.data import update_schedule, get_schedule
        if not get_schedule(schedule_id):
            return f"No task with id {schedule_id}."
        update_schedule(schedule_id, active=bool(active))
        return f"Task {schedule_id} is now {'active' if active else 'OFF'}."
    except Exception as e:
        return f"Error in set_agentic_task_active: {e}"


def run_agentic_task_now(schedule_id: str, run_by: str = "") -> str:
    """Run an autonomous task immediately (once), without waiting for its schedule."""
    try:
        from apps.schedules.data import get_schedule
        sch = get_schedule(schedule_id)
        if not sch or sch.get("linked_entity_id") != "agentic":
            return f"No agentic task with id {schedule_id}."
        from app_platform.jobs import submit_job
        job = submit_job(
            job_type="agentic",
            name=f"Manual run: {sch.get('title','agentic')}",
            created_by=(run_by or "skipper"),
            config=sch.get("job_config") or {},
        )
        return f"Running '{sch.get('title')}' now (job {job.get('id')})."
    except Exception as e:
        return f"Error in run_agentic_task_now: {e}"
