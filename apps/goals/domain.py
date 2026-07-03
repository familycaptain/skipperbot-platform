"""
Goal Domain Module
==================
Generic thinking-domain handler for goals assigned to Skipper.

Each goal owned by Skipper gets its own thinking domain whose name IS the
goal ID (e.g. ``g-b9cd5ae6``).  The handler loads the full goal context
(projects, tasks, notes, DoD) and runs the agent loop so Skipper can
analyse health, create tasks, DM collaborators, and do research.

The handler is registered via a pattern match in domain_modules.py:
any domain name starting with ``g-`` routes here.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta

from config import logger, PROMPTS_DIR
from app_platform.time import get_timezone
import agent_loop
# Threshold: below this many state items we use the cheaper model
CHEAP_MODEL_THRESHOLD = 5

# Tool categories always available to goal domains (beyond keyword routing)
BASELINE_CATEGORIES = {"core", "goals", "docs", "knowledge", "research", "web"}


# ---------------------------------------------------------------------------
# Custom tool schemas (same pattern as PM domain)
# ---------------------------------------------------------------------------

SEND_DM_TOOL = {
    "type": "function",
    "function": {
        "name": "send_dm",
        "description": "Send a direct message to a family member. Automatically creates a pending_action to track the conversation. Max 3 DMs per cycle.",
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

EXPIRE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "expire_state",
        "description": "Expire/close a skipper_state entry permanently.",
        "parameters": {
            "type": "object",
            "properties": {
                "state_id": {"type": "string", "description": "The ss-xxx ID to expire"},
            },
            "required": ["state_id"],
        },
    },
}

RESOLVE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve_state",
        "description": "Mark a skipper_state entry as reviewed/acknowledged.",
        "parameters": {
            "type": "object",
            "properties": {
                "state_id": {"type": "string", "description": "The ss-xxx ID to resolve"},
            },
            "required": ["state_id"],
        },
    },
}

UPDATE_WORKING_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "update_working_memory",
        "description": "Save or update a note in your working memory about an entity. Persists across thinking cycles.",
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


# =========================================================================
# Handler entry point
# =========================================================================

# The onboarding goal gets special "live agent" treatment (real-time cadence,
# one item at a time, 1-month auto-close). Identified by its fixed seed name.
ONBOARDING_GOAL_NAME = "Get started with Skipper"

# Notification source_type for the live first-contact arrival greeting. Delivery
# (apps/notifications/delivery._deliver_one) recognizes this source and pushes it
# over the WS as a typing-clearing `chat_response` frame (live render = chat
# bubble), while it still persists/reloads from history as a notification row —
# consistent with other proactive DMs (platform.onboarding.live-greeting).
ONBOARDING_GREETING_SOURCE = "onboarding_greeting"

# Appended to the goal-think user prompt on a live ARRIVAL cycle so the model
# opens with a warm first-contact hello instead of a mid-conversation nudge.
_FIRST_CONTACT_FRAMING = """
## FIRST CONTACT — LIVE ARRIVAL GREETING (act now)
{who} just arrived on their desktop for the FIRST TIME, moments after finishing setup.
This is your VERY FIRST message to them — a live hello, NOT a resumed conversation.
- Greet them warmly and BY NAME ({who}) in 1-2 short sentences — like a present
  person saying hi, not a wall of text.
- Then OPEN the current (first not-done) agenda topic above as a single friendly
  question — introduce it fresh; assume no prior context.
- Use send_dm to {who} (the primary user). Send at most TWO short bubbles (a warm
  opener, then the first agenda prompt), then STOP and yield so they can reply.
  Do NOT dump the whole agenda.
"""


def _first_contact_framing() -> str:
    """First-contact greeting instructions, personalized with the primary user's name."""
    try:
        from data_layer.users import get_primary_user
        who = (get_primary_user() or "").strip() or "the primary user"
    except Exception:
        who = "the primary user"
    return _FIRST_CONTACT_FRAMING.format(who=who)


def _user_recently_active(username: str, within_minutes: int = 15) -> bool:
    """True if the user has chatted within the last ``within_minutes``.

    Drives the onboarding "live agent" cadence: when the primary user is around,
    Skipper comes back in seconds for real-time back-and-forth; when they go
    quiet, it backs off.
    """
    name = (username or "").strip().lower()
    if not name:
        return False
    try:
        from data_layer.chatlogs import get_recent_turns
        from datetime import datetime, timezone
        turns = get_recent_turns(name, limit=1)
        if not turns:
            return False
        ts = turns[-1].get("created_at")
        if not ts:
            return False
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if isinstance(ts, str) else ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() < within_minutes * 60
    except Exception:
        return False


