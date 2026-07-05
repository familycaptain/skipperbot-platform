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
    # Phase 3b: under consciousness_pm the scheduler stays the ALARM CLOCK but
    # the turn runs through the attention system as the pm SKILL.
    if _consciousness_pm_enabled():
        from app_platform.consciousness import log_event
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
    """Run one PM thinking cycle via the unified agent loop.

    Flow: observe → build messages → agent_loop.run() (multi-turn tool execution)
    The LLM calls state tools (expire_state, resolve_state, update_working_memory),
    action tools (send_dm, create_task, update_item), and returns reasoning as text.
    """
    from tool_router import get_guides_for_message

    # ---------- OBSERVE ----------
    ctx = await asyncio.to_thread(_observe)

    total_items = (
        ctx["pending_actions_count"]
        + ctx["observations_count"]
    )
    has_project = ctx.get("project_snapshot") is not None

    # Only skip if truly nothing to do — no state items AND no project to review
    if total_items == 0 and not has_project:
        return {
            "trigger": "timer",
            "input_summary": "No pending work, no projects to review — quiet cycle.",
            "context_snapshot": _safe_snapshot(ctx),
            "reasoning": "Nothing requires attention. No overdue actions, no new observations, no projects due for review.",
            "actions_taken": [],
            "memories_extracted": [],
            "model_used": "skip",
            "tokens_used": 0,
            "next_check_seconds": 1800,
        }

    # ---------- SET FOCUS ----------
    focus_subject = ctx.get("reviewed_project_id") or "pm"
    focus_type = "project" if ctx.get("reviewed_project_id") else "domain"
    project_name = ""
    if ctx.get("project_snapshot"):
        project_name = ctx["project_snapshot"].get("project_name", "")
    focus_desc = f"Reviewing project: {project_name}" if project_name else "Scanning pending actions and observations"
    try:
        from data_layer.skipper_state import upsert_focus
        await asyncio.to_thread(upsert_focus, "pm", focus_subject, focus_type, focus_desc)
    except Exception as e:
        logger.warning("PM_THINK: Failed to set focus: %s", e)

    # ---------- MODEL SELECTION ----------
    # The cheap/standard decision maps to a model TIER (MODEL_FLEXIBILITY #44/#71); agent_loop
    # resolves the connector+model+key from the tier. No raw model id / OPENAI_API_KEY here.
    if has_project:
        tier = "smart"
        model_tier = "standard"
    else:
        tier = "fast" if total_items <= CHEAP_MODEL_THRESHOLD else "smart"
        model_tier = "cheap" if tier == "fast" else "standard"

    remaining = budget_status.get("remaining", 999999)
    if remaining < 50_000 and tier == "smart":
        tier = "fast"
        model_tier = "cheap"
        logger.info("PM_THINK: Downgraded to fast tier — budget low (%d remaining)", remaining)

    # ---------- BUILD MESSAGES + TOOLS ----------
    static_system = _load_pm_think_prompt()
    if not static_system:
        logger.error("PM_THINK: No system prompt — skipping cycle")
        return {
            "trigger": "timer", "input_summary": "No prompt file found",
            "context_snapshot": _safe_snapshot(ctx), "reasoning": "No prompt file",
            "actions_taken": [], "memories_extracted": [], "model_used": "skip",
            "tokens_used": 0, "next_check_seconds": 1800,
        }

    user_prompt = _build_user_prompt(ctx)
    tools, routed_tool_names = _build_thinking_tools(user_prompt)

    # Dynamic context — keyword-routed guides change per project review
    dynamic_context = ""
    guide_content = get_guides_for_message(user_prompt)
    if guide_content:
        dynamic_context = "## Tool Guides (reference)\n\n" + guide_content

    # Two system messages: static prefix (cacheable) + dynamic context
    messages = [
        {"role": "system", "content": static_system},
    ]
    if dynamic_context:
        messages.append({"role": "system", "content": dynamic_context})
    messages.append({"role": "user", "content": user_prompt})

    pm_audit_logger.info("PM_THINK: Calling %s tier with %d pending actions, %d observations, %d memory entries, %d tools",
                         tier, ctx["pending_actions_count"], ctx["observations_count"],
                         ctx["working_memory_count"], len(tools))
    pm_audit_logger.info("PM_THINK user prompt:\n%s", user_prompt[:2000])

    # ---------- TOOL DISPATCH + HOOKS ----------
    actions_taken = []
    memory_updates = []
    dm_count = 0
    dm_recipients = set()

    async def _pm_dispatch(tool_name: str, tool_args: dict) -> str:
        """Route PM tool calls to state ops, DM handler, or MCP."""
        nonlocal dm_count
        from data_layer.skipper_state import (
            expire_state as _expire, resolve_state as _resolve,
            upsert_working_memory as _upsert_wm, create_state,
        )

        if tool_name == "expire_state":
            state_id = tool_args.get("state_id", "")
            await asyncio.to_thread(_expire, state_id)
            return f"Expired state entry {state_id}"

        if tool_name == "resolve_state":
            state_id = tool_args.get("state_id", "")
            await asyncio.to_thread(_resolve, state_id)
            return f"Resolved state entry {state_id}"

        if tool_name == "update_working_memory":
            sid = tool_args.get("subject_id", "")
            summary = tool_args.get("summary", "")
            stype = ("project" if sid.startswith("p-") else
                     "goal" if sid.startswith("g-") else
                     "task" if sid.startswith("t-") else "unknown")
            await asyncio.to_thread(_upsert_wm, "pm", sid, stype, summary)
            return f"Working memory updated for {sid}"

        if tool_name == "send_dm":
            dm_to = tool_args.get("to_user", "").lower().strip()
            dm_text = tool_args.get("message", "")
            subject_id = tool_args.get("subject_id", "")
            if not dm_to or not dm_text:
                return "Error: to_user and message are required"
            if dm_to == "skipper":
                return ("You cannot DM Skipper — that's you. "
                        "To communicate findings about a Skipper-owned project or task, "
                        "add a history note via update_item(item_id, updated_by='pm', history_note='...'), "
                        "or record it in working memory.")
            # Produce-layer tour gate (defect 1a): block a DM whose subject
            # resolves to a per-app tour project of the in-progress onboarding
            # goal while its agenda is still open — the read tools can enumerate
            # tours even though _pick_next_project won't select them. tour_gated()
            # self-gates on the onboarding goal (resolved from the project's
            # goal_id), so normal projects are untouched.
            if subject_id and subject_id.startswith("p-"):
                try:
                    from apps.goals import onboarding
                    from apps.goals.data import load_entity
                    _proj = load_entity(subject_id)
                    if _proj and onboarding.tour_gated(_proj.get("goal_id", ""), _proj):
                        return (
                            "That DM is about an app tour, but the onboarding "
                            "setup agenda isn't complete yet — app tours come "
                            "after the agenda. DM not sent."
                        )
                except Exception:
                    logger.warning("PM_THINK: tour-gate DM check failed", exc_info=True)
            # Global onboarding app-tour CADENCE hold (ev-75, site 2): after the
            # agenda is complete tours pass tour_gated (ORDER) above; hold ALL app
            # tour nudges for ~24h once one is out and unanswered so a no-reply
            # can't march the catalog to a DIFFERENT app. Global (not per-subject),
            # so it complements — not replaces — the per-subject _dm_on_hold below.
            if subject_id and subject_id.startswith("p-"):
                try:
                    from apps.goals import onboarding
                    from apps.goals.data import load_entity as _load_tour_proj
                    from apps.goals.domain import _onboarding_tour_on_hold
                    _tp = _load_tour_proj(subject_id)
                    if (_tp
                            and onboarding.onboarding_agenda_in_progress() == _tp.get("goal_id")
                            and onboarding.onboarding_project_kind(_tp.get("name", "")) == "tour"
                            and await asyncio.to_thread(_onboarding_tour_on_hold, dm_to)):
                        return (
                            "That app-tour nudge is on a daily hold — a tour message "
                            "is still unanswered and less than 24h old. Wait for their "
                            "reply before nudging another app tour. DM not sent."
                        )
                except Exception:
                    logger.warning("PM_THINK: onboarding tour-hold DM check failed", exc_info=True)
            if dm_count >= 3:
                return "DM limit reached (max 3 per cycle). DM not sent."
            if dm_to in dm_recipients:
                return f"Already sent a DM to {dm_to} this cycle. DM not sent."
            # One-at-a-time pacing: don't re-nudge if the prior DM to this person
            # ABOUT THIS SAME SUBJECT is still unanswered and < 24h old. Scoped by
            # subject so PM stays independent per project/goal (shared helper).
            from apps.goals.domain import _dm_on_hold
            if await asyncio.to_thread(_dm_on_hold, dm_to, "pm", subject_id):
                return (
                    f"Your previous message to {dm_to} is unanswered and less than "
                    "24h old. Wait for their reply before sending another — DM not sent."
                )

            await _send_thinking_dm(dm_to, dm_text, subject_id)
            dm_count += 1
            dm_recipients.add(dm_to)

            # Create pending_action to track response
            try:
                stype = ("project" if subject_id.startswith("p-") else
                         "goal" if subject_id.startswith("g-") else
                         "task" if subject_id.startswith("t-") else "unknown")
                await asyncio.to_thread(
                    create_state,
                    domain="pm",
                    state_type="pending_action",
                    subject_id=subject_id or "unknown",
                    subject_type=stype,
                    content=json.dumps({
                        "dm_to": dm_to,
                        "dm_text": dm_text[:200],
                        "sent_at": datetime.now(get_timezone()).isoformat(),
                    }),
                    priority="medium",
                )
            except Exception as e:
                logger.error("PM_THINK: Failed to create pending_action for DM to %s: %s", dm_to, e)

            return f"DM sent to {dm_to} about {subject_id}"

        # --- MCP tool dispatch ---
        if routed_tool_names and tool_name not in routed_tool_names:
            return f"Error: Tool '{tool_name}' was not in the routed tool set for this cycle."
        if "created_by" not in tool_args and tool_name.startswith("create_"):
            tool_args["created_by"] = "skipper"
        import tool_dispatch
        return await tool_dispatch.call_tool(tool_name, tool_args)

    async def _pm_after_tool(tool_name: str, tool_args: dict, tool_result: str, tool_call_id: str) -> str | None:
        """Track actions for the cycle result."""
        pm_audit_logger.info("PM_THINK tool [%s]: %s → %s",
                             tool_name, json.dumps(tool_args)[:200], (tool_result or "")[:200])

        if tool_name == "send_dm":
            if "DM sent" in (tool_result or ""):
                actions_taken.append({
                    "type": "dm_sent", "tool": "send_dm",
                    "dm_to": tool_args.get("to_user"), "subject_id": tool_args.get("subject_id"),
                })
            else:
                actions_taken.append({"type": "dm_skipped", "tool": "send_dm", "reason": tool_result})
        elif tool_name == "expire_state":
            actions_taken.append({"type": "expired", "target_id": tool_args.get("state_id")})
        elif tool_name == "resolve_state":
            actions_taken.append({"type": "resolved", "target_id": tool_args.get("state_id")})
        elif tool_name == "update_working_memory":
            memory_updates.append({
                "subject_id": tool_args.get("subject_id"),
                "summary": tool_args.get("summary"),
            })
            actions_taken.append({"type": "memory_updated", "subject_id": tool_args.get("subject_id")})
        else:
            actions_taken.append({
                "type": "tool_executed", "tool": tool_name,
                "result": (tool_result or "")[:300],
            })

        return None  # don't transform the result

    # ---------- RUN AGENT LOOP ----------
    try:
        loop_result = await agent_loop.run(
            messages=messages,
            tools=tools,
            tier=tier,
            max_turns=4,
            max_tool_calls=12,
            tool_dispatch=_pm_dispatch,
            hooks=agent_loop.LoopHooks(
                after_tool_call=_pm_after_tool,
            ),
        )
        reasoning = loop_result.response_text or ""
        tokens_used = loop_result.prompt_tokens + loop_result.completion_tokens
    except Exception as e:
        logger.error("PM_THINK: Agent loop failed: %s", e, exc_info=True)
        pm_audit_logger.info("PM_THINK: Agent loop failed: %s", str(e)[:200])
        reasoning = f"Agent loop failed: {str(e)[:200]}"
        tokens_used = 0

    # ---------- POST-LOOP ----------
    reviewed_pid = ctx.get("reviewed_project_id")
    if reviewed_pid:
        try:
            await asyncio.to_thread(_record_project_review, reviewed_pid)
        except Exception as e:
            logger.error("PM_THINK: Failed to record project review for %s: %s", reviewed_pid, e)

    pm_audit_logger.info("PM_THINK: tier=%s, tokens=%d, actions=%d, project=%s",
                         tier, tokens_used, len(actions_taken),
                         reviewed_pid or "none")

    # Dynamic rhythm: more activity → come back sooner
    dm_sent = sum(1 for a in actions_taken if a.get("type") == "dm_sent")
    if dm_sent > 0:
        next_check = 900   # 15 min — we reached out, check for responses soon
    elif total_items > 5:
        next_check = 600   # 10 min — lots of activity
    elif total_items > 0:
        next_check = 1200  # 20 min — some activity
    else:
        next_check = 1800  # 30 min — quiet

    snap = ctx.get("project_snapshot")
    project_label = f", reviewed {snap['project_name']}" if snap else ""

    # Phase-0 SHADOW WRITE (specs/CONSCIOUSNESS.md §13, §11.6): productive PM
    # cycles log one outcome activity row (Q6). DMs mirror via create_notification.
    _meaningful = [a for a in actions_taken if a.get("type") not in ("dm_skipped",)]
    if _meaningful:
        try:
            from app_platform.consciousness import shadow_log_event
            await asyncio.to_thread(
                shadow_log_event, kind="activity", who_from="skipper", domain="pm",
                subject_id=(snap or {}).get("project_id"),
                content=(f"[pm] reviewed {snap['project_name'] if snap else 'projects'}: "
                         f"{len(_meaningful)} action(s)"),
                payload={"actions": len(_meaningful)},
                pre_attended_by="legacy-pipeline",
            )
        except Exception:
            logger.debug("CONSCIOUSNESS: pm shadow write skipped", exc_info=True)

    return {
        "trigger": "timer",
        "input_summary": (
            f"PM think: {ctx['pending_actions_count']} pending actions, "
            f"{ctx['observations_count']} observations → {len(actions_taken)} actions"
            f"{project_label}"
        ),
        "context_snapshot": _safe_snapshot(ctx),
        "reasoning": reasoning,
        "actions_taken": actions_taken,
        "memories_extracted": memory_updates,
        "model_used": model_tier,
        "tokens_used": tokens_used,
        "next_check_seconds": next_check,
    }


