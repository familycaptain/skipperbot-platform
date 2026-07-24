"""
PM Domain Module
================
Implements the observe → evaluate → act contract for the Project Management domain.

Called by the thinking scheduler when the PM domain is due for a cycle.
Uses PM_THINK.md prompt to give the LLM judgment over pending actions,
observations, and working memory — deciding what needs attention now
versus what can wait for the next daily scrum.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta

from config import (
    logger, pm_audit_logger,
    PROMPTS_DIR, PM_QUIET_MODE,
)
from app_platform.time import get_timezone
import agent_loop

def _default_cadence_minutes() -> int:
    """Global anti-spam window (Settings → Goals: pm_cadence_hours), in minutes.

    The PM domain runs throughout the day, but won't re-engage the SAME project
    within this window unless there's new activity. Used as the default when a
    project has no explicit pm_cadence_minutes override.
    """
    try:
        from app_platform import settings as _settings
        return int(_settings.get("pm_cadence_hours", scope="app:goals", default=24) or 24) * 60
    except (TypeError, ValueError):
        return 24 * 60


# Max items before we escalate from cheap to standard model
CHEAP_MODEL_THRESHOLD = 5

# Custom tool schemas for the thinking loop (not MCP tools)
SEND_DM_TOOL = {
    "type": "function",
    "function": {
        "name": "send_dm",
        "description": "Send a direct message to a family member. Automatically creates a pending_action to track the conversation. Max 2 DMs per cycle.",
        "parameters": {
            "type": "object",
            "properties": {
                "to_user": {"type": "string", "description": "The recipient's REAL username — an actual household user from your context (usually the primary user). Do NOT invent or use placeholder/example names."},
                "message": {"type": "string", "description": "The message text to send"},
                "subject_id": {"type": "string", "description": "Entity ID this DM is about (e.g. 't-xxx', 'p-xxx')"},
            },
            "required": ["to_user", "message", "subject_id"],
        },
    },
}

# State tools — the LLM calls these directly via the agent loop
# (replaces the old submit_analysis batched approach)
EXPIRE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "expire_state",
        "description": "Expire/close a skipper_state entry (pending_action, observation, etc.). Use when the item is no longer relevant, or a pending action has been answered.",
        "parameters": {
            "type": "object",
            "properties": {
                "state_id": {"type": "string", "description": "The ss-xxx ID of the state entry to expire"},
            },
            "required": ["state_id"],
        },
    },
}

RESOLVE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve_state",
        "description": "Mark a skipper_state entry as resolved/acknowledged. Use for observations and pending actions you've reviewed — IGNORE or NOTE.",
        "parameters": {
            "type": "object",
            "properties": {
                "state_id": {"type": "string", "description": "The ss-xxx ID of the state entry to resolve"},
            },
            "required": ["state_id"],
        },
    },
}

UPDATE_WORKING_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "update_working_memory",
        "description": "Save or update a note in your working memory about an entity. Persists across thinking cycles so you remember findings.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject_id": {"type": "string", "description": "Entity ID (e.g. p-xxx, t-xxx, g-xxx)"},
                "summary": {"type": "string", "description": "What to remember about this entity"},
            },
            "required": ["subject_id", "summary"],
        },
    },
}


async def pm_domain_handler(domain: dict, budget_status: dict) -> dict:
    """The scheduler is the ALARM CLOCK: log an owed pm event; the attention
    system runs the pm sweep turn (pm_skill_runner). Phase 5b: this is the
    only path — the legacy in-handler produce loop is deleted."""
    if True:
        from app_platform.consciousness import log_event
        # De-stack (soak finding: two full sweeps 8 minutes apart): never log a
        # new owed pm alarm while one is still unattended, and never within
        # 15 minutes of the last one — one sweep per alarm, alarms well apart.
        from data_layer.db import fetch_one
        recent = await asyncio.to_thread(
            fetch_one,
            "SELECT id FROM consciousness_log "
            "WHERE kind='event' AND domain='pm' AND payload->>'alarm' = 'pm' "
            "  AND (attended_at IS NULL "
            "       OR created_at > now() - interval '15 minutes') "
            "ORDER BY seq DESC LIMIT 1")
        if recent:
            return {"trigger": "timer",
                    "input_summary": "pm alarm suppressed (recent/pending sweep)",
                    "context_snapshot": {}, "reasoning": f"alarm {recent['id']} still fresh",
                    "actions_taken": [], "memories_extracted": [], "model_used": "skip",
                    "tokens_used": 0, "next_check_seconds": 1800}
        row = log_event(kind="event", who_from="system", domain="pm",
                        content="⏰ pm: review goals & projects",
                        payload={"alarm": "pm"}, needs_attention=True)
        try:
            from app_platform.attention import kick
            kick()
        except Exception:
            pass
        return {"trigger": "timer", "input_summary": "pm alarm handed to attention",
                "context_snapshot": {}, "reasoning": f"owed event {row['id']} logged",
                "actions_taken": [], "memories_extracted": [], "model_used": "skip",
                "tokens_used": 0, "next_check_seconds": 1800}
# ---------------------------------------------------------------------------
# OBSERVE — gather context from skipper_state + entity store
# ---------------------------------------------------------------------------

def _observe() -> dict:
    """Gather all PM-relevant state + pick a project for deep review.

    Phase 5b: the private conversation gatherer is gone — the TIMELINE is the
    conversational context (§12.3)."""
    from data_layer.skipper_state import (
        list_states, get_due_actions,
    )

    # Pending actions (all active, not just overdue — LLM decides relevance)
    pending_actions = list_states(
        domain="pm", state_type="pending_action", status="active", limit=20,
    )

    # Overdue subset (past due_at)
    overdue_actions = get_due_actions(domain="pm")
    overdue_ids = {a["id"] for a in overdue_actions}

    # Unreviewed observations
    observations = list_states(
        domain="pm", state_type="observation", status="active", limit=30,
    )

    # Active working memory
    working_memory = list_states(
        domain="pm", state_type="working_memory", status="active", limit=20,
    )

    # Pick a project for deep review and load its snapshot
    project_snapshot = None
    reviewed_project_id = None
    try:
        reviewed_project_id = _pick_next_project(observations)
        if reviewed_project_id:
            project_snapshot = _load_project_snapshot(reviewed_project_id)
    except Exception as e:
        logger.error("PM_THINK: Failed to load project snapshot: %s", e)


    # Memory recall — search shared memory store for context about the reviewed project
    memories = _recall_memories(reviewed_project_id, project_snapshot)

    return {
        "pending_actions": pending_actions,
        "pending_actions_count": len(pending_actions),
        "overdue_ids": overdue_ids,
        "observations": observations,
        "observations_count": len(observations),
        "working_memory": working_memory,
        "working_memory_count": len(working_memory),
        "project_snapshot": project_snapshot,
        "reviewed_project_id": reviewed_project_id,
        "memories": memories,
        "now": datetime.now(get_timezone()).isoformat(),
    }


def _recall_memories(project_id: str | None, project_snapshot: dict | None) -> list[dict]:
    """Search the shared memory store for memories relevant to the reviewed project.

    Gives the PM cross-domain context — e.g. facts from recent chat
    conversations about the project, or insights from the goal domain.
    """
    if not project_id:
        return []
    try:
        from memory_store import search_memories

        project_name = (project_snapshot or {}).get("project_name", "")
        query = f"{project_name} project status tasks" if project_name else project_id

        results = search_memories(
            query_text=query,
            entity_id=project_id,
            max_results=5,
        )

        # Also search by goal_id if available
        goal_name = (project_snapshot or {}).get("goal_name", "")
        if goal_name:
            goal_results = search_memories(
                query_text=f"{goal_name} goal",
                max_results=3,
            )
            seen_ids = {m["id"] for m in results}
            for m in goal_results:
                if m["id"] not in seen_ids:
                    results.append(m)

        logger.info("PM_THINK: Recalled %d memories for project %s", len(results), project_id)
        return results[:8]

    except Exception as e:
        logger.warning("PM_THINK: Memory recall failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# PROJECT ROTATION — pick the most-due project for deep review
# ---------------------------------------------------------------------------

def _pick_next_project(observations: list[dict]) -> str | None:
    """Pick the project most due for review. Returns project_id or None.

    Scoring: higher score = more urgently needs review.
    - Priority: high=3, medium=2, low=1
    - Activity: +5 per recent observation referencing this project
    - Staleness: hours since last review (capped at 24)
    - Findings: +3 if working_memory exists with issues
    """
    from apps.goals.data import list_entities, load_entity
    from data_layer.skipper_state import list_states

    # Load all active projects. Skip any goal/project in an INACTIVE status
    # (done/deferred/archived/cancelled) so a cancelled or archived goal is no
    # longer surfaced for PM review — aligning this filter with the per-goal
    # goal-think domain, which already treats all four as inactive.
    # Global onboarding app-tour CADENCE hold (ev-75, site 1): resolved ONCE per
    # cycle (it is GLOBAL across all tour apps, not per-subject). Tri-state:
    # None = not yet resolved, resolved lazily the first time a tour candidate is
    # seen so non-onboarding cycles pay nothing.
    _tour_hold = None

    goals = list_entities("g-")
    project_ids = []
    project_meta = {}  # project_id -> {priority, goal_name, pm_cadence_minutes}
    for g in goals:
        if g.get("status") in _INACTIVE_STATUSES:
            continue
        for pid in g.get("projects", []):
            proj = load_entity(pid)
            if not proj or proj.get("status") in _INACTIVE_STATUSES:
                continue
            # Onboarding ordering gate (defect 1a): never SELECT a per-app tour
            # of the in-progress onboarding goal for review while its ordered
            # setup agenda is still open — this is the live selector the repro
            # showed picking 'Try the Chores app' while household was not_started.
            # tour_gated() self-gates on the onboarding goal, so normal goals are
            # untouched.
            try:
                from apps.goals import onboarding
                if onboarding.tour_gated(g, proj):
                    continue
            except Exception:
                logger.warning("PM_THINK: onboarding tour-gate selection filter failed", exc_info=True)
            # Onboarding CADENCE gate (ev-75): once the agenda is complete a tour
            # passes tour_gated (ORDER); do not SELECT a SECOND (different) tour
            # while a prior tour DM is unanswered and < 24h old — a no-reply must
            # not advance to another app. Global (per primary user), resolved once.
            try:
                from apps.goals import onboarding as _onb
                if (_onb.onboarding_project_kind(proj.get("name", "")) == "tour"
                        and _onb.onboarding_agenda_in_progress() == proj.get("goal_id")):
                    if _tour_hold is None:
                        from apps.goals.onboarding import tour_nudge_on_hold
                        from data_layer.users import get_primary_user
                        _recip = (get_primary_user() or "").strip().lower()
                        _tour_hold = tour_nudge_on_hold(_recip) if _recip else False
                    if _tour_hold:
                        continue
            except Exception:
                logger.warning("PM_THINK: onboarding tour-cadence selection filter failed", exc_info=True)
            project_ids.append(pid)
            project_meta[pid] = {
                "priority": proj.get("priority", "medium"),
                "goal_name": g.get("name", ""),
                "pm_cadence_minutes": proj.get("pm_cadence_minutes"),
            }

    if not project_ids:
        return None

    # Load process_position entries — track when we last reviewed each project
    positions = list_states(
        domain="pm", state_type="process_position", status="active", limit=100,
    )
    last_reviewed = {}  # project_id -> datetime
    for pos in positions:
        sid = pos.get("subject_id", "")
        if sid in project_meta:
            ts = pos.get("updated_at") or pos.get("created_at") or ""
            if ts:
                try:
                    last_reviewed[sid] = datetime.fromisoformat(str(ts))
                except (ValueError, TypeError):
                    pass

    # Build set of project_ids referenced by active observations
    obs_project_ids = set()
    for obs in observations:
        sid = obs.get("subject_id", "")
        if sid.startswith("p-"):
            obs_project_ids.add(sid)
        elif sid.startswith("t-"):
            # Resolve task → project
            try:
                task = load_entity(sid)
                if task and task.get("project_id"):
                    obs_project_ids.add(task["project_id"])
            except Exception:
                pass

    # Load working memory entries to detect projects with existing findings
    wm_entries = list_states(
        domain="pm", state_type="working_memory", status="active", limit=50,
    )
    wm_project_ids = {wm.get("subject_id") for wm in wm_entries if wm.get("subject_id", "").startswith("p-")}

    now = datetime.now(get_timezone())
    priority_score = {"high": 3, "medium": 2, "low": 1}

    scores = {}
    for pid in project_ids:
        meta = project_meta[pid]
        score = priority_score.get(meta["priority"], 2)

        # Activity bonus: recent observations about this project
        has_activity = pid in obs_project_ids
        if has_activity:
            score += 5

        # Staleness: hours since last review
        hours_ago = 24  # default: never reviewed
        if pid in last_reviewed:
            hours_ago = (now - last_reviewed[pid]).total_seconds() / 3600
            score += min(hours_ago, 24)  # Cap at 24h worth of staleness
        else:
            score += 24  # Never reviewed — max staleness

        # Findings bonus
        if pid in wm_project_ids:
            score += 3

        # Cadence gate: if the project was reviewed within its cadence window,
        # suppress it heavily (but still allow if there's urgent activity like
        # observations). Per-project pm_cadence_minutes overrides the global
        # default (Settings → Goals: pm_cadence_hours).
        cadence = meta.get("pm_cadence_minutes")
        if not cadence or cadence <= 0:
            cadence = _default_cadence_minutes()
        if cadence and cadence > 0 and pid in last_reviewed:
            cadence_hours = cadence / 60.0
            if hours_ago < cadence_hours and not has_activity:
                score = -100  # Effectively skip — not due yet and no urgent activity
                logger.debug("PM_THINK: Cadence gate — %s reviewed %.1fh ago, cadence=%.1fh, suppressed",
                             pid, hours_ago, cadence_hours)

        scores[pid] = score

    # Pick highest score
    best_pid = max(scores, key=scores.get)
    logger.info("PM_THINK: Project rotation — picked %s (score=%.1f) from %d candidates",
                best_pid, scores[best_pid], len(scores))
    return best_pid


def _load_project_snapshot(project_id: str) -> dict | None:
    """Load a compact project snapshot for the LLM to reason about.

    Returns a dict with project info, goal context, and task summaries.
    Designed to be token-efficient — no full history or artifacts.
    """
    from apps.goals.data import load_entity, get_top_level_tasks, get_subtasks

    project = load_entity(project_id)
    if not project:
        return None

    # Load parent goal for context
    goal_name = ""
    goal_target = ""
    if project.get("goal_id"):
        goal = load_entity(project["goal_id"])
        if goal:
            goal_name = goal.get("name", "")
            goal_target = goal.get("target_date", "")

    # Load tasks (top-level + one level of subtasks)
    top_tasks = get_top_level_tasks(project_id)
    task_summaries = []
    task_counts = {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "not_started": 0}

    for t in top_tasks:
        task_counts["total"] += 1
        status = t.get("status", "not_started")
        task_counts[status] = task_counts.get(status, 0) + 1

        summary = {
            "id": t["id"],
            "name": t["name"],
            "status": status,
            "assigned_to": t.get("assigned_to", []),
            "due_date": t.get("due_date", ""),
            "priority": t.get("priority", ""),
        }

        # Load subtasks (one level deep)
        subs = get_subtasks(t["id"])
        if subs:
            summary["subtasks"] = []
            for s in subs:
                task_counts["total"] += 1
                s_status = s.get("status", "not_started")
                task_counts[s_status] = task_counts.get(s_status, 0) + 1
                summary["subtasks"].append({
                    "id": s["id"],
                    "name": s["name"],
                    "status": s_status,
                    "assigned_to": s.get("assigned_to", []),
                    "due_date": s.get("due_date", ""),
                })

        task_summaries.append(summary)

    return {
        "project_id": project_id,
        "project_name": project.get("name", ""),
        "project_status": project.get("status", ""),
        "project_priority": project.get("priority", "medium"),
        "project_owners": project.get("owners", []),
        "project_due_date": project.get("due_date", ""),
        "project_notes": (project.get("notes", "") or "")[:500],
        "project_definition_of_done": (project.get("definition_of_done", "") or "")[:300],
        "pm_cadence_minutes": project.get("pm_cadence_minutes"),
        "recent_history": (project.get("history") or [])[-5:],
        "goal_name": goal_name,
        "goal_target_date": goal_target,
        "task_counts": task_counts,
        "tasks": task_summaries,
    }


def _record_project_review(project_id: str):
    """Update the process_position entry to record that we just reviewed this project."""
    from data_layer.skipper_state import list_states, create_state, update_state

    # Find existing position entry for this project
    positions = list_states(
        domain="pm", state_type="process_position", status="active",
        subject_id=project_id, limit=1,
    )
    now_str = datetime.now(get_timezone()).isoformat()
    if positions:
        update_state(positions[0]["id"], content=json.dumps({"last_reviewed": now_str}))
    else:
        create_state(
            domain="pm",
            state_type="process_position",
            subject_id=project_id,
            subject_type="project",
            content=json.dumps({"last_reviewed": now_str}),
        )


# ---------------------------------------------------------------------------
# EVALUATE — LLM-powered judgment
# ---------------------------------------------------------------------------

def _format_state_entry(entry: dict, overdue_ids: set = None) -> str:
    """Format a skipper_state entry for the LLM context."""
    eid = entry.get("id", "?")
    subject = entry.get("subject_id", "?")
    subject_type = entry.get("subject_type", "?")
    created = entry.get("created_at", "")
    due = entry.get("due_at", "")
    priority = entry.get("priority", "")

    # Parse content
    content_raw = entry.get("content", "")
    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except (json.JSONDecodeError, TypeError):
        content = {"raw": content_raw}

    lines = [f"- **{eid}** (subject: {subject_type} `{subject}`)"]
    if priority:
        lines[0] += f" [priority: {priority}]"
    if due:
        is_overdue = overdue_ids and eid in overdue_ids
        lines[0] += f" [due: {due}]" + (" ⚠️ OVERDUE" if is_overdue else "")
    if created:
        lines.append(f"  Created: {created}")

    # Render content fields
    if isinstance(content, dict):
        for k, v in content.items():
            if k in ("raw",):
                lines.append(f"  {v}")
            else:
                lines.append(f"  {k}: {v}")
    else:
        lines.append(f"  {content}")

    return "\n".join(lines)


def _build_user_prompt(ctx: dict) -> str:
    """Assemble the user prompt from observation context + project snapshot."""
    now = ctx["now"]
    overdue_ids = ctx.get("overdue_ids", set())
    parts = [f"**Current time:** {now}\n"]

    # Real household roster — so DMs address actual users by name (never a
    # placeholder). Always use a real username; default to the primary user.
    try:
        from data_layer.users import get_human_users, get_primary_user, display_name_for
        _humans = [u["name"] for u in get_human_users() if u.get("name") != "skipper"]
        _primary = (get_primary_user() or "").strip().lower()
        if _humans:
            _roster = ", ".join(
                f"{display_name_for(h)} (username `{h}`" + (", primary)" if h == _primary else ")")
                for h in _humans
            )
            parts.append(f"**Household (address by name in prose; DM by username):** {_roster}")
            parts.append("Address people by their display name in what you say/write; when you DM, use their exact username above — default to the primary user. Never invent or use placeholder/example names.\n")
    except Exception:
        pass

    # Project under review (deep analysis target)
    snap = ctx.get("project_snapshot")
    if snap:
        parts.append("## Project Under Review (deep analysis target this cycle)")
        parts.append(f"**{snap['project_name']}** (`{snap['project_id']}`)")
        parts.append(f"- Goal: {snap['goal_name']}" + (f" (target: {snap['goal_target_date']})" if snap.get('goal_target_date') else ""))
        parts.append(f"- Status: {snap['project_status']} | Priority: {snap['project_priority']}")
        parts.append(f"- Owners: {', '.join(snap['project_owners']) if snap['project_owners'] else 'none'}")
        if snap.get("project_due_date"):
            parts.append(f"- Due: {snap['project_due_date']}")
        if snap.get("pm_cadence_minutes"):
            parts.append(f"- PM check-in cadence: every {snap['pm_cadence_minutes']} minutes (you can change this with update_item)")
        tc = snap.get("task_counts", {})
        parts.append(f"- Tasks: {tc.get('total', 0)} total — {tc.get('done', 0)} done, {tc.get('in_progress', 0)} in progress, {tc.get('blocked', 0)} blocked, {tc.get('not_started', 0)} not started")
        if snap.get("project_definition_of_done"):
            parts.append(f"- Definition of done: {snap['project_definition_of_done']}")
        if snap.get("project_notes"):
            parts.append(f"- Notes: {snap['project_notes']}")
        if snap.get("recent_history"):
            parts.append("\n**Recent project history (READ THESE - may contain owner directives):**")
            for h in snap["recent_history"]:
                ts = (h.get("timestamp") or "")[:16]
                parts.append(f"- [{ts}] ({h.get('by', '')}): {h.get('note', '')}")

        # Task details
        if snap.get("tasks"):
            parts.append("\n### Tasks")
            for t in snap["tasks"]:
                assignees = ", ".join(t.get("assigned_to", [])) if t.get("assigned_to") else "unassigned"
                due = f" due:{t['due_date']}" if t.get("due_date") else ""
                pri = f" [{t['priority']}]" if t.get("priority") else ""
                parts.append(f"- **{t['name']}** (`{t['id']}`) — {t['status']}{pri} — {assignees}{due}")
                for sub in t.get("subtasks", []):
                    s_assignees = ", ".join(sub.get("assigned_to", [])) if sub.get("assigned_to") else "unassigned"
                    s_due = f" due:{sub['due_date']}" if sub.get("due_date") else ""
                    parts.append(f"  - {sub['name']} (`{sub['id']}`) — {sub['status']} — {s_assignees}{s_due}")
        parts.append("")

    # Pending actions + conversation replies
    if ctx["pending_actions"]:
        parts.append("## Pending Actions (DMs sent to people, awaiting response)")
        conversations = ctx.get("recent_conversations", {})
        for pa in ctx["pending_actions"]:
            parts.append(_format_state_entry(pa, overdue_ids))
            # Show any replies from this person since the DM was sent
            content_raw = pa.get("content", "")
            try:
                content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                person = content.get("dm_to", "") if isinstance(content, dict) else ""
            except (json.JSONDecodeError, TypeError):
                person = ""
            if person and person in conversations:
                turns = conversations[person]
                parts.append(f"  **Conversation with {person} since DM:**")
                for turn in turns[-5:]:  # Last 5 messages max
                    um = turn.get("user_message", "")
                    am = turn.get("assistant_message", "")
                    ts = turn.get("timestamp", "")[:19]
                    if um and not um.startswith("["):
                        parts.append(f"  - [{ts}] {person}: {um[:200]}")
                    if am:
                        parts.append(f"  - [{ts}] Skipper: {am[:200]}")
        parts.append("")

    # Additional conversation context for project members (not in pending_actions)
    conversations = ctx.get("recent_conversations", {})
    pa_people = set()
    for pa in ctx.get("pending_actions", []):
        try:
            c = json.loads(pa.get("content", ""))
            if isinstance(c, dict) and c.get("dm_to"):
                pa_people.add(c["dm_to"])
        except (json.JSONDecodeError, TypeError):
            pass
    extra_convos = {p: turns for p, turns in conversations.items() if p not in pa_people}
    if extra_convos:
        parts.append("## Recent Conversations (project members, last 24h)")
        for person, turns in extra_convos.items():
            parts.append(f"**{person}:**")
            for turn in turns[-3:]:
                um = turn.get("user_message", "")
                am = turn.get("assistant_message", "")
                ts = turn.get("timestamp", "")[:19]
                if um and not um.startswith("["):
                    parts.append(f"- [{ts}] {person}: {um[:200]}")
                if am:
                    parts.append(f"- [{ts}] Skipper: {am[:200]}")
        parts.append("")

    # Observations
    if ctx["observations"]:
        parts.append("## Recent Observations (entity changes since last cycle)")
        for obs in ctx["observations"]:
            parts.append(_format_state_entry(obs))
        parts.append("")

    # Working memory
    if ctx["working_memory"]:
        parts.append("## Working Memory (what you know from recent scans)")
        for wm in ctx["working_memory"]:
            parts.append(_format_state_entry(wm))
        parts.append("")

    # Shared memories (from chat conversations, other domains, etc.)
    if ctx.get("memories"):
        from memory_store import format_memories_for_context
        mem_text = format_memories_for_context(ctx["memories"])
        if mem_text:
            parts.append("## Shared Memories (from conversations and other thinking domains)")
            parts.append(mem_text)
            parts.append("")

    if not ctx["pending_actions"] and not ctx["observations"] and not snap:
        parts.append("Nothing to review — all quiet.")

    return "\n".join(parts)


PM_TOOL_CATEGORIES = {
    "core",          # memory, recall
    "goals",         # projects, tasks, goals
    "reminders",     # reminders and nags
    "lists",         # to-do lists
    "docs",          # living documents (project notes, reference)
    "links",         # cross-reference entities
    "prioritize",    # focus / backlog
    "scrum",         # daily scrum items
    "notifications", # check what's been sent
    "knowledge",     # query knowledge base
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_snapshot(ctx: dict) -> dict:
    """Build a JSON-safe context snapshot (strip non-serializable items)."""
    snap = {
        "pending_actions_count": ctx.get("pending_actions_count", 0),
        "observations_count": ctx.get("observations_count", 0),
        "working_memory_count": ctx.get("working_memory_count", 0),
        "now": ctx.get("now", ""),
    }
    ps = ctx.get("project_snapshot")
    if ps:
        snap["reviewed_project"] = {
            "id": ps.get("project_id"),
            "name": ps.get("project_name"),
            "task_counts": ps.get("task_counts"),
        }
    convos = ctx.get("recent_conversations", {})
    if convos:
        snap["conversations_loaded"] = {
            "people": list(convos.keys()),
            "total_turns": sum(len(t) for t in convos.values()),
        }
    return snap


# ── the pm SKILL (specs/CONSCIOUSNESS.md §13 Phase 3b) ───────────────────────
# The sweep + ROUTER as one attention turn: structured state from _observe
# (conversation gatherer OFF — the timeline is the conversation source), the
# recent timeline as native multi-speaker turns, sends via send_message (one
# voice), and goal work routed to the HANDS via schedule_goal_work.

_PM_SKILL_GUIDANCE = (
    "You are Skipper wearing the PROJECT-MANAGER skill: review the household's "
    "goals and projects like a good PM. You see the household timeline below — "
    "each person only sees their own chat, so any message you send must stand "
    "on its own for its reader. Actions available: send_message to follow up "
    "with a person about THEIR items (brief, specific, at most one message per "
    "person per review; don't re-nudge someone the timeline shows you nudged "
    "recently or who hasn't replied yet); schedule_goal_work(goal_id) for goals "
    "whose open items are assigned to Skipper and are tool-executable (research, "
    "drafting, building) — that queues an autonomous work session, do NOT try "
    "to do that work here; update_working_memory / resolve_state / expire_state "
    "to keep your PM state tidy. Doing NOTHING is a valid outcome — only act "
    "where a PM genuinely would."
    "\n\nTIMING — read the [time] stamps on every timeline line and the current "
    "time in the alarm, and reason about elapsed time before you speak: "
    "(1) If someone said they WILL do something at a future time (\"tomorrow "
    "morning\", \"next week\"), it has NOT happened yet — never ask how it went "
    "or whether they did it until that time has clearly passed. A good PM does "
    "not nag ahead of the plan; note the commitment in working memory with WHEN "
    "to follow up, and stay silent until then. "
    "(2) If your own recent message is still unanswered, do not re-ask or "
    "re-nudge — minutes of silence means they're busy, not that they forgot. "
    "(3) The timeline is the freshest truth: when an old memory, note, or "
    "pending action conflicts with what someone said more recently in the "
    "timeline, the timeline wins — update or expire the stale state instead of "
    "repeating it back."
)

_SEND_MESSAGE_TOOL_PM = {
    "type": "function",
    "function": {
        "name": "send_message",
        "description": "Send one chat message to one family member (as Skipper's own voice). "
                       "When the message is ABOUT a specific project/task/goal (e.g. asking for "
                       "a status or a blocker), pass its id as `subject` — that tags the message "
                       "to the item so when they reply, their answer can be recorded on it.",
        "parameters": {"type": "object", "properties": {
            "to_user": {"type": "string"}, "message": {"type": "string"},
            "subject": {"type": "string",
                        "description": "The p-/t-/g- id this message is about, if any (optional)."}},
            "required": ["to_user", "message"]},
    },
}
_SCHEDULE_GOAL_WORK_TOOL = {
    "type": "function",
    "function": {
        "name": "schedule_goal_work",
        "description": "Queue one autonomous Skipper work session for a goal whose open items are Skipper-assigned and tool-executable.",
        "parameters": {"type": "object", "properties": {
            "goal_id": {"type": "string", "description": "The g- goal id."}},
            "required": ["goal_id"]},
    },
}


async def pm_skill_runner(event: dict) -> dict:
    """Attention runner for the pm alarm event."""
    import asyncio
    import agent_loop
    from data_layer.users import get_human_users
    from app_platform.consciousness import tail, send_message
    from app_platform.context import render_event

    ctx = await asyncio.to_thread(_observe)
    state = _build_user_prompt(ctx)

    rows = await asyncio.to_thread(tail, 40)
    timeline = []
    for r in rows:
        m = render_event(r, "")  # no focal person: PM sees everyone tagged
        if m:
            timeline.append(m)

    humans = {((u.get("name") or "") if isinstance(u, dict) else str(u)).lower()
              for u in (await asyncio.to_thread(get_human_users) or [])}
    actions_taken: list[dict] = []
    messaged: set[str] = set()
    scheduled: set[str] = set()

    async def _dispatch(name: str, args: dict) -> str:
        if name == "send_message":
            to_user = (args.get("to_user") or "").lower().strip()
            if to_user not in humans:
                return f"REFUSED: {to_user!r} is not a known household member"
            if to_user in messaged:
                return f"ALREADY messaged {to_user} this review"
            subj = (args.get("subject") or "").strip() or None
            # #101 (re-homes #74/#75): tour nudges are CODE-GATED at dispatch,
            # mirroring how the legacy path gated send_dm — never prompt-only.
            # A send is a tour nudge if its subject is a tour project of the
            # in-progress onboarding goal, or its text names one.
            try:
                from apps.goals import onboarding as _onb
                _gid = _onb.onboarding_agenda_in_progress()
                if _gid:
                    _projs = _onb._onboarding_goal_projects(_gid)
                    _tours = {p.get("id"): (p.get("name") or "") for p in _projs
                              if _onb.onboarding_project_kind(p.get("name", "")) == "tour"}
                    _txt = (args.get("message") or "").lower()
                    _is_tour = (subj in _tours) or any(
                        n and n.lower() in _txt for n in _tours.values())
                    if _is_tour:
                        # ORDERING (#74): no tour nudge while an ordered
                        # agenda step is still open.
                        if not _onb.agenda_projects_complete(_projs):
                            return ("REFUSED: the onboarding setup agenda still has an "
                                    "open step — finish/skip the agenda before any app "
                                    "tour nudge (#74)")
                        # PACING (#75): ≤1 tour nudge per ~24h across ALL apps;
                        # advance only on a genuine reply.
                        if _onb.tour_nudge_on_hold(to_user):
                            return ("REFUSED: a tour nudge to this person is already "
                                    "out (<24h, unanswered) — do not send another tour "
                                    "nudge until they reply (#75)")
                    else:
                        # PACING (#113): the ordered agenda/step nudges get the
                        # SAME once-a-day/held-until-reply cadence as tours —
                        # always intended for both, only ever built for tours.
                        # Keyed by tour-EXCLUSION (this send is not a tour), so
                        # an untagged step nudge is still held.
                        if _onb.onboarding_step_nudge_on_hold(to_user):
                            return ("REFUSED: a nudge for this onboarding step is "
                                    "already out (<24h, unanswered) — wait for their "
                                    "reply before nudging again (#113)")
            except Exception:
                logger.warning("PM_SKILL: tour dispatch guard failed open", exc_info=True)
            row = await asyncio.to_thread(
                lambda: send_message(who_to=to_user, content=args.get("message") or "",
                                     domain="pm", subject_id=subj,
                                     payload={"pm_review": event.get("id")}))
            messaged.add(to_user)
            actions_taken.append({"type": "dm_sent", "dm_to": to_user})
            return f"sent ({row['id']})"
        if name == "schedule_goal_work":
            gid = (args.get("goal_id") or "").strip()
            if not gid.startswith("g-"):
                return "REFUSED: goal_id must be a g- id"
            if gid in scheduled:
                return f"already scheduled this review"
            from apps.jobs.data import count_running
            if count_running("goal_work") >= 2:
                return "work slots busy — try next review"
            from app_platform.jobs import submit_job
            job = await asyncio.to_thread(
                lambda: submit_job(job_type="goal_work", name=f"goal work: {gid}",
                                   created_by="pm-skill", config={"goal_id": gid}))
            scheduled.add(gid)
            actions_taken.append({"type": "goal_work_scheduled", "goal_id": gid})
            return f"work session queued ({job.get('id')})"
        if name == "update_working_memory":
            from data_layer.skipper_state import upsert_working_memory
            await asyncio.to_thread(
                upsert_working_memory, "pm", args.get("subject_id") or "pm", "note",
                args.get("summary") or args.get("content") or "")
            actions_taken.append({"type": "memory_updated"})
            return "working memory updated"
        if name in ("resolve_state", "expire_state"):
            from data_layer.skipper_state import update_state
            sid = args.get("state_id") or ""
            new_status = "resolved" if name == "resolve_state" else "expired"
            await asyncio.to_thread(update_state, sid, status=new_status)
            actions_taken.append({"type": new_status, "target_id": sid})
            return f"state {sid} {new_status}"
        import tool_dispatch
        result = await tool_dispatch.call_tool(name, args)
        actions_taken.append({"type": "tool_executed", "tool": name})
        return result

    tools = [_SEND_MESSAGE_TOOL_PM, _SCHEDULE_GOAL_WORK_TOOL,
             UPDATE_WORKING_MEMORY_TOOL, RESOLVE_STATE_TOOL, EXPIRE_STATE_TOOL]

    _now = datetime.now(get_timezone())
    trigger = (f"[alarm] ⏰ pm review time — it is now {_now:%A, %B} {_now.day}, "
               f"{_now:%Y, %I:%M %p}. Sweep, follow up, route work — respecting "
               f"the TIMING rules. Silence is fine.")
    await agent_loop.run(
        messages=[
            {"role": "system", "content": _PM_SKILL_GUIDANCE},
            {"role": "system", "content": "STRUCTURED PM STATE:\n" + state},
            *timeline,
            {"role": "user", "content": trigger},
        ],
        tools=tools, tier="smart", max_turns=4, max_tool_calls=10,
        tool_dispatch=_dispatch,
    )
    return {"summary": f"pm sweep: {len(actions_taken)} action(s) "
                       f"({len(messaged)} msg, {len(scheduled)} work session(s))"}