def _dm_hold_core(recipient: str, rows: list) -> bool:
    """Shared engagement/24h hold decision over a candidate set of pending DMs.

    Given ``rows`` (pending_action rows already scoped to the caller's domain(s)
    and subject-set), select the SINGLE most-recent DM to ``recipient`` by
    ``sent_at`` and hold IFF it is < 24h old AND still has no genuine reply.

    ONE definition of "engaged" (a real, non-marker user turn after the DM) and
    ONE 24h daily floor, shared by the per-subject hold (``_dm_on_hold``) and the
    global onboarding-tour hold (``_onboarding_tour_on_hold``) so the two can
    never drift. Conservative on error — never blocks indefinitely.
    """
    recip = (recipient or "").strip().lower()
    if not recip:
        return False
    try:
        import json
        from datetime import datetime, timezone, timedelta
        from data_layer.chatlogs import get_turns_since

        latest = ""
        for r in rows:
            raw = r.get("content", "")
            try:
                c = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(c, dict):
                continue
            if (c.get("dm_to", "") or "").strip().lower() != recip:
                continue
            sent = c.get("sent_at") or r.get("created_at") or ""
            if sent and sent > latest:
                latest = sent
        if not latest:
            return False  # no prior DM to this person — fine to send

        sent_dt = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
        if sent_dt.tzinfo is None:
            sent_dt = sent_dt.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - sent_dt) >= timedelta(hours=24):
            return False  # daily floor reached — a check-in is allowed

        # Replied since? A real (non-marker) user turn after the DM = engaged.
        turns = get_turns_since(recip, latest, limit=5)
        replied = any(
            (t.get("user_message", "") or "").strip()
            and not (t.get("user_message", "") or "").startswith("[")
            for t in turns
        )
        return not replied  # hold only if unanswered and < 24h old
    except Exception:
        return False


def _dm_on_hold(recipient: str, domain_name: str, subject_id: str = "") -> bool:
    """True if the most recent proactive DM to ``recipient`` is still UNANSWERED
    and less than 24h old — enforce one-at-a-time pacing.

    Scope matters so independent threads don't block each other:
      * Each goal worker has its OWN domain (the goal id), so this query never
        sees another goal's pending DMs — different goals are isolated for free.
      * The PM domain is a SINGLE domain spanning many projects/goals, so it
        passes ``subject_id`` to scope the hold to just that thread — a held
        nudge about one project won't silence a different one to the same person.

    Send one, then wait for a reply. Exception: once 24h passes with no reply, a
    single check-in is allowed (the caller's per-cycle cap still applies).
    Conservative on error — never blocks indefinitely.
    """
    recip = (recipient or "").strip().lower()
    if not recip:
        return False
    subj = (subject_id or "").strip()
    subj_filter = subj if subj and subj != "unknown" else ""
    try:
        from data_layer.skipper_state import list_states

        rows = list_states(domain=domain_name, state_type="pending_action",
                           status="active", limit=50)
        # Per-subject scoping (PM): only this thread's pending DMs hold it.
        if subj_filter:
            rows = [r for r in rows if (r.get("subject_id") or "") == subj_filter]
        return _dm_hold_core(recip, rows)
    except Exception:
        return False


def _onboarding_tour_on_hold(recipient: str) -> bool:
    """GLOBAL onboarding app-tour cadence hold (ev-75).

    True when a "Try the {app}" tour nudge for the IN-PROGRESS onboarding goal is
    still unanswered and < 24h old — holding ALL tour nudges (not just that app's)
    so a no-reply can't march the app catalog to a different tour each cycle. The
    per-subject ``_dm_on_hold`` can't do this: the PM selector switches apps every
    cycle, so each nudge is a fresh ``subject_id`` and the per-subject hold misses.

    CORRECTNESS: unions pending_action across BOTH the PM domain AND the
    onboarding goal's OWN domain (goal-domain tour DMs are filed under
    ``domain=goal_id``, not ``'pm'``) into ONE pool, keeps only rows whose subject
    is a tour project of that goal, then runs the SINGLE shared 24h/engagement
    check on the global-latest DM — NOT a per-domain OR (which would falsely hold
    when the newest tour DM is replied-to but an older one is still < 24h open).
    Conservative on error — never blocks indefinitely.
    """
    recip = (recipient or "").strip().lower()
    if not recip:
        return False
    try:
        from apps.goals import onboarding
        from apps.goals.data import load_entity
        from data_layer.skipper_state import list_states

        onb_goal = onboarding.onboarding_agenda_in_progress()
        if not onb_goal:
            return False  # onboarding not in progress — no tour hold

        # Union pending_action rows across BOTH domains into ONE pool.
        pool = []
        for dom in ("pm", onb_goal):
            pool.extend(list_states(domain=dom, state_type="pending_action",
                                    status="active", limit=50))

        # Keep only rows whose subject is a TOUR project of THIS onboarding goal.
        proj_cache: dict = {}
        tour_rows = []
        for r in pool:
            sid = (r.get("subject_id") or "").strip()
            if not sid.startswith("p-"):
                continue
            if sid not in proj_cache:
                proj_cache[sid] = load_entity(sid)
            proj = proj_cache[sid]
            if not proj or proj.get("goal_id") != onb_goal:
                continue
            if onboarding.onboarding_project_kind(proj.get("name", "")) != "tour":
                continue
            tour_rows.append(r)

        # ONE shared engagement/24h check on the single global-latest tour DM.
        return _dm_hold_core(recip, tour_rows)
    except Exception:
        return False


def _past_target_date(goal_snap: dict) -> bool:
    """True if the goal's target date is in the past (onboarding 1-month window)."""
    td = (goal_snap or {}).get("goal_target_date") or ""
    if not td:
        return False
    try:
        from datetime import date
        return date.fromisoformat(str(td)[:10]) < date.today()
    except Exception:
        return False