# ---------------------------------------------------------------------------
# OBSERVE — gather context from skipper_state + entity store
# ---------------------------------------------------------------------------

def _consciousness_pm_enabled() -> bool:
    """Phase 3b flag (specs/CONSCIOUSNESS.md §13): PM runs as a SKILL of the one
    consciousness — the scheduler cadence fires an owed alarm event; the
    attention system runs the pm sweep turn (timeline replaces the private
    conversation gatherer; sends via send_message; routes goal work)."""
    try:
        from app_platform import settings as _settings
        v = _settings.get("consciousness_pm", scope="platform", default=False)
        return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


def _observe(include_conversations: bool = True) -> dict:
    """Gather all PM-relevant state + pick a project for deep review + conversation context."""
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

    # --- Conversation context: pull recent chatlogs for people we're tracking ---
    recent_conversations = (
        _gather_conversation_context(pending_actions, project_snapshot)
        if include_conversations else []
    )  # consciousness mode: the TIMELINE supersedes the private gatherer (§12.3)

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
        "recent_conversations": recent_conversations,
        "memories": memories,
        "now": datetime.now(get_timezone()).isoformat(),
    }


def _gather_conversation_context(
    pending_actions: list[dict],
    project_snapshot: dict | None,
) -> dict[str, list[dict]]:
    """Pull recent chatlogs for people the PM is actively tracking.

    Returns: { "person_name": [{"timestamp", "user_message", "assistant_message"}, ...] }
    """
    from data_layer.chatlogs import get_turns_since, get_recent_turns

    conversations: dict[str, list[dict]] = {}

    # 1) People with active pending_actions — pull chats since the DM was sent
    for pa in pending_actions:
        content_raw = pa.get("content", "")
        try:
            content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(content, dict):
            continue

        person = content.get("dm_to", "")
        sent_at = content.get("sent_at") or pa.get("created_at", "")
        if person and sent_at and person not in conversations:
            try:
                turns = get_turns_since(person.lower().strip(), sent_at, limit=10)
                if turns:
                    conversations[person] = turns
            except Exception as e:
                logger.error("PM_THINK: Failed to pull chatlogs for %s: %s", person, e)

    # 2) Project owners/assignees — pull last few messages for awareness
    if project_snapshot:
        people = set()
        for owner in project_snapshot.get("project_owners", []):
            if owner:
                people.add(owner)
        for task in project_snapshot.get("tasks", []):
            for assignee in task.get("assigned_to", []):
                if assignee:
                    people.add(assignee)

        for person in people:
            if person not in conversations:
                try:
                    turns = get_recent_turns(person.lower().strip(), limit=5)
                    # Only include if there are recent messages (last 24h)
                    if turns:
                        cutoff = (datetime.now(get_timezone()) - timedelta(hours=24)).isoformat()
                        recent = [t for t in turns if t.get("timestamp", "") > cutoff]
                        if recent:
                            conversations[person] = recent
                except Exception as e:
                    logger.error("PM_THINK: Failed to pull recent chatlogs for %s: %s", person, e)

    if conversations:
        logger.info("PM_THINK: Loaded conversation context for %d people: %s",
                     len(conversations), list(conversations.keys()))

    return conversations


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
    from apps.goals.lifecycle import _INACTIVE_STATUSES
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
                        from apps.goals.domain import _onboarding_tour_on_hold
                        from data_layer.users import get_primary_user
                        _recip = (get_primary_user() or "").strip().lower()
                        _tour_hold = _onboarding_tour_on_hold(_recip) if _recip else False
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

