"""Tools for creating + managing routines (#109).

`create_routine` sets up the whole thing in one call: it writes the PROMPT
to a d-* document, then creates a public.schedules row whose job_config carries
the spec (prompt_doc_id, tool_categories, tier) and whose
linked_entity points at the `agentic` job type. When due, the schedule fires the
agentic job (see agentic.py). Edit a routine's prompt by editing its document (in
chat or the Documents app); manage the schedule with the list/toggle/run tools.
"""
import re
import logging

logger = logging.getLogger("apps.agentic.tools")

_VALID_RECURRENCE = {"daily", "weekly", "monthly", "yearly", "interval", "cron", "rrule"}

_ALL_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _normalize_recurrence(rtype: str, rule: dict | None):
    """A weekly cadence that covers every day IS daily. LLMs often express
    "every morning" as weekly with all 7 days checked; collapse that to a clean
    `daily` so the Schedules UI shows "Daily" instead of "Weekly" (all days)."""
    if rtype == "weekly" and rule:
        days = {str(d).strip().lower()[:3] for d in (rule.get("days") or [])}
        if _ALL_DAYS.issubset(days):
            return "daily", {"every": 1}
    return rtype, rule


def create_routine(
    name: str,
    prompt: str,
    created_by: str,
    tool_categories: str = "",
    recurrence_type: str = "daily",
    recurrence_rule: dict | None = None,
    time_of_day: str = "",
    tier: str = "smart",
) -> str:
    """Set up a ROUTINE — Skipper running a prompt on a schedule.

    Use when a household member asks Skipper to do something automatically /
    on a schedule going forward (e.g. "every morning, check my calendar and
    draft a summary", "each Friday, review the chore log and note who's behind").

    Args:
        name: Short human name for the routine (e.g. "Morning calendar summary").
        prompt: The full instructions Skipper should follow each time it runs —
            written as a routine for Skipper to execute. Be specific about what to
            produce (a document, updates, findings). This is saved as a document
            you can edit later.
        created_by: Who is setting it up (a person's name).
        tool_categories: Comma-separated tool categories the routine needs loaded to
            start (e.g. "app:goals,web,documents"). Skipper can request more at
            run time; `core` is always available. Leave empty for a
            prompt-only/thinking routine.
        recurrence_type: daily | weekly | monthly | yearly | interval (default daily).
        recurrence_rule: the schedule detail matching recurrence_type — e.g.
            weekly {"days": ["mon","thu"]}, monthly {"day": 15},
            yearly {"month": 6, "day": 1}, daily/interval {"every": 1}. Without
            it, weekly/monthly/etc. have no anchor day and won't fire predictably.
        time_of_day: Local HH:MM for when it runs (e.g. "07:00"). Optional.
        tier: "smart" (default) or "fast" model tier for the routine.

    Returns:
        Confirmation with the routine's schedule id and prompt-document id.
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
        rtype, recurrence_rule = _normalize_recurrence(rtype, recurrence_rule)

        # 1. Save the prompt as a document (editable later, in chat or the doc app).
        from apps.documents.tools import create_doc
        doc_result = create_doc(
            title=f"{name.strip()} — routine prompt",
            created_by=created_by.strip(),
            content=prompt.strip(),
            tags="routine",
        )
        m = re.search(r"d-[0-9a-f]+", doc_result)
        if not m:
            return f"Error: could not create the prompt document ({doc_result[:120]})"
        doc_id = m.group(0)

        # 2. Parse the initial tool categories.
        cats = [c.strip() for c in (tool_categories or "").split(",") if c.strip()]

        # 3. Create the schedule; its job_config IS the routine spec.
        from apps.schedules.data import create_schedule
        sch = create_schedule(
            title=name.strip(),
            created_by=created_by.strip(),
            # Assign to the creator so the routine is visible + manageable in their
            # Schedules app (the list filters by the logged-in user).
            assigned_to=created_by.strip(),
            category="agentic",
            recurrence_type=rtype,
            recurrence_rule=(recurrence_rule or None),
            time_of_day=(time_of_day.strip() or None),
            linked_entity_type="job",
            linked_entity_id="agentic",
            job_config={
                "prompt_doc_id": doc_id,
                "tool_categories": cats,
                "tier": (tier or "smart"),
            },
        )
        sid = sch.get("id", "?")
        when = f"{rtype}" + (f" at {time_of_day.strip()}" if time_of_day.strip() else "")
        return (
            f"Routine created: '{name.strip()}' ({sid}).\n"
            f"  Runs: {when}\n"
            f"  Tools: {', '.join(cats) if cats else 'core only (request more at run time)'}\n"
            f"  Prompt document: {doc_id} (edit it to change what the routine does)."
        )
    except Exception as e:
        return f"Error in create_routine: {e}"


def list_routines() -> str:
    """List the routines Skipper is set up to run."""
    try:
        from apps.schedules.data import list_schedules
        rows = [s for s in list_schedules(active_only=False, limit=500)
                if s.get("linked_entity_type") == "job" and s.get("linked_entity_id") == "agentic"]
        if not rows:
            return "No routines are set up."
        lines = [f"{len(rows)} routine(s):"]
        for s in rows:
            jc = s.get("job_config") or {}
            state = "active" if s.get("active") else "OFF"
            lines.append(
                f"  - {s.get('title','(untitled)')} ({s.get('id')}) — {state}, "
                f"{s.get('recurrence_type','?')}"
                + (f" @ {s.get('time_of_day')}" if s.get("time_of_day") else "")
                + f" · prompt {jc.get('prompt_doc_id','?')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_routines: {e}"


def show_routine(schedule_id: str) -> str:
    """Show a routine's full settings AND its current prompt text.

    Use to inspect what a routine actually does before changing it.
    Args:
        schedule_id: The routine's schedule id (from list_routines).
    """
    try:
        from apps.schedules.data import get_schedule
        sch = get_schedule(schedule_id)
        if not sch or sch.get("linked_entity_id") != "agentic":
            return f"No routine with id {schedule_id}."
        jc = sch.get("job_config") or {}
        doc_id = jc.get("prompt_doc_id", "")
        from apps.documents.data import get_document_content
        prompt = get_document_content(doc_id) if doc_id else ""
        cats = jc.get("tool_categories") or []
        return (
            f"Routine: {sch.get('title','(untitled)')} ({schedule_id})\n"
            f"  Runs: {sch.get('recurrence_type','?')}"
            + (f" @ {sch.get('time_of_day')}" if sch.get("time_of_day") else "")
            + f" · {'active' if sch.get('active') else 'OFF'}\n"
            f"  Tools: {', '.join(cats) if cats else 'core only'}\n"
            f"  Prompt document: {doc_id}\n"
            f"  ----- current prompt -----\n{prompt or '(empty)'}"
        )
    except Exception as e:
        return f"Error in show_routine: {e}"


def update_routine(
    schedule_id: str,
    prompt: str = "",
    tool_categories: str = "",
    recurrence_type: str = "",
    recurrence_rule: dict | None = None,
    time_of_day: str = "",
    tier: str = "",
) -> str:
    """Change an existing routine — its prompt and/or its schedule/tools.

    Only the fields you pass are changed; leave the rest empty to keep them.
    Args:
        schedule_id: The routine to change (from list_routines).
        prompt: New full prompt text (rewrites the routine's prompt document).
        tool_categories: New comma-separated initial tool categories.
        recurrence_type: New cadence (daily | weekly | monthly | yearly | interval).
        recurrence_rule: schedule detail for the new cadence (see create_routine).
        time_of_day: New local HH:MM run time.
        tier: "smart" or "fast".
    """
    try:
        from apps.schedules.data import get_schedule, update_schedule
        sch = get_schedule(schedule_id)
        if not sch or sch.get("linked_entity_id") != "agentic":
            return f"No routine with id {schedule_id}."
        jc = dict(sch.get("job_config") or {})
        changed = []

        if prompt.strip():
            doc_id = jc.get("prompt_doc_id", "")
            if not doc_id:
                return "Routine has no prompt document to update."
            from apps.documents.tools import update_doc
            update_doc(doc_id=doc_id, content=prompt.strip(), updated_by="skipper")
            changed.append("prompt")

        if tool_categories.strip():
            jc["tool_categories"] = [c.strip() for c in tool_categories.split(",") if c.strip()]
            changed.append("tools")
        if tier.strip():
            jc["tier"] = tier.strip()
            changed.append("tier")

        sched_kw = {}
        if recurrence_type.strip() or recurrence_rule:
            new_type = recurrence_type.strip().lower() or sch.get("recurrence_type", "daily")
            new_type, new_rule = _normalize_recurrence(new_type, recurrence_rule)
            if recurrence_type.strip():
                sched_kw["recurrence_type"] = new_type
            elif new_type != sch.get("recurrence_type"):
                # normalization changed the cadence even though the caller only
                # passed a rule (e.g. weekly-all-days -> daily)
                sched_kw["recurrence_type"] = new_type
            if new_rule:
                sched_kw["recurrence_rule"] = new_rule
            changed.append("cadence")
        if time_of_day.strip():
            sched_kw["time_of_day"] = time_of_day.strip()
            changed.append("time")
        # persist job_config if any spec field changed
        if any(k in changed for k in ("tools", "tier")):
            sched_kw["job_config"] = jc

        if sched_kw:
            update_schedule(schedule_id, **sched_kw)

        if not changed:
            return "Nothing to change — pass a prompt or a setting to update."
        return f"Updated {sch.get('title', schedule_id)}: {', '.join(changed)}."
    except Exception as e:
        return f"Error in update_routine: {e}"


def set_routine_active(schedule_id: str, active: bool) -> str:
    """Turn an routine on or off (off = it stops running but is kept)."""
    try:
        from apps.schedules.data import update_schedule, get_schedule
        if not get_schedule(schedule_id):
            return f"No routine with id {schedule_id}."
        update_schedule(schedule_id, active=bool(active))
        return f"Routine {schedule_id} is now {'active' if active else 'OFF'}."
    except Exception as e:
        return f"Error in set_routine_active: {e}"


def run_routine_now(schedule_id: str, run_by: str = "") -> str:
    """Run an routine immediately (once), without waiting for its schedule."""
    try:
        from apps.schedules.data import get_schedule
        sch = get_schedule(schedule_id)
        if not sch or sch.get("linked_entity_id") != "agentic":
            return f"No routine with id {schedule_id}."
        from app_platform.jobs import submit_job
        job = submit_job(
            job_type="agentic",
            name=f"Manual run: {sch.get('title','agentic')}",
            created_by=(run_by or "skipper"),
            config=sch.get("job_config") or {},
        )
        return f"Running '{sch.get('title')}' now (job {job.get('id')})."
    except Exception as e:
        return f"Error in run_routine_now: {e}"
