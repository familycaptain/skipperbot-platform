"""
Evolve Domain Module
====================
Skipper's self-improvement engine — the most cross-cutting thinking domain.

Unlike other domain handlers that call agent_loop.run() once per cycle,
Evolve manages a **persistent job tree** of hundreds of focused LLM calls.
The handler itself is a cycle manager: it creates jobs, monitors progress,
and advances phases. The actual LLM work happens in evolve_unit job handlers
executed by the job dispatcher.

Architecture:
  - Cycle job (evolve_cycle) → Phase jobs (evolve_phase) → Unit jobs (evolve_unit)
  - All state persisted to Postgres via the job queue
  - Survives server crashes and restarts — resumes from where it left off
  - Budget-aware: pauses if token spend is too high

See specs/EVOLVE.md for the full specification.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, date, timedelta

from config import logger, SMART_MODEL
from app_platform.time import get_timezone

PLATFORM_REGISTRY_DIR = os.path.join(os.path.dirname(__file__), "docs", "platform")


def _load_platform_registry(files: list[str] | None = None) -> dict:
    """Load platform registry YAML files as raw text for LLM context.

    Args:
        files: Specific filenames to load (e.g. ["apps.yaml", "integrations.yaml"]).
               If None, loads all .yaml files in docs/platform/.
    Returns:
        Dict of filename → file contents (as string).
    """
    registry = {}
    if not os.path.isdir(PLATFORM_REGISTRY_DIR):
        return registry
    targets = files or [f for f in os.listdir(PLATFORM_REGISTRY_DIR) if f.endswith(".yaml")]
    for fname in sorted(targets):
        path = os.path.join(PLATFORM_REGISTRY_DIR, fname)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    registry[fname] = fh.read()
            except Exception:
                pass
    return registry


# How often the handler checks on an active cycle (seconds)
MONITOR_INTERVAL = 15

# Max concurrent evolve_unit jobs (set in job handler registration)
EVOLVE_CONCURRENCY = 5

# Budget ceiling: pause cycle if daily usage exceeds this percentage
BUDGET_PAUSE_PCT = 0.85

# Cycle type registry — maps cycle_type to its ordered phase list
CYCLE_PHASES = {
    "deep": [
        ("phase_0_feedback",        "Feedback Check"),
        ("phase_1_vision",          "Vision & Ambition"),
        ("phase_2_self_assessment", "Self-Assessment"),
        ("phase_3_gap_analysis",    "Gap Analysis"),
        ("phase_4_planning",        "Planning"),
        ("phase_5_propose",         "Propose"),
    ],
    "feedback": [
        ("phase_0_feedback", "Feedback Check"),
        ("phase_1_act",      "Act on Approved"),
    ],
    "assessment": [
        ("phase_0_feedback",        "Feedback Check"),
        ("phase_2_self_assessment", "Self-Assessment"),
        ("phase_3_gap_analysis",    "Gap Analysis"),
    ],
    "planning": [
        ("phase_0_feedback",  "Feedback Check"),
        ("phase_4_planning",  "Planning"),
        ("phase_5_propose",   "Propose"),
    ],
    "vision": [
        ("phase_0_feedback", "Feedback Check"),
        ("phase_1_vision",   "Vision & Ambition"),
    ],
    # Single-phase cycle types — run one phase standalone
    "solo_vision": [
        ("phase_1_vision",          "Vision & Ambition"),
    ],
    "solo_assessment": [
        ("phase_2_self_assessment", "Self-Assessment"),
    ],
    "solo_gap": [
        ("phase_3_gap_analysis",    "Gap Analysis"),
    ],
    "solo_planning": [
        ("phase_4_planning",        "Planning"),
    ],
    "solo_propose": [
        ("phase_5_propose",         "Propose"),
    ],
    "solo_reconcile": [
        ("phase_1_act",             "Act on Approved"),
    ],
}

# Convenience aliases for backward compat
DEEP_PHASES = CYCLE_PHASES["deep"]
FEEDBACK_PHASES = CYCLE_PHASES["feedback"]


# ---------------------------------------------------------------------------
# Domain handler entry point
# ---------------------------------------------------------------------------

async def evolve_domain_handler(domain: dict, budget_status: dict) -> dict:
    """
    Evolve thinking domain handler — called by thinking_scheduler on cadence.

    The handler does NOT run LLM calls directly. It manages the persistent
    job tree and lets the job dispatcher execute individual work units.

    Declared prerequisites: the Issues app. Evolve reads open issues during
    Phase 0 feedback synthesis; running without it is a degraded cycle, so
    we refuse to start instead of silently producing an incomplete result.
    """
    from app_platform.loader import require_apps
    require_apps("issues")

    # Check for an active (in-progress) cycle
    active_cycle = await _find_active_cycle()

    if active_cycle:
        return await _resume_cycle(active_cycle, budget_status)
    else:
        # Determine if we should start a new cycle
        cycle_type = _determine_cycle_type(domain)
        if not cycle_type:
            return _skip("No cycle needed right now")
        return await _start_cycle(cycle_type, budget_status)


# ---------------------------------------------------------------------------
# Cycle type determination
# ---------------------------------------------------------------------------

def _determine_cycle_type(domain: dict) -> str | None:
    """Decide whether to start a deep or feedback cycle (or neither).

    Returns 'deep', 'feedback', or None.
    """
    # DISABLED: Automatic cycles off — use manual trigger only (POST /api/apps/evolve/trigger)
    return None

    # now = datetime.now(get_timezone())
    # cadence = domain.get("cadence") or {}
    #
    # deep_day = cadence.get("deep_cycle_day", "sunday")
    # deep_hour = cadence.get("deep_cycle_hour", 10)
    #
    # # TEMP: Deep cycle runs daily (any day) for debugging — revert to weekly later
    # # Check if we already ran a deep cycle today
    # last_deep = _get_last_cycle_date("deep")
    # if not last_deep or last_deep < now.date():
    #     return "deep"
    #
    # # Otherwise, check if a daily feedback cycle is due
    # last_feedback = _get_last_cycle_date("feedback")
    # if not last_feedback or last_feedback < now.date():
    #     return "feedback"
    #
    # return None


def _get_last_cycle_date(cycle_type: str) -> date | None:
    """Get the date of the last completed or running cycle of this type."""
    from data_layer.db import fetch_one
    row = fetch_one("""
        SELECT created_at FROM jobs
        WHERE job_type = 'evolve_cycle'
          AND config->>'cycle_type' = %s
          AND status IN ('running', 'completed')
        ORDER BY created_at DESC LIMIT 1
    """, (cycle_type,))
    if row and row.get("created_at"):
        dt = row["created_at"]
        if hasattr(dt, "astimezone"):
            return dt.astimezone(get_timezone()).date()
    return None


# ---------------------------------------------------------------------------
# Start a new cycle
# ---------------------------------------------------------------------------

async def _start_cycle(cycle_type: str, budget_status: dict) -> dict:
    """Create the full job tree for a new Evolve cycle."""
    from app_platform.jobs import submit_job

    cycle_job = submit_job(
        job_type="evolve_cycle",
        name=f"Evolve {cycle_type} cycle — {date.today()}",
        config={
            "cycle_type": cycle_type,
            "budget_snapshot": budget_status,
        },
        created_by="skipper",
    )
    cycle_id = cycle_job["id"]
    logger.info("EVOLVE: Starting %s cycle: %s", cycle_type, cycle_id)

    phases = CYCLE_PHASES.get(cycle_type, FEEDBACK_PHASES)

    for i, (phase_key, phase_name) in enumerate(phases):
        submit_job(
            job_type="evolve_phase",
            name=f"Phase {i}: {phase_name}",
            config={"phase_key": phase_key, "phase_index": i},
            parent_job_id=cycle_id,
            created_by="skipper",
        )

    # Activate the first phase
    await _activate_next_phase(cycle_id)

    return {
        "trigger": "timer",
        "input_summary": f"Started {cycle_type} Evolve cycle: {cycle_id}",
        "reasoning": f"Created job tree with {len(phases)} phases",
        "actions_taken": [{"action": "start_cycle", "cycle_id": cycle_id, "type": cycle_type}],
        "memories_extracted": [],
        "model_used": "skip",
        "tokens_used": 0,
        "next_check_seconds": 30,
    }


# ---------------------------------------------------------------------------
# Resume an active cycle
# ---------------------------------------------------------------------------

async def _resume_cycle(cycle_job: dict, budget_status: dict) -> dict:
    """Monitor and advance an in-progress cycle."""
    cycle_id = cycle_job["id"]

    # Budget check
    if budget_status.get("usage_pct", 0) > BUDGET_PAUSE_PCT:
        logger.info("EVOLVE: Budget > %.0f%%, pausing cycle %s",
                     BUDGET_PAUSE_PCT * 100, cycle_id)
        return _skip(f"Budget > {int(BUDGET_PAUSE_PCT*100)}%, pausing cycle",
                      next_check=600)

    # Find the currently running phase
    active_phase = _get_running_phase(cycle_id)

    if not active_phase:
        # No running phase — either all done or need to activate next
        next_queued = _get_next_queued_phase(cycle_id)
        if not next_queued:
            # All phases done — complete the cycle
            await _complete_cycle(cycle_id)
            return {
                "trigger": "timer",
                "input_summary": f"Evolve cycle {cycle_id} completed",
                "reasoning": "All phases finished",
                "actions_taken": [{"action": "complete_cycle", "cycle_id": cycle_id}],
                "memories_extracted": [],
                "model_used": "skip",
                "tokens_used": 0,
                "next_check_seconds": 300,
            }
        else:
            # Activate the next phase
            await _activate_next_phase(cycle_id)
            return _skip(f"Activated next phase in cycle {cycle_id}", next_check=30)

    # Active phase exists — check unit progress
    phase_id = active_phase["id"]
    units = _get_child_jobs(phase_id)

    if not units:
        # Phase has no units yet (shouldn't happen, but handle gracefully)
        logger.warning("EVOLVE: Phase %s has no units", phase_id)
        return _skip("Phase has no units — waiting", next_check=30)

    completed = [u for u in units if u["status"] == "completed"]
    failed = [u for u in units if u["status"] == "failed"]
    running = [u for u in units if u["status"] == "running"]
    queued = [u for u in units if u["status"] == "queued"]

    # Re-queue interrupted units (were "running" when server died)
    for unit in running:
        if _worker_is_dead(unit):
            logger.info("EVOLVE: Re-queuing interrupted unit %s", unit["id"])
            _requeue_job(unit["id"])

    total = len(units)
    done = len(completed) + len(failed)

    # Update phase progress
    from app_platform.jobs import update_progress
    pct = int(done / total * 100) if total > 0 else 0
    update_progress(phase_id, pct, f"{done}/{total} units complete")

    # Check if phase is done
    if done >= total:
        # All units finished — check if synthesis succeeded
        synthesis_units = [u for u in units
                           if u.get("config", {}).get("is_synthesis")]
        if synthesis_units and all(s["status"] == "completed" for s in synthesis_units):
            # Phase complete
            _complete_phase(phase_id)
            logger.info("EVOLVE: Phase %s complete (%d/%d units)",
                         active_phase["name"], done, total)
            return _skip(f"Phase complete: {active_phase['name']}", next_check=10)
        elif synthesis_units and any(s["status"] == "failed" for s in synthesis_units):
            # Synthesis failed — mark phase as failed but continue cycle
            from app_platform.jobs import fail_job
            fail_job(phase_id, "Synthesis unit failed")
            logger.error("EVOLVE: Phase %s synthesis failed — advancing cycle",
                         active_phase["name"])
            return _skip(f"Phase failed: {active_phase['name']} — advancing",
                         next_check=10)
        elif not synthesis_units:
            # No synthesis unit — phase done
            _complete_phase(phase_id)
            return _skip(f"Phase complete: {active_phase['name']}", next_check=10)

    return _skip(
        f"Cycle {cycle_id}: {active_phase['name']} — {done}/{total} units",
        next_check=MONITOR_INTERVAL,
    )


# ---------------------------------------------------------------------------
# Phase activation — enumerate work units
# ---------------------------------------------------------------------------

async def _activate_next_phase(cycle_id: str):
    """Find the next queued phase, enumerate units, submit them as jobs."""
    from app_platform.jobs import submit_job
    from app_platform.jobs import update_progress

    phase_job = _get_next_queued_phase(cycle_id)
    if not phase_job:
        return  # All phases done

    phase_id = phase_job["id"]
    phase_key = phase_job["config"]["phase_key"]

    logger.info("EVOLVE: Activating phase %s (%s)", phase_key, phase_id)

    # Mark phase as running
    _set_job_running(phase_id)
    update_progress(phase_id, 0, "Enumerating work units...")

    # Enumerate work units for this phase
    units = await _enumerate_units(phase_key, cycle_id)

    if not units:
        # Empty phase — mark complete immediately
        logger.info("EVOLVE: Phase %s has no work — marking complete", phase_key)
        _complete_phase(phase_id)
        return

    # Submit each unit as a child job
    for unit in units:
        submit_job(
            job_type="evolve_unit",
            name=unit["name"],
            config={
                "phase_key": phase_key,
                "prompt_template": unit["prompt_template"],
                "context": unit["context"],
                "tools": unit.get("tools", []),
                "is_synthesis": unit.get("is_synthesis", False),
                "cycle_id": cycle_id,
            },
            parent_job_id=phase_id,
            created_by="skipper",
        )

    update_progress(phase_id, 0, f"0/{len(units)} units complete")
    logger.info("EVOLVE: Phase %s activated with %d units", phase_key, len(units))


async def _enumerate_units(phase_key: str, cycle_id: str) -> list[dict]:
    """Enumerate work units for a phase. Each unit becomes one evolve_unit job.

    Returns list of dicts with: name, prompt_template, context, tools, is_synthesis
    """
    # Load goal context from working memory (if available from previous phases)
    wm = _load_working_memory()

    # Load evolve items created by earlier phases in this same cycle
    cycle_items = await _load_cycle_items(cycle_id)
    if cycle_items:
        wm["_cycle_items"] = cycle_items
        logger.info("EVOLVE: Loaded %d existing items from earlier phases in this cycle",
                     len(cycle_items))

    if phase_key == "phase_0_feedback":
        return await _enumerate_feedback_units(wm)
    elif phase_key == "phase_1_vision":
        return await _enumerate_vision_units(wm)
    elif phase_key == "phase_2_self_assessment":
        return await _enumerate_self_assessment_units(wm)
    elif phase_key == "phase_3_gap_analysis":
        return await _enumerate_gap_analysis_units(wm)
    elif phase_key == "phase_4_planning":
        return await _enumerate_planning_units(wm)
    elif phase_key == "phase_5_propose":
        return await _enumerate_propose_units(wm)
    elif phase_key == "phase_1_act":
        return await _enumerate_act_units(wm)
    else:
        logger.warning("EVOLVE: Unknown phase key: %s", phase_key)
        return []


async def _load_cycle_items(cycle_job_id: str) -> list[dict]:
    """Load evolve items for context: current cycle items + all active items from prior cycles."""
    try:
        from data_layer.db import fetch_all
        # Current cycle items (from earlier phases in this run)
        current = await asyncio.to_thread(
            fetch_all,
            "SELECT id, type, title, body, impact, phase_origin, parent_id, category, "
            "'current' AS source "
            "FROM evolution_items WHERE cycle_job_id = %s "
            "ORDER BY created_at",
            (cycle_job_id,),
        )
        current_ids = {r["id"] for r in current}

        # All active items from any cycle (for cross-cycle hierarchy awareness)
        prior = await asyncio.to_thread(
            fetch_all,
            "SELECT id, type, title, body, impact, phase_origin, parent_id, category, "
            "'prior' AS source "
            "FROM evolution_items "
            "WHERE status NOT IN ('dismissed', 'rejected', 'completed') "
            "ORDER BY created_at DESC LIMIT 150",
        )
        # Merge: current cycle first, then prior items not already in current
        all_items = [dict(r) for r in current]
        for r in prior:
            if r["id"] not in current_ids:
                all_items.append(dict(r))

        return all_items
    except Exception as e:
        logger.warning("EVOLVE: Could not load cycle items: %s", e)
        return []


def _format_cycle_items_context(wm: dict) -> str:
    """Format evolve items into a compact context string for LLM injection.

    Includes both current-cycle items from earlier phases AND active items
    from prior cycles, so the LLM can build cross-cycle hierarchy links.
    """
    items = wm.get("_cycle_items", [])
    if not items:
        return ""

    current = [it for it in items if it.get("source") == "current"]
    prior = [it for it in items if it.get("source") != "current"]

    def _fmt(it):
        origin = it.get("phase_origin", "?")
        parent = f" → parent:{it['parent_id']}" if it.get("parent_id") else ""
        return f"  [{it['id']}] ({origin}/{it.get('type','?')}) {it.get('title','')}{parent}"

    parts = []
    if current:
        parts.append("### Items Created Earlier in This Cycle")
        parts.extend(_fmt(it) for it in current[:30])
    if prior:
        parts.append("### Active Items from Prior Cycles")
        parts.extend(_fmt(it) for it in prior[:50])

    return (
        "\n## Existing Evolve Items\n"
        "Reference these by ID (parent_item_id) if your findings relate to them:\n"
        + "\n".join(parts)
    )


def _items_by_origin(wm: dict, *origins: str) -> list[dict]:
    """Extract evolve items matching given phase_origin values from loaded cycle items.

    This is how phases discover findings from other phases without depending
    on working memory. Enables any phase to run standalone — it reads the
    persistent evolve items as its primary input.
    """
    items = wm.get("_cycle_items", [])
    return [it for it in items if it.get("phase_origin") in origins]


# ---------------------------------------------------------------------------
# Phase unit enumerators (one per phase)
# ---------------------------------------------------------------------------

async def _enumerate_feedback_units(wm: dict) -> list[dict]:
    """Phase 0: 1 unit per evolution item with unread threads + issues + synthesis."""
    from data_layer.evolution import list_items_with_unread_threads

    units = []

    # Items with unread feedback from Alice
    items = await asyncio.to_thread(list_items_with_unread_threads)
    for item in items:
        units.append({
            "name": f"Feedback: {item['title'][:60]}",
            "prompt_template": "phase_0_feedback",
            "context": {"item": item},
        })

    # Load open/recent issues from the app_issues schema (Issues app package).
    # The Issues app is a declared prerequisite of evolve — see
    # evolve_domain_handler's require_apps() call. A failure here is a real
    # bug (DB error, schema mismatch), not a missing-app situation, so we
    # let it propagate instead of swallowing it as a warning.
    from apps.issues.store import list_issues
    open_issues = await asyncio.to_thread(list_issues, status="open")
    in_progress_issues = await asyncio.to_thread(list_issues, status="in_progress")
    all_issues = open_issues + in_progress_issues
    if all_issues:
        units.append({
            "name": f"Review {len(all_issues)} open issues",
            "prompt_template": "phase_0_issues",
            "context": {
                "task": "review_issues",
                "issues": all_issues,
                "issue_count": len(all_issues),
            },
        })
        logger.info("EVOLVE: Phase 0 loaded %d open/in-progress issues", len(all_issues))
    else:
        logger.info("EVOLVE: Phase 0 — no open issues found")

    # Synthesis
    if units:
        units.append({
            "name": "Phase 0 synthesis — consolidate feedback",
            "prompt_template": "synthesis",
            "context": {"phase": "feedback", "phase_key": "phase_0_feedback"},
            "is_synthesis": True,
        })

    return units


async def _enumerate_vision_units(wm: dict) -> list[dict]:
    """Phase 1: 1 unit per goal + exploration calls + synthesis."""
    units = []

    # Build a landscape of what Skipper is already working on:
    # goals → projects (no tasks — too granular for high-level planning)
    landscape = []
    try:
        from apps.goals.data import list_entities, get_projects_for_goal
        goals = await asyncio.to_thread(list_entities, "g-")
        for goal in goals:
            projects = await asyncio.to_thread(get_projects_for_goal, goal["id"])
            goal_summary = {
                "id": goal["id"],
                "name": goal.get("name", ""),
                "status": goal.get("status", ""),
                "owners": goal.get("owners", []),
                "target_date": goal.get("target_date", ""),
                "projects": [
                    {
                        "id": p["id"],
                        "name": p.get("name", ""),
                        "status": p.get("status", ""),
                        "owners": p.get("owners", []),
                        "task_count": len(p.get("tasks", [])),
                    }
                    for p in projects
                ],
            }
            landscape.append(goal_summary)
    except Exception as e:
        logger.warning("EVOLVE: Could not load goals/projects: %s", e)
        goals = []

    # Load existing evolve items so the LLM knows what's already tracked
    existing_items = []
    rejected_items = []
    try:
        from data_layer.evolution import list_items, get_thread
        # Active items
        items = await asyncio.to_thread(list_items, include_completed=False)
        for it in items:
            entry = {"id": it["id"], "title": it["title"], "status": it["status"],
                     "category": it.get("category", ""), "impact": it.get("impact", "")}
            # Include recent thread messages (user feedback) — last 3 per item
            try:
                thread = await asyncio.to_thread(get_thread, it["id"])
                user_msgs = [m for m in thread if m.get("author") != "skipper"]
                if user_msgs:
                    entry["user_feedback"] = [
                        {"author": m["author"], "body": m["body"][:300]}
                        for m in user_msgs[-3:]
                    ]
            except Exception:
                pass
            existing_items.append(entry)

        # Rejected/dismissed items — so the LLM knows NOT to recreate them
        rejected = await asyncio.to_thread(list_items, include_completed=True, limit=200)
        for it in rejected:
            if it["status"] in ("rejected", "dismissed"):
                entry = {"id": it["id"], "title": it["title"], "status": it["status"]}
                try:
                    thread = await asyncio.to_thread(get_thread, it["id"])
                    user_msgs = [m for m in thread if m.get("author") != "skipper"]
                    if user_msgs:
                        entry["rejection_reason"] = user_msgs[-1]["body"][:300]
                except Exception:
                    pass
                rejected_items.append(entry)
    except Exception as e:
        logger.warning("EVOLVE: Could not load existing evolve items: %s", e)

    # Load platform registry so the LLM knows Skipper's current capabilities
    platform_registry = await asyncio.to_thread(
        _load_platform_registry, ["apps.yaml", "integrations.yaml"])

    shared_context = {
        "feedback_summary": wm.get("feedback", {}),
        "goal_landscape": landscape,
        "existing_evolve_items": existing_items,
        "rejected_items": rejected_items,
    }
    # Flatten registry files as raw text keys (rendered as markdown sections)
    for fname, content in platform_registry.items():
        key = f"PLATFORM_REGISTRY_{fname.replace('.yaml', '').upper()}"
        shared_context[key] = content

    logger.info("EVOLVE: Phase 1 landscape: %d goals, %d projects, %d evolve items, %d rejected, %d registry files",
                len(landscape),
                sum(len(g["projects"]) for g in landscape),
                len(existing_items),
                len(rejected_items),
                len(platform_registry))

    # Evaluate each existing high-level goal
    for goal_summary in landscape:
        units.append({
            "name": f"Goal eval: {goal_summary.get('name', goal_summary['id'])[:60]}",
            "prompt_template": "phase_1_goal_eval",
            "context": {"goal": goal_summary, **shared_context},
        })

    # Exploration calls
    explorations = [
        "family_pain_points",
        "monetary_opportunities",
        "evolve_process_improvement",
    ]
    for topic in explorations:
        units.append({
            "name": f"Explore: {topic}",
            "prompt_template": "phase_1_explore",
            "context": {"topic": topic, **shared_context},
            "tools": ["internet_search", "curl_request"],
        })

    # Synthesis
    if units:
        units.append({
            "name": "Phase 1 synthesis — rank goals and ambitions",
            "prompt_template": "synthesis",
            "context": {"phase": "vision", "phase_key": "phase_1_vision"},
            "is_synthesis": True,
        })

    return units


async def _enumerate_self_assessment_units(wm: dict) -> list[dict]:
    """Phase 2: 1 unit per tool category, domain, app + synthesis.

    Can run standalone — if working memory has no vision data, falls back to
    vision-origin evolve items from prior cycles.
    """
    import glob
    units = []
    goals_ctx = wm.get("vision", {})
    if not goals_ctx:
        vision_items = _items_by_origin(wm, "vision")
        if vision_items:
            goals_ctx = {"findings": [
                {"title": it["title"], "summary": it.get("body", ""),
                 "impact": it.get("impact"), "id": it["id"]}
                for it in vision_items
            ]}
            logger.info("EVOLVE: Phase 2 standalone — using %d vision evolve items as goals context",
                         len(vision_items))

    # Load platform registry for capability awareness
    platform_reg = await asyncio.to_thread(
        _load_platform_registry, ["apps.yaml", "tools.yaml"])
    reg_ctx = {}
    for fname, content in platform_reg.items():
        reg_ctx[f"PLATFORM_REGISTRY_{fname.replace('.yaml', '').upper()}"] = content

    # Tool categories from tool_routes.json
    try:
        with open("tool_routes.json") as f:
            routes = json.load(f)
        categories = set()
        for tool_info in routes.values():
            cat = tool_info.get("category", "uncategorized")
            categories.add(cat)
        for cat in sorted(categories):
            units.append({
                "name": f"Tool audit: {cat}",
                "prompt_template": "phase_2_tool_audit",
                "context": {"category": cat, "goals": goals_ctx, **reg_ctx},
            })
    except Exception as e:
        logger.warning("EVOLVE: Could not load tool_routes.json: %s", e)

    # Apps
    apps_dir = "apps"
    if os.path.isdir(apps_dir):
        for app_name in sorted(os.listdir(apps_dir)):
            app_path = os.path.join(apps_dir, app_name)
            if os.path.isdir(app_path) and not app_name.startswith("_"):
                units.append({
                    "name": f"App audit: {app_name}",
                    "prompt_template": "phase_2_app_audit",
                    "context": {"app_name": app_name, "goals": goals_ctx, **reg_ctx},
                })

    # Thinking domains
    try:
        from data_layer.thinking_domains import list_domains
        domains = await asyncio.to_thread(list_domains, enabled_only=False)
        for d in domains:
            if d["name"] != "evolve":  # don't audit ourselves (meta-evolution is separate)
                units.append({
                    "name": f"Domain audit: {d['name']}",
                    "prompt_template": "phase_2_tool_audit",
                    "context": {"domain": d, "goals": goals_ctx, **reg_ctx},
                })
    except Exception as e:
        logger.warning("EVOLVE: Could not load thinking domains: %s", e)

    # Synthesis
    if units:
        units.append({
            "name": "Phase 2 synthesis — State of Skipper",
            "prompt_template": "synthesis",
            "context": {"phase": "self_assessment", "phase_key": "phase_2_self_assessment"},
            "is_synthesis": True,
        })

    return units


async def _enumerate_gap_analysis_units(wm: dict) -> list[dict]:
    """Phase 3: The biggest phase. 1 unit per spec, tool file, app, data layer file.

    Can run standalone — if working memory has no vision data, falls back to
    vision-origin evolve items from prior cycles.
    """
    import glob
    units = []
    goals_ctx = wm.get("vision", {})
    if not goals_ctx:
        # Standalone mode: build goals context from vision-origin evolve items
        vision_items = _items_by_origin(wm, "vision")
        if vision_items:
            goals_ctx = {"findings": [
                {"title": it["title"], "summary": it.get("body", ""),
                 "impact": it.get("impact"), "id": it["id"]}
                for it in vision_items
            ]}
            logger.info("EVOLVE: Phase 3 standalone — using %d vision evolve items as goals context",
                         len(vision_items))
    state_ctx = wm.get("self_assessment", {})
    cycle_items_ctx = _format_cycle_items_context(wm)

    # Spec files
    for spec_file in sorted(glob.glob("specs/*.md")):
        units.append({
            "name": f"Spec gap: {os.path.basename(spec_file)}",
            "prompt_template": "phase_3_spec_gap",
            "context": {"file": spec_file, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Tool files
    for tool_file in sorted(glob.glob("tools/*.py")):
        basename = os.path.basename(tool_file)
        if basename.startswith("__"):
            continue
        units.append({
            "name": f"Tool gap: {basename}",
            "prompt_template": "phase_3_tool_gap",
            "context": {"file": tool_file, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Data layer files
    for dl_file in sorted(glob.glob("data_layer/*.py")):
        basename = os.path.basename(dl_file)
        if basename.startswith("__"):
            continue
        units.append({
            "name": f"Data layer: {basename}",
            "prompt_template": "phase_3_tool_gap",
            "context": {"file": dl_file, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Prompt guides
    for guide in sorted(glob.glob("prompts/guides/*.md")):
        units.append({
            "name": f"Guide: {os.path.basename(guide)}",
            "prompt_template": "phase_3_tool_gap",
            "context": {"file": guide, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Platform registry reconciliation — verify docs/platform/*.yaml against actual code
    registry_files = {
        "apps.yaml": {
            "verify_against": [
                "tool_routes.json",
                "apps/*/tools.py",
                "apps/*/data.py",
                "web/src/apps/*.jsx",
            ],
            "description": "Verify app entries: tool counts, capability claims, UI components, data layer refs",
        },
        "tools.yaml": {
            "verify_against": [
                "tool_routes.json",
                "apps/*/tools.py",
                "tools/*.py",
            ],
            "description": "Verify every tool name exists in code, no missing tools, no phantom tools",
        },
        "domains.yaml": {
            "verify_against": [
                "domain_modules.py",
                "domain_pm.py",
                "domain_evolve.py",
                "chat_domain.py",
                "domain_goal.py",
                "apps/investment/risk_domain.py",
                "thinking_scheduler.py",
            ],
            "description": "Verify domain registrations, handler files, behavior descriptions",
        },
        "integrations.yaml": {
            "verify_against": [
                ".env.example",
                "discord_bot.py",
                "trello_client.py",
                "gmail_client.py",
                "fcm_sender.py",
                "tastytrade/",
                "mcp_client.py",
            ],
            "description": "Verify integration files exist, config vars match .env.example",
        },
        "data_model.yaml": {
            "verify_against": [
                "migrations/*.sql",
                "apps/*/migrations/*.sql",
            ],
            "description": "Verify every table and column against actual CREATE TABLE statements",
        },
        "infrastructure.yaml": {
            "verify_against": [
                "agent.py",
                "agent_loop.py",
                "job_dispatcher.py",
                "job_handlers.py",
                "thinking_scheduler.py",
                "notification_delivery.py",
                "config.py",
            ],
            "description": "Verify component descriptions, handler types, scheduler behavior",
        },
    }
    for yaml_file, meta in registry_files.items():
        yaml_path = os.path.join("docs", "platform", yaml_file)
        if os.path.isfile(yaml_path):
            units.append({
                "name": f"Registry reconcile: {yaml_file}",
                "prompt_template": "phase_3_registry_reconcile",
                "context": {
                    "registry_file": yaml_path,
                    "verify_against": meta["verify_against"],
                    "verification_focus": meta["description"],
                    "goals": goals_ctx,
                    "existing_items": cycle_items_ctx,
                },
            })

    # Issues from Phase 0
    issues = wm.get("feedback", {}).get("new_issues", [])
    for issue in issues[:20]:  # cap at 20
        units.append({
            "name": f"Issue: {issue.get('title', issue.get('id', '?'))[:60]}",
            "prompt_template": "phase_3_spec_gap",
            "context": {"issue": issue, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Synthesis (may need multiple calls if findings are huge)
    if units:
        units.append({
            "name": "Phase 3 synthesis — prioritized gap list",
            "prompt_template": "synthesis",
            "context": {"phase": "gap_analysis", "phase_key": "phase_3_gap_analysis"},
            "is_synthesis": True,
        })

    return units


async def _enumerate_planning_units(wm: dict) -> list[dict]:
    """Phase 4: 1 unit per approved item, redirected item, and top findings.

    Can run standalone — if working memory has no gap_analysis data, falls
    back to gap-origin evolve items. Vision context also falls back to
    vision-origin evolve items.
    """
    units = []
    feedback = wm.get("feedback", {})
    cycle_items_ctx = _format_cycle_items_context(wm)

    # Build goals context — working memory first, then evolve items
    goals_ctx = wm.get("vision", {})
    if not goals_ctx:
        vision_items = _items_by_origin(wm, "vision")
        if vision_items:
            goals_ctx = {"findings": [
                {"title": it["title"], "summary": it.get("body", ""),
                 "impact": it.get("impact"), "id": it["id"]}
                for it in vision_items
            ]}
            logger.info("EVOLVE: Phase 4 standalone — using %d vision evolve items",
                         len(vision_items))

    # Build findings — working memory first, then gap/assessment evolve items
    findings = wm.get("gap_analysis", {}).get("findings", [])
    if not findings:
        gap_items = _items_by_origin(wm, "gap", "assessment")
        if gap_items:
            findings = [
                {"title": it["title"], "summary": it.get("body", ""),
                 "impact": it.get("impact"), "category": it.get("category"),
                 "id": it["id"], "phase_origin": it.get("phase_origin")}
                for it in gap_items
            ]
            logger.info("EVOLVE: Phase 4 standalone — using %d gap/assessment evolve items as findings",
                         len(findings))

    # Approved items → detailed implementation plans
    for item in feedback.get("approved_items", []):
        units.append({
            "name": f"Plan: {item.get('title', item.get('id', '?'))[:60]}",
            "prompt_template": "phase_4_plan",
            "context": {"item": item, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Redirected items → revised plans
    for item in feedback.get("redirected_items", []):
        units.append({
            "name": f"Revise: {item.get('title', item.get('id', '?'))[:60]}",
            "prompt_template": "phase_4_plan",
            "context": {"item": item, "redirect": True, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Top-priority findings → new proposals
    top_findings = sorted(findings,
                          key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(
                              f.get("impact", "low"), 2))[:10]
    for finding in top_findings:
        units.append({
            "name": f"Propose: {finding.get('title', '?')[:60]}",
            "prompt_template": "phase_4_plan",
            "context": {"finding": finding, "goals": goals_ctx, "existing_items": cycle_items_ctx},
        })

    # Synthesis
    if units:
        units.append({
            "name": "Phase 4 synthesis — final proposals and plans",
            "prompt_template": "synthesis",
            "context": {"phase": "planning", "phase_key": "phase_4_planning"},
            "is_synthesis": True,
        })

    return units


async def _enumerate_propose_units(wm: dict) -> list[dict]:
    """Phase 5: Create/update evolution items, link to goals, notify Alice.

    Can run standalone — if working memory has no plans, falls back to
    planning-origin evolve items from prior cycles.
    """
    units = []

    # Extract plans from planning working memory.
    # Structure: {"findings": [{"findings": [{plan}, {plan}]}]}
    # Also check legacy key "proposals" for backward compat.
    planning_wm = wm.get("planning", {})
    plans = planning_wm.get("proposals", [])
    if not plans:
        # Extract from nested findings structure
        for group in planning_wm.get("findings", []):
            if isinstance(group, dict):
                plans.extend(group.get("findings", []))

    # Standalone fallback: use planning-origin evolve items
    if not plans:
        planning_items = _items_by_origin(wm, "planning")
        if planning_items:
            plans = [
                {"title": it["title"], "summary": it.get("body", ""),
                 "impact": it.get("impact"), "category": it.get("category"),
                 "id": it["id"], "phase_origin": it.get("phase_origin")}
                for it in planning_items
            ]
            logger.info("EVOLVE: Phase 5 standalone — using %d planning evolve items as plans",
                         len(plans))

    logger.info("EVOLVE: Phase 5 found %d plans total", len(plans))

    # Load existing evolve items for dedup — the LLM must check before creating
    existing_items = []
    try:
        from data_layer.evolution import list_items
        all_items = await asyncio.to_thread(list_items, include_completed=True, limit=200)
        existing_items = [
            {"id": it["id"], "title": it["title"], "status": it["status"],
             "category": it.get("category", ""), "body": it.get("body", "")[:200]}
            for it in all_items
        ]
    except Exception as e:
        logger.warning("EVOLVE: Could not load existing items for dedup: %s", e)

    # Load goal landscape for linking
    goal_landscape = []
    try:
        from apps.goals.data import list_entities, get_projects_for_goal
        goals = await asyncio.to_thread(list_entities, "g-")
        for goal in goals:
            projects = await asyncio.to_thread(get_projects_for_goal, goal["id"])
            goal_landscape.append({
                "id": goal["id"],
                "name": goal.get("name", ""),
                "status": goal.get("status", ""),
                "projects": [{"id": p["id"], "name": p.get("name", ""), "status": p.get("status", "")}
                             for p in projects],
            })
    except Exception as e:
        logger.warning("EVOLVE: Could not load goals for Phase 5 linking: %s", e)

    dedup_context = {
        "existing_items": existing_items,
        "goal_landscape": goal_landscape,
    }

    for plan in plans:
        units.append({
            "name": f"Create item: {plan.get('title', '?')[:60]}",
            "prompt_template": "phase_5_propose",
            "context": {"plan": plan, **dedup_context},
        })

    # Summary DM to Alice
    if plans:
        units.append({
            "name": "Notify Alice — cycle summary",
            "prompt_template": "phase_5_propose",
            "context": {"task": "summary_dm", "plan_count": len(plans),
                        "existing_item_count": len(existing_items)},
        })

    return units


async def _enumerate_act_units(wm: dict) -> list[dict]:
    """Daily feedback Phase 1: Act on approved items + reconcile in-progress items."""
    units = []
    feedback = wm.get("feedback", {})

    # Approved items from Phase 0 feedback → planning
    for item in feedback.get("approved_items", []):
        units.append({
            "name": f"Act: {item.get('title', item.get('id', '?'))[:60]}",
            "prompt_template": "phase_4_plan",
            "context": {"item": item, "act_mode": True},
        })

    # Load active evolve items with their linked goals for reconciliation
    from data_layer.evolution import list_items
    from data_layer.links import get_links

    active_items = await asyncio.to_thread(
        list_items, include_completed=False)

    # Build goal landscape for status checking
    goal_map = {}
    try:
        from apps.goals.data import list_entities, get_projects_for_goal
        goals = await asyncio.to_thread(list_entities, "g-")
        for g in goals:
            projects = await asyncio.to_thread(get_projects_for_goal, g["id"])
            goal_map[g["id"]] = {
                "id": g["id"], "name": g.get("name", ""), "status": g.get("status", ""),
                "projects": [{"id": p["id"], "name": p.get("name", ""),
                              "status": p.get("status", ""), "task_count": len(p.get("tasks", []))}
                             for p in projects],
            }
    except Exception as e:
        logger.warning("EVOLVE: Could not load goal map for act phase: %s", e)

    # For each active evolve item, check its linked goals/projects
    for item in active_items:
        links = await asyncio.to_thread(get_links, item["id"])
        linked_goals = []
        linked_projects = []
        for lnk in links:
            other = lnk["target_id"] if lnk["source_id"] == item["id"] else lnk["source_id"]
            if other.startswith("g-") and other in goal_map:
                linked_goals.append(goal_map[other])
            elif other.startswith("p-"):
                # Find in goal_map projects
                for g in goal_map.values():
                    for p in g.get("projects", []):
                        if p["id"] == other:
                            linked_projects.append(p)

        units.append({
            "name": f"Reconcile: {item['title'][:60]}",
            "prompt_template": "phase_1_reconcile",
            "context": {
                "item": item,
                "linked_goals": linked_goals,
                "linked_projects": linked_projects,
                "task": "reconcile",
            },
        })

    logger.info("EVOLVE: Feedback Act phase: %d approved, %d active items to reconcile",
                len(feedback.get("approved_items", [])), len(active_items))

    # Synthesis
    if units:
        units.append({
            "name": "Act synthesis — status updates",
            "prompt_template": "synthesis",
            "context": {"phase": "act", "phase_key": "phase_1_act"},
            "is_synthesis": True,
        })

    return units


# ---------------------------------------------------------------------------
# Job tree helpers
# ---------------------------------------------------------------------------

def _find_active_cycle_sync() -> dict | None:
    """Find an evolve_cycle job that is still active (queued or running).
    Cycle jobs are containers — never dispatched by the job runner — so they
    stay 'queued' for their entire lifetime."""
    from data_layer.db import fetch_one
    row = fetch_one(
        "SELECT * FROM jobs WHERE job_type = 'evolve_cycle' "
        "AND status IN ('queued', 'running') "
        "ORDER BY created_at DESC LIMIT 1",
    )
    return _job_row(row) if row else None


async def _find_active_cycle() -> dict | None:
    return await asyncio.to_thread(_find_active_cycle_sync)


def _get_running_phase(cycle_id: str) -> dict | None:
    from data_layer.db import fetch_one
    row = fetch_one(
        "SELECT * FROM jobs WHERE job_type = 'evolve_phase' AND parent_job_id = %s "
        "AND status = 'running' ORDER BY config->>'phase_index' LIMIT 1",
        (cycle_id,),
    )
    return _job_row(row) if row else None


def _get_next_queued_phase(cycle_id: str) -> dict | None:
    from data_layer.db import fetch_one
    row = fetch_one(
        "SELECT * FROM jobs WHERE job_type = 'evolve_phase' AND parent_job_id = %s "
        "AND status = 'queued' ORDER BY config->>'phase_index' LIMIT 1",
        (cycle_id,),
    )
    return _job_row(row) if row else None


def _get_child_jobs(parent_id: str) -> list[dict]:
    from data_layer.db import fetch_all
    rows = fetch_all(
        "SELECT * FROM jobs WHERE parent_job_id = %s ORDER BY created_at",
        (parent_id,),
    )
    return [_job_row(r) for r in rows]


def _set_job_running(job_id: str):
    from data_layer.db import execute
    execute(
        "UPDATE jobs SET status = 'running', started_at = now() WHERE id = %s",
        (job_id,),
    )


def _complete_phase(phase_id: str):
    from app_platform.jobs import complete_job
    complete_job(phase_id, "Phase complete")


async def _complete_cycle(cycle_id: str):
    from app_platform.jobs import complete_job
    await asyncio.to_thread(complete_job, cycle_id, "Cycle complete")
    logger.info("EVOLVE: Cycle %s completed", cycle_id)


def _requeue_job(job_id: str):
    from data_layer.db import execute
    execute(
        "UPDATE jobs SET status = 'queued', started_at = NULL, claimed_by = '' "
        "WHERE id = %s",
        (job_id,),
    )


def _worker_is_dead(unit: dict) -> bool:
    """Check if the worker that claimed a job is no longer running.

    Simple heuristic: if the job has been running for more than 10 minutes
    without progress, assume the worker is dead.
    """
    started = unit.get("started_at")
    if not started:
        return True
    if hasattr(started, "timestamp"):
        age = datetime.now(get_timezone()).timestamp() - started.timestamp()
    else:
        return False
    return age > 600  # 10 minutes


def _job_row(row: dict) -> dict:
    """Normalize a job row dict — handle config JSONB."""
    if not row:
        return {}
    result = dict(row)
    if isinstance(result.get("config"), str):
        try:
            result["config"] = json.loads(result["config"])
        except (json.JSONDecodeError, TypeError):
            result["config"] = {}
    if isinstance(result.get("output"), str):
        try:
            result["output"] = json.loads(result["output"])
        except (json.JSONDecodeError, TypeError):
            result["output"] = {}
    return result


# ---------------------------------------------------------------------------
# Working memory helpers
# ---------------------------------------------------------------------------

def _load_working_memory() -> dict:
    """Load all Evolve working memory from skipper_state.

    Returns a dict keyed by subject_id (phase name), with parsed JSON content.
    """
    try:
        from data_layer.skipper_state import get_working_memory
        entries = get_working_memory("evolve") or []
        result = {}
        for entry in entries:
            key = entry.get("subject_id", "")
            content = entry.get("content", "")
            if isinstance(content, str) and content.strip():
                try:
                    result[key] = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    result[key] = content
            elif isinstance(content, dict):
                result[key] = content
        return result
    except Exception:
        return {}


async def _save_working_memory(key: str, value):
    """Save a value to Evolve working memory."""
    try:
        from data_layer.skipper_state import upsert_working_memory
        content = json.dumps(value) if not isinstance(value, str) else value
        await asyncio.to_thread(
            upsert_working_memory,
            domain="evolve",
            subject_id=key,
            subject_type="phase_output",
            content=content,
        )
    except Exception as e:
        logger.error("EVOLVE: Failed to save working memory key '%s': %s", key, e)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _skip(reason: str, next_check: int = 300) -> dict:
    """Return a 'skip' result — handler didn't run the LLM."""
    return {
        "trigger": "timer",
        "input_summary": reason,
        "reasoning": reason,
        "actions_taken": [],
        "memories_extracted": [],
        "model_used": "skip",
        "tokens_used": 0,
        "next_check_seconds": next_check,
    }