async def goal_domain_handler(domain: dict, budget_status: dict) -> dict:
    """Run one thinking cycle for a goal domain.

    ``domain["name"]`` is the goal ID (e.g. ``g-b9cd5ae6``).

    ``domain["arrival"]`` (optional) marks an event-driven LIVE arrival cycle
    for the onboarding goal (platform.onboarding.live-greeting): the produce
    path switches to a warm FIRST-CONTACT greeting (personalized, opening — not
    resuming — the current agenda step) delivered as a typing-clearing frame.
    """
    goal_id = domain["name"]
    # First-contact live arrival greeting (vs the normal timer-driven nudge cycle).
    is_arrival = bool(domain.get("arrival"))

    # ---------- OBSERVE ----------
    ctx = await asyncio.to_thread(_observe, goal_id, domain["name"])

    if ctx.get("error"):
        return _skip_result(ctx["error"], next_check=3600)

    total_items = ctx["pending_actions_count"] + ctx["observations_count"]
    goal_snap = ctx.get("goal_snapshot")

    # Nothing to review and no goal context — sleep long
    if total_items == 0 and not goal_snap:
        return _skip_result("Goal not found or no context — quiet cycle.", next_check=3600)

    # Inactive goals — skip entirely and self-heal the domain
    goal_status = (goal_snap.get("goal_status", "") if goal_snap else "").lower()
    if goal_status in ("done", "deferred", "archived", "cancelled"):
        try:
            from goal_domain_lifecycle import sync_goal_domain
            await asyncio.to_thread(sync_goal_domain, goal_id)
        except Exception:
            pass
        return _skip_result(f"Goal is {goal_status} — disabling domain.", next_check=86400)

    # Onboarding goal: auto-close after its 1-month window elapses (close out
    # as-is regardless of completion), which also disables this domain.
    is_onboarding = bool(goal_snap and goal_snap.get("goal_name") == ONBOARDING_GOAL_NAME)
    if is_onboarding and _past_target_date(goal_snap):
        try:
            # Reuse the single canonical close-out path: cascades open children and
            # disables this domain. Timeout closes as 'done' ("completed the window"),
            # unlike a user-requested stop which closes as 'cancelled'.
            from apps.goals.store import close_out_goal
            await asyncio.to_thread(
                close_out_goal, goal_id, by="skipper", status="done",
                reason="Onboarding window (1 month) elapsed — closing out as-is.",
            )
        except Exception as e:
            logger.warning("GOAL_THINK[%s]: onboarding auto-close failed: %s", goal_id, e)
        return _skip_result("Onboarding window elapsed — closed out.", next_check=86400)

    # Ownership gate: only think if Skipper actually owns something under this goal
    if goal_snap and not _skipper_owns_anything(goal_snap):
        return _skip_result(
            "No projects or tasks assigned to Skipper yet — nothing to work on.",
            next_check=1800,
        )

    # ---------- SET FOCUS ----------
    goal_name = goal_snap.get("goal_name", goal_id) if goal_snap else goal_id
    focus_desc = f"Working on goal: {goal_name}"
    try:
        from data_layer.skipper_state import upsert_focus
        await asyncio.to_thread(upsert_focus, goal_id, goal_id, "goal", focus_desc)
    except Exception as e:
        logger.warning("GOAL_THINK[%s]: Failed to set focus: %s", goal_id, e)

    # ---------- MODEL SELECTION ----------
    # The cheap/standard decision maps to a model TIER (MODEL_FLEXIBILITY #44/#71); agent_loop
    # resolves the connector+model+key from the tier. No raw model id / OPENAI_API_KEY here.
    tier = "fast" if total_items <= CHEAP_MODEL_THRESHOLD else "smart"
    model_tier = "cheap" if tier == "fast" else "standard"

    # Always use the smart tier for goals with many projects/tasks
    if goal_snap and goal_snap.get("total_task_count", 0) > 10:
        tier = "smart"
        model_tier = "standard"

    remaining = budget_status.get("remaining", 999_999)
    if remaining < 50_000 and tier == "smart":
        tier = "fast"
        model_tier = "cheap"
        logger.info("GOAL_THINK[%s]: Downgraded to fast tier — budget low (%d remaining)",
                     goal_id, remaining)

    # ---------- BUILD MESSAGES + TOOLS ----------
    static_system = _load_prompt()
    if not static_system:
        return _skip_result("No GOAL_THINK.md prompt file", next_check=3600)

    user_prompt = _build_user_prompt(ctx)
    tools, routed_tool_names = _build_tools(user_prompt)

    # Live arrival cycle: prepend warm first-contact greeting framing so the model
    # opens with a personalized hello (not a mid-conversation nudge).
    if is_onboarding and is_arrival:
        user_prompt = user_prompt + "\n\n" + _first_contact_framing()

    from tool_router import get_guides_for_categories
    # Baseline guides are a fixed set — appended to static system for caching
    guide_content = get_guides_for_categories(BASELINE_CATEGORIES)
    if guide_content:
        static_system += "\n\n## Tool Guides (reference)\n\n" + guide_content

    messages = [
        {"role": "system", "content": static_system},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("GOAL_THINK[%s]: Calling %s tier — %d pending, %d observations, %d tools",
                goal_id, tier, ctx["pending_actions_count"],
                ctx["observations_count"], len(tools))

    # ---------- TOOL DISPATCH + HOOKS ----------
    actions_taken: list[dict] = []
    memory_updates: list[dict] = []
    dm_count = 0
    dm_recipients: set[str] = set()
    domain_name = domain["name"]

    async def _dispatch(tool_name: str, tool_args: dict) -> str:
        nonlocal dm_count
        from data_layer.skipper_state import (
            expire_state as _expire, resolve_state as _resolve,
            upsert_working_memory as _upsert_wm, create_state,
        )

        if tool_name == "expire_state":
            sid = tool_args.get("state_id", "")
            await asyncio.to_thread(_expire, sid)
            return f"Expired state entry {sid}"

        if tool_name == "resolve_state":
            sid = tool_args.get("state_id", "")
            await asyncio.to_thread(_resolve, sid)
            return f"Resolved state entry {sid}"

        if tool_name == "update_working_memory":
            sid = tool_args.get("subject_id", "")
            summary = tool_args.get("summary", "")
            stype = ("project" if sid.startswith("p-") else
                     "goal" if sid.startswith("g-") else
                     "task" if sid.startswith("t-") else "unknown")
            await asyncio.to_thread(_upsert_wm, domain_name, sid, stype, summary)
            return f"Working memory updated for {sid}"

        if tool_name == "send_dm":
            dm_to = tool_args.get("to_user", "").lower().strip()
            dm_text = tool_args.get("message", "")
            subject_id = tool_args.get("subject_id", "")
            if not dm_to or not dm_text:
                return "Error: to_user and message are required"
            if dm_to == "skipper":
                return "You cannot DM yourself. DM not sent."
            # Produce-layer tour gate (defect 1a, layer 2): the snapshot-filter
            # alone is defeatable — the goal agent's baseline read tools
            # (get_goal_detail/search_goals) can enumerate the hidden tour
            # projects and the goal_id is printed in-prompt, so block a DM whose
            # subject resolves to a gated tour project. tour_gated() self-gates on
            # the in-progress onboarding goal, so normal goals are untouched.
            if is_onboarding and subject_id:
                try:
                    from apps.goals import onboarding
                    if onboarding.tour_gated(goal_id, subject_id):
                        return (
                            "That DM is about an app tour, but the ordered setup "
                            "agenda isn't complete yet. Finish the agenda projects "
                            "first — app tours come after. DM not sent."
                        )
                except Exception:
                    logger.warning("GOAL_THINK[%s]: tour-gate DM check failed", goal_id, exc_info=True)
            # Global onboarding app-tour CADENCE hold (ev-75, site 3): once the
            # agenda is complete tours pass the ORDER gate above, so hold ALL tour
            # nudges for ~24h while a prior tour DM is unanswered — a no-reply must
            # not march the catalog to a different app. Defense-in-depth parity
            # with the PM domain guards; the per-subject _dm_on_hold below still
            # paces everything else. tour_gated (ORDER) is untouched.
            if is_onboarding and subject_id and subject_id.startswith("p-"):
                try:
                    from apps.goals import onboarding
                    from apps.goals.data import load_entity as _load_tour_proj
                    _tp = _load_tour_proj(subject_id)
                    if (_tp and _tp.get("goal_id") == goal_id
                            and onboarding.onboarding_project_kind(_tp.get("name", "")) == "tour"
                            and await asyncio.to_thread(_onboarding_tour_on_hold, dm_to)):
                        return (
                            "That app-tour nudge is on a daily hold — a tour message "
                            "is still unanswered and less than 24h old. Wait for their "
                            "reply before nudging another app tour. DM not sent."
                        )
                except Exception:
                    logger.warning("GOAL_THINK[%s]: onboarding tour-hold DM check failed", goal_id, exc_info=True)
            # Onboarding is a live, one-at-a-time conversation — a single DM per
            # cycle. The first-contact live arrival greeting is allowed TWO short
            # bubbles (a warm opener + the first agenda prompt). Other goals keep
            # the looser cap.
            _cap = (2 if (is_onboarding and is_arrival) else 1) if is_onboarding else 3
            if dm_count >= _cap:
                return f"DM limit reached (max {_cap} per cycle). DM not sent."
            # The first-contact arrival burst is an INTENTIONAL 2-bubble greeting
            # to the same primary user, so it bypasses the same-recipient and
            # one-at-a-time gates below (the cap still bounds it to 2). The
            # pending_action rows it writes still HOLD the later cadence cycle.
            _arrival_burst = is_onboarding and is_arrival
            if dm_to in dm_recipients and not _arrival_burst:
                return f"Already sent a DM to {dm_to} this cycle. DM not sent."
            # One-at-a-time pacing: if the prior DM to this person is still
            # unanswered and < 24h old, hold and wait for their reply.
            if not _arrival_burst and await asyncio.to_thread(_dm_on_hold, dm_to, domain_name):
                return (
                    f"Your previous message to {dm_to} is unanswered and less than "
                    "24h old. Wait for their reply before sending another — DM not sent."
                )

            # On a live arrival cycle the greeting delivers as a chat_response
            # bubble (clears the client's optimistic typing) via this source_type.
            _dm_source = ONBOARDING_GREETING_SOURCE if (is_onboarding and is_arrival) else "goal_thinking"
            await _send_dm(dm_to, dm_text, subject_id, source_type=_dm_source)
            dm_count += 1
            dm_recipients.add(dm_to)

            # Track pending_action
            try:
                stype = ("project" if subject_id.startswith("p-") else
                         "goal" if subject_id.startswith("g-") else
                         "task" if subject_id.startswith("t-") else "unknown")
                await asyncio.to_thread(
                    create_state,
                    domain=domain_name,
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
                logger.error("GOAL_THINK[%s]: Failed to create pending_action: %s", goal_id, e)

            return f"DM sent to {dm_to} about {subject_id}"

        # --- MCP tool dispatch ---
        if routed_tool_names and tool_name not in routed_tool_names:
            return f"Error: Tool '{tool_name}' was not in the routed tool set."
        if "created_by" not in tool_args and tool_name.startswith("create_"):
            tool_args["created_by"] = "skipper"
        import tool_dispatch
        return await tool_dispatch.call_tool(tool_name, tool_args)

    async def _after_tool(tool_name: str, tool_args: dict, tool_result: str, tool_call_id: str) -> str | None:
        if tool_name == "send_dm":
            if "DM sent" in (tool_result or ""):
                actions_taken.append({"type": "dm_sent", "tool": "send_dm",
                                      "dm_to": tool_args.get("to_user"),
                                      "subject_id": tool_args.get("subject_id")})
            else:
                actions_taken.append({"type": "dm_skipped", "tool": "send_dm", "reason": tool_result})
        elif tool_name == "expire_state":
            actions_taken.append({"type": "expired", "target_id": tool_args.get("state_id")})
        elif tool_name == "resolve_state":
            actions_taken.append({"type": "resolved", "target_id": tool_args.get("state_id")})
        elif tool_name == "update_working_memory":
            memory_updates.append({"subject_id": tool_args.get("subject_id"),
                                   "summary": tool_args.get("summary")})
            actions_taken.append({"type": "memory_updated", "subject_id": tool_args.get("subject_id")})
        else:
            actions_taken.append({"type": "tool_executed", "tool": tool_name,
                                  "result": (tool_result or "")[:300]})
        return None

    # ---------- RUN AGENT LOOP ----------
    try:
        loop_result = await agent_loop.run(
            messages=messages,
            tools=tools,
            tier=tier,
            max_turns=8,
            max_tool_calls=25,
            tool_dispatch=_dispatch,
            hooks=agent_loop.LoopHooks(after_tool_call=_after_tool),
        )
        reasoning = loop_result.response_text or ""
        tokens_used = loop_result.prompt_tokens + loop_result.completion_tokens
    except Exception as e:
        logger.error("GOAL_THINK[%s]: Agent loop failed: %s", goal_id, e, exc_info=True)
        reasoning = f"Agent loop failed: {str(e)[:200]}"
        tokens_used = 0

    # ---------- DYNAMIC RHYTHM ----------
    dm_sent = sum(1 for a in actions_taken if a.get("type") == "dm_sent")
    if is_onboarding:
        # Live-agent feel: when the primary user is around, come back in ~45s for
        # real-time back-and-forth; when they go quiet, back off hard so we don't
        # hound them (the prompt keeps it to ~one gentle check-in per day).
        from data_layer.users import get_primary_user
        _primary = (get_primary_user() or "").strip().lower()
        next_check = 45 if _user_recently_active(_primary) else 3600
    elif dm_sent > 0:
        next_check = 900       # 15 min — waiting for replies
    elif total_items > 5:
        next_check = 600       # 10 min
    elif total_items > 0:
        next_check = 1200      # 20 min
    else:
        next_check = 1800      # 30 min

    goal_name = goal_snap.get("goal_name", goal_id) if goal_snap else goal_id

    return {
        "trigger": "timer",
        "input_summary": (
            f"Goal [{goal_name}]: {ctx['pending_actions_count']} pending, "
            f"{ctx['observations_count']} observations → {len(actions_taken)} actions"
        ),
        "context_snapshot": _safe_snapshot(ctx),
        "reasoning": reasoning,
        "actions_taken": actions_taken,
        "memories_extracted": memory_updates,
        "model_used": model_tier,
        "tokens_used": tokens_used,
        "next_check_seconds": next_check,
    }


# =========================================================================
# OBSERVE — load goal + all children + state
# =========================================================================

def _observe(goal_id: str, domain_name: str) -> dict:
    """Gather full goal context + skipper_state for this domain."""
    from apps.goals.data import load_entity, get_top_level_tasks, get_subtasks
    from data_layer.skipper_state import list_states, get_due_actions

    goal = load_entity(goal_id)
    if not goal:
        return {"error": f"Goal {goal_id} not found"}

    # Build full snapshot
    goal_snapshot = _build_goal_snapshot(goal)

    # Pending actions for THIS domain
    pending_actions = list_states(
        domain=domain_name, state_type="pending_action", status="active", limit=20,
    )
    overdue_actions = get_due_actions(domain=domain_name)
    overdue_ids = {a["id"] for a in overdue_actions}

    # Observations for this domain
    observations = list_states(
        domain=domain_name, state_type="observation", status="active", limit=30,
    )

    # Working memory for this domain
    working_memory = list_states(
        domain=domain_name, state_type="working_memory", status="active", limit=20,
    )

    # Memory recall — search shared memory store for context about this goal
    memories = _recall_memories(goal_id, goal_snapshot)

    return {
        "goal_id": goal_id,
        "goal_snapshot": goal_snapshot,
        "pending_actions": pending_actions,
        "pending_actions_count": len(pending_actions),
        "overdue_ids": overdue_ids,
        "observations": observations,
        "observations_count": len(observations),
        "working_memory": working_memory,
        "working_memory_count": len(working_memory),
        "memories": memories,
        "now": datetime.now(get_timezone()).isoformat(),
    }


def _build_goal_snapshot(goal: dict) -> dict:
    """Build a comprehensive snapshot of the goal and all its children."""
    from apps.goals.data import load_entity, get_top_level_tasks, get_subtasks

    # Pre-load project entities so onboarding tour-gating (defect 1a, layer 1)
    # can EXCLUDE the per-app "Try the {app}" tour projects while the ordered
    # setup agenda is still open. Filtering HERE keeps the snapshot, the memory
    # recall, AND the total/done progress counts all free of tours, so the goal
    # LLM never sees — and thus can't nudge — an app tour early. Gated on the
    # onboarding goal only via the shared tour_gated() helper.
    loaded = []
    for pid in goal.get("projects", []):
        proj = load_entity(pid)
        if not proj:
            continue
        loaded.append((pid, proj))

    if goal.get("name", "") == ONBOARDING_GOAL_NAME:
        try:
            from apps.goals import onboarding
            proj_entities = [p for _, p in loaded]
            loaded = [
                (pid, proj) for (pid, proj) in loaded
                if not onboarding.tour_gated(goal, proj, projects=proj_entities)
            ]
        except Exception:
            logger.warning("GOAL_THINK: onboarding tour-gate snapshot filter failed", exc_info=True)

    projects = []
    total_task_count = 0
    total_done = 0
    total_blocked = 0

    for pid, proj in loaded:
        top_tasks = get_top_level_tasks(pid)
        task_summaries = []
        p_counts = {"total": 0, "done": 0, "in_progress": 0, "blocked": 0, "not_started": 0}

        for t in top_tasks:
            p_counts["total"] += 1
            status = t.get("status", "not_started")
            p_counts[status] = p_counts.get(status, 0) + 1

            task_info = {
                "id": t["id"],
                "name": t["name"],
                "status": status,
                "assigned_to": t.get("assigned_to", []),
                "due_date": t.get("due_date", ""),
                "priority": t.get("priority", ""),
                "notes": (t.get("notes", "") or "")[:200],
            }

            subs = get_subtasks(t["id"])
            if subs:
                task_info["subtasks"] = []
                for s in subs:
                    p_counts["total"] += 1
                    s_status = s.get("status", "not_started")
                    p_counts[s_status] = p_counts.get(s_status, 0) + 1
                    task_info["subtasks"].append({
                        "id": s["id"],
                        "name": s["name"],
                        "status": s_status,
                        "assigned_to": s.get("assigned_to", []),
                        "due_date": s.get("due_date", ""),
                    })

            task_summaries.append(task_info)

        total_task_count += p_counts["total"]
        total_done += p_counts.get("done", 0)
        total_blocked += p_counts.get("blocked", 0)

        projects.append({
            "id": pid,
            "name": proj.get("name", ""),
            "status": proj.get("status", ""),
            "priority": proj.get("priority", "medium"),
            "owners": proj.get("owners", []),
            "due_date": proj.get("due_date", ""),
            "notes": (proj.get("notes", "") or "")[:300],
            "definition_of_done": (proj.get("definition_of_done", "") or "")[:300],
            "recent_history": (proj.get("history") or [])[-5:],
            "task_counts": p_counts,
            "tasks": task_summaries,
        })

    return {
        "goal_id": goal["id"],
        "goal_name": goal.get("name", ""),
        "goal_status": goal.get("status", ""),
        "goal_owners": goal.get("owners", []),
        "goal_collaborators": goal.get("collaborators", []),
        "goal_target_date": goal.get("target_date", ""),
        "goal_notes": (goal.get("notes", "") or "")[:500],
        "goal_definition_of_done": (goal.get("definition_of_done", "") or "")[:300],
        "goal_recent_history": (goal.get("history") or [])[-5:],
        "projects": projects,
        "total_task_count": total_task_count,
        "total_done": total_done,
        "total_blocked": total_blocked,
    }


def _recall_memories(goal_id: str, goal_snapshot: dict) -> list[dict]:
    """Search the shared memory store for memories relevant to this goal.

    Searches by entity ID (goal + project IDs) and semantic similarity
    to the goal name. This gives the domain cross-domain context — e.g.
    facts from chat conversations about the goal's projects.
    """
    try:
        from memory_store import search_memories, format_memories_for_context

        goal_name = goal_snapshot.get("goal_name", "")
        # Collect all entity IDs under this goal for broader matching
        entity_ids = [goal_id]
        for proj in goal_snapshot.get("projects", []):
            entity_ids.append(proj["id"])

        # Semantic search using goal name as query + entity ID boost
        all_memories: list[dict] = []
        seen_ids: set[str] = set()

        # Primary search: by goal ID + goal name
        results = search_memories(
            query_text=f"{goal_name} goal progress tasks",
            entity_id=goal_id,
            max_results=5,
        )
        for m in results:
            if m["id"] not in seen_ids:
                seen_ids.add(m["id"])
                all_memories.append(m)

        # Secondary: search by each project ID (capped to keep cost down)
        for pid in entity_ids[1:3]:  # max 2 projects
            results = search_memories(
                entity_id=pid,
                max_results=3,
            )
            for m in results:
                if m["id"] not in seen_ids:
                    seen_ids.add(m["id"])
                    all_memories.append(m)

        logger.info("GOAL_THINK[%s]: Recalled %d memories from shared store",
                     goal_id, len(all_memories))
        return all_memories[:8]  # cap total

    except Exception as e:
        logger.warning("GOAL_THINK[%s]: Memory recall failed: %s", goal_id, e)
        return []


# =========================================================================
# BUILD PROMPT
# =========================================================================

def _load_prompt() -> str:
    # The goal-worker prompt lives in THIS app's prompts/ dir
    # (apps/goals/prompts/goals_think.md) — it was moved there during packaging.
    # The old path (platform PROMPTS_DIR/GOAL_THINK.md) no longer exists, which
    # silently made every goal-thinking cycle a no-op.
    path = os.path.join(os.path.dirname(__file__), "prompts", "goals_think.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error("GOAL_THINK: Prompt file not found: %s", path)
        return ""


def _build_user_prompt(ctx: dict) -> str:
    """Assemble the user prompt from goal snapshot + state."""
    parts = [f"**Current time:** {ctx['now']}\n"]

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

    overdue_ids = ctx.get("overdue_ids", set())
    snap = ctx.get("goal_snapshot")

    if snap:
        parts.append("## Your Assigned Goal")
        parts.append(f"**{snap['goal_name']}** (`{snap['goal_id']}`)")
        parts.append(f"- Status: {snap['goal_status']}")
        parts.append(f"- Owners: {', '.join(snap['goal_owners']) if snap['goal_owners'] else 'skipper'}")
        if snap.get("goal_collaborators"):
            parts.append(f"- Collaborators: {', '.join(snap['goal_collaborators'])}")
        if snap.get("goal_target_date"):
            parts.append(f"- Target date: {snap['goal_target_date']}")
        if snap.get("goal_definition_of_done"):
            parts.append(f"- Definition of done: {snap['goal_definition_of_done']}")
        if snap.get("goal_notes"):
            parts.append(f"- Notes: {snap['goal_notes']}")
        if snap.get("goal_recent_history"):
            parts.append("\n**Recent goal history (READ THESE - may contain owner directives):**")
            for h in snap["goal_recent_history"]:
                ts = (h.get("timestamp") or "")[:16]
                parts.append(f"- [{ts}] ({h.get('by', '')}): {h.get('note', '')}")

        parts.append(f"\n**Overall progress:** {snap['total_done']}/{snap['total_task_count']} tasks done, "
                      f"{snap['total_blocked']} blocked")

        # Projects
        for proj in snap.get("projects", []):
            parts.append(f"\n### Project: {proj['name']} (`{proj['id']}`)")
            parts.append(f"- Status: {proj['status']} | Priority: {proj['priority']}")
            parts.append(f"- Owners: {', '.join(proj['owners']) if proj['owners'] else 'unassigned'}")
            if proj.get("due_date"):
                parts.append(f"- Due: {proj['due_date']}")
            tc = proj.get("task_counts", {})
            parts.append(f"- Tasks: {tc.get('total', 0)} total — {tc.get('done', 0)} done, "
                          f"{tc.get('in_progress', 0)} in progress, {tc.get('blocked', 0)} blocked, "
                          f"{tc.get('not_started', 0)} not started")
            if proj.get("definition_of_done"):
                parts.append(f"- Definition of done: {proj['definition_of_done']}")
            if proj.get("notes"):
                parts.append(f"- Notes: {proj['notes']}")
            if proj.get("recent_history"):
                parts.append("\n**Recent project history (READ THESE - may contain owner directives):**")
                for h in proj["recent_history"]:
                    ts = (h.get("timestamp") or "")[:16]
                    parts.append(f"- [{ts}] ({h.get('by', '')}): {h.get('note', '')}")

            # Tasks
            if proj.get("tasks"):
                parts.append("\n**Tasks:**")
                for t in proj["tasks"]:
                    assignees = ", ".join(t.get("assigned_to", [])) if t.get("assigned_to") else "unassigned"
                    due = f" due:{t['due_date']}" if t.get("due_date") else ""
                    pri = f" [{t['priority']}]" if t.get("priority") else ""
                    parts.append(f"- **{t['name']}** (`{t['id']}`) — {t['status']}{pri} — {assignees}{due}")
                    if t.get("notes"):
                        parts.append(f"  Notes: {t['notes']}")
                    for sub in t.get("subtasks", []):
                        s_assignees = ", ".join(sub.get("assigned_to", [])) if sub.get("assigned_to") else "unassigned"
                        s_due = f" due:{sub['due_date']}" if sub.get("due_date") else ""
                        parts.append(f"  - {sub['name']} (`{sub['id']}`) — {sub['status']} — {s_assignees}{s_due}")

        parts.append("")

    # Pending actions
    if ctx["pending_actions"]:
        parts.append("## Pending Actions (DMs sent, awaiting response)")
        for pa in ctx["pending_actions"]:
            parts.append(_format_state_entry(pa, overdue_ids))
        parts.append("")

    # Observations
    if ctx["observations"]:
        parts.append("## Recent Observations (entity changes since last cycle)")
        for obs in ctx["observations"]:
            parts.append(_format_state_entry(obs))
        parts.append("")

    # Working memory
    if ctx["working_memory"]:
        parts.append("## Working Memory (what you know from recent cycles)")
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


def _format_state_entry(entry: dict, overdue_ids: set = None) -> str:
    """Format a skipper_state entry for the LLM context."""
    eid = entry.get("id", "?")
    subject = entry.get("subject_id", "?")
    subject_type = entry.get("subject_type", "?")
    created = entry.get("created_at", "")
    due = entry.get("due_at", "")
    priority = entry.get("priority", "")

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

    if isinstance(content, dict):
        for k, v in content.items():
            if k in ("raw",):
                lines.append(f"  {v}")
            else:
                lines.append(f"  {k}: {v}")
    else:
        lines.append(f"  {content}")

    return "\n".join(lines)


# =========================================================================
# TOOLS
# =========================================================================

def _build_tools(context_text: str) -> tuple[list[dict], set[str]]:
    """Build tool schemas for the goal thinking loop."""
    import mcp_client
    from tool_router import get_tools_for_message, get_category_tool_names

    routed_names = get_tools_for_message(context_text)

    # Always include baseline categories so Skipper has full capability
    for cat in BASELINE_CATEGORIES:
        routed_names |= get_category_tool_names(cat)

    # Filter MCP tools to routed set
    mcp_tools = []
    if mcp_client.mcp_tools:
        all_mcp = mcp_client.get_openai_tools()
        mcp_tools = [t for t in all_mcp if t["function"]["name"] in routed_names]

    STATE_TOOLS = [SEND_DM_TOOL, EXPIRE_STATE_TOOL, RESOLVE_STATE_TOOL, UPDATE_WORKING_MEMORY_TOOL]
    tools = mcp_tools + STATE_TOOLS
    routed_names |= {"send_dm", "expire_state", "resolve_state", "update_working_memory"}

    # Enforce 128-tool cap
    MAX_TOOLS = 120
    if len(tools) > MAX_TOOLS:
        logger.warning("GOAL_THINK: %d tools exceed limit — truncating", len(tools))
        keep_mcp = MAX_TOOLS - len(STATE_TOOLS)
        tools = STATE_TOOLS + mcp_tools[:keep_mcp]

    return tools, routed_names


# =========================================================================
# DM helper
# =========================================================================

async def _send_dm(person: str, text: str, subject_id: str = "", *, source_type: str = "goal_thinking"):
    """DM a real household user from the goal thinking loop.

    Delivers through the platform's multi-surface notification path (web UI,
    Discord, push, chat log) via create_notification — never a channel-specific
    sender directly. The recipient is validated: an unknown/placeholder name is
    redirected to the primary user so the nudge still reaches a real person
    (never a phantom like an example name the LLM might invent).

    ``source_type`` tags the notification (default ``goal_thinking``); the live
    first-contact arrival greeting passes ``onboarding_greeting`` so delivery
    surfaces it as a typing-clearing chat_response bubble.
    """
    from config import PM_QUIET_MODE
    if PM_QUIET_MODE:
        logger.info("GOAL_THINK: DM to %s suppressed (quiet mode)", person)
        return

    from apps.goals.data import resolve_dm_recipient
    recipient = resolve_dm_recipient(person)
    if not recipient:
        logger.warning("GOAL_THINK: DM dropped — '%s' is not a real user and no primary user is set", person)
        return
    if recipient != (person or "").strip().lower():
        logger.warning("GOAL_THINK: recipient '%s' is not a real user — redirecting to primary user '%s'", person, recipient)

    logger.info("GOAL_THINK DM → %s (re: %s): %s", recipient, subject_id, text[:200])
    try:
        from app_platform.notifications import create_notification
        await asyncio.to_thread(
            create_notification,
            recipient=recipient,
            message=text,
            source_type=source_type,
            source_id=subject_id or "",
            channel="all",
            delivered=False,
        )
    except Exception as e:
        logger.error("GOAL_THINK: Failed to notify %s: %s", recipient, e)


# =========================================================================
# Helpers
# =========================================================================

def _skip_result(reason: str, next_check: int = 1800) -> dict:
    return {
        "trigger": "timer",
        "input_summary": reason,
        "context_snapshot": {},
        "reasoning": reason,
        "actions_taken": [],
        "memories_extracted": [],
        "model_used": "skip",
        "tokens_used": 0,
        "next_check_seconds": next_check,
    }


def _skipper_owns_anything(goal_snap: dict) -> bool:
    """Return True if Skipper owns the goal, any project, or any task under it."""
    # Goal-level ownership
    if "skipper" in [o.lower() for o in (goal_snap.get("goal_owners") or [])]:
        return True

    for proj in goal_snap.get("projects", []):
        # Project-level ownership
        if "skipper" in [o.lower() for o in (proj.get("owners") or [])]:
            return True
        # Task-level assignment
        for task in proj.get("tasks", []):
            if "skipper" in [a.lower() for a in (task.get("assigned_to") or [])]:
                return True
            for sub in task.get("subtasks", []):
                if "skipper" in [a.lower() for a in (sub.get("assigned_to") or [])]:
                    return True

    return False


def _safe_snapshot(ctx: dict) -> dict:
    snap = {
        "goal_id": ctx.get("goal_id", ""),
        "pending_actions_count": ctx.get("pending_actions_count", 0),
        "observations_count": ctx.get("observations_count", 0),
        "working_memory_count": ctx.get("working_memory_count", 0),
        "now": ctx.get("now", ""),
    }
    gs = ctx.get("goal_snapshot")
    if gs:
        snap["goal_name"] = gs.get("goal_name")
        snap["total_tasks"] = gs.get("total_task_count")
        snap["total_done"] = gs.get("total_done")
        snap["total_blocked"] = gs.get("total_blocked")
        snap["project_count"] = len(gs.get("projects", []))
    return snap