def _load_pm_think_prompt() -> str:
    """Load the PM thinking system prompt (apps/goals/prompts/pm_think.md).

    Moved into this app's prompts/ dir during packaging; the old path
    (platform PROMPTS_DIR/PM_THINK.md) no longer exists, which silently made
    every PM cycle a no-op.
    """
    path = os.path.join(os.path.dirname(__file__), "prompts", "pm_think.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error("PM_THINK: Prompt file not found: %s", path)
        return ""


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
        from data_layer.users import get_human_users, get_primary_user
        _humans = [u["name"] for u in get_human_users() if u.get("name") != "skipper"]
        _primary = (get_primary_user() or "").strip().lower()
        if _humans:
            _roster = ", ".join(f"{h} (primary)" if h == _primary else h for h in _humans)
            parts.append(f"**Household users (DM only these real usernames):** {_roster}")
            parts.append("When you DM, use one of these exact usernames — default to the primary user. Never invent or use placeholder/example names.\n")
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


def _build_thinking_tools(context_text: str) -> tuple[list[dict], set[str]]:
    """Build the OpenAI tool schemas for the PM thinking loop.

    Uses a fixed category allowlist — PM's job (manage tasks, follow up with
    people, check schedules) is the same regardless of which project it's
    reviewing, so dynamic keyword routing against the briefing text is wrong
    (project names like "Investment App" would pull in finance tools, etc.).

    Returns:
        (tools_list, routed_tool_names) — OpenAI schemas and the set of allowed names.
    """
    import mcp_client
    from tool_router import get_tools_for_categories

    routed_names = get_tools_for_categories(PM_TOOL_CATEGORIES)

    # Filter MCP tools to routed set
    mcp_tools = []
    if mcp_client.mcp_tools:
        all_mcp = mcp_client.get_openai_tools()
        mcp_tools = [t for t in all_mcp if t["function"]["name"] in routed_names]

    # Combine: MCP tools + custom PM tools (DM + state management)
    STATE_TOOLS = [SEND_DM_TOOL, EXPIRE_STATE_TOOL, RESOLVE_STATE_TOOL, UPDATE_WORKING_MEMORY_TOOL]
    tools = mcp_tools + STATE_TOOLS
    # Add custom names to the allowed set for dispatch validation
    routed_names |= {"send_dm", "expire_state", "resolve_state", "update_working_memory"}

    logger.debug("PM_THINK: %d tools (%d MCP + %d state)", len(tools), len(mcp_tools), len(STATE_TOOLS))
    return tools, routed_names


async def _send_thinking_dm(person: str, text: str, subject_id: str = ""):
    """DM a real household user from the PM thinking loop (multi-surface).

    Validates the recipient — an unknown/placeholder name is redirected to the
    primary user so the nudge reaches a real person (never a phantom). Delivers
    via the platform notification path (web UI, Discord, push, chat log), not a
    channel-specific sender. Respects quiet mode.
    """
    if PM_QUIET_MODE:
        pm_audit_logger.info("  → Skipped (quiet mode)")
        logger.info("PM_THINK: DM to %s suppressed (quiet mode)", person)
        return

    from apps.goals.data import resolve_dm_recipient
    recipient = resolve_dm_recipient(person)
    if not recipient:
        logger.warning("PM_THINK: DM dropped — '%s' is not a real user and no primary user is set", person)
        return
    if recipient != (person or "").strip().lower():
        logger.warning("PM_THINK: recipient '%s' is not a real user — redirecting to primary user '%s'", person, recipient)

    pm_audit_logger.info("PM_THINK DM → %s (re: %s): %s", recipient, subject_id, text[:200])
    try:
        from app_platform.notifications import create_notification
        await asyncio.to_thread(
            create_notification,
            recipient=recipient,
            message=text,
            source_type="pm_thinking",
            source_id=subject_id or "",
            channel="all",
            delivered=False,
        )
        pm_audit_logger.info("  → Sent OK to %s", recipient)
    except Exception as e:
        logger.error("PM_THINK: Failed to notify %s: %s", recipient, e)
        pm_audit_logger.info("  → FAILED: %s", str(e))


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
)

_SEND_MESSAGE_TOOL_PM = {
    "type": "function",
    "function": {
        "name": "send_message",
        "description": "Send one chat message to one family member (as Skipper's own voice).",
        "parameters": {"type": "object", "properties": {
            "to_user": {"type": "string"}, "message": {"type": "string"}},
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

    ctx = await asyncio.to_thread(_observe, False)
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
            row = await asyncio.to_thread(
                lambda: send_message(who_to=to_user, content=args.get("message") or "",
                                     domain="pm", payload={"pm_review": event.get("id")}))
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

    await agent_loop.run(
        messages=[
            {"role": "system", "content": _PM_SKILL_GUIDANCE},
            {"role": "system", "content": "STRUCTURED PM STATE:\n" + state},
            *timeline,
            {"role": "user", "content": "[alarm] ⏰ pm review time — sweep, follow up, route work. Silence is fine."},
        ],
        tools=tools, tier="smart", max_turns=4, max_tool_calls=10,
        tool_dispatch=_dispatch,
    )
    return {"summary": f"pm sweep: {len(actions_taken)} action(s) "
                       f"({len(messaged)} msg, {len(scheduled)} work session(s))"}
