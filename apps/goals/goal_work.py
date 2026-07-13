"""goal_work — the HANDS layer (specs/CONSCIOUSNESS.md §3.2, §14, Q8).

Skipper autonomously executing a goal assigned to it: ONE bounded, resumable
work session per job firing, on the jobs dispatcher (parallel via
max_concurrent — never synchronous, never on the attention pool).

Hands never speak: no communication tools. Outputs are artifacts (docs,
research, task updates via MCP tools), per-goal working memory ("where I left
off" — the continuity between sessions), a sparse `activity` row per productive
session (Q6's artifact rule), and — when a result is family-worthy — a
`report_milestone` call that raises a needs_attention EVENT for the VOICE
(the goals milestone skill in handlers.py) to deliver. One mouth, many hands.

Scheduled by the pm sweep's router (`schedule_goal_work` tool) for goals whose
open items are Skipper-assigned and tool-executable.
"""

import json
import logging

logger = logging.getLogger("apps.goals.goal_work")

_WORKER_GUIDANCE = (
    "You are Skipper doing a FOCUSED WORK SESSION on one household goal that "
    "was assigned to you. Make CONCRETE progress with your tools: research, "
    "draft or update documents, complete or update tasks, record findings. "
    "You start with your goal/task tools + core. If a step needs a capability "
    "you don't have loaded — searching the web, the knowledge base, drafting a "
    "document, files — call request_tools(category) (e.g. 'web', 'knowledge', "
    "'filesystem') and the tools appear immediately; then use them. "
    "You CANNOT send messages to anyone in this mode — if you reach a result "
    "the family would genuinely want to hear about, call report_milestone "
    "(once, brief). Work the most valuable open item first; do not re-do work "
    "your working memory says is done. Before you stop, ALWAYS call "
    "update_working_memory with where you left off and what's next, so the "
    "next session resumes cleanly. This is one bounded session, not the whole "
    "goal — stop at a natural checkpoint."
)

_REPORT_MILESTONE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_milestone",
        "description": "Raise a family-worthy result to Skipper's voice for possible delivery. Use at most once per session, only for genuinely notable progress.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "One or two sentences describing the result."},
            },
            "required": ["message"],
        },
    },
}


async def handle_goal_work(job: dict, ctx) -> str:
    """Job handler: one work session for job.config.goal_id."""
    import asyncio
    import agent_loop
    from apps.goals import work_context as G
    from data_layer.skipper_state import list_states
    from app_platform.consciousness import shadow_log_event, log_event

    config = job.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}
    goal_id = config.get("goal_id") or ""
    if not goal_id:
        return "no goal_id in job config — nothing to do"

    ctx.update_progress(10, f"Assembling work context for {goal_id}...")
    from apps.goals.data import load_entity
    goal = await asyncio.to_thread(load_entity, goal_id)
    if not goal:
        return f"goal {goal_id} not found — nothing to do"
    snapshot = await asyncio.to_thread(G._build_goal_snapshot, goal)
    if not snapshot:
        return f"goal {goal_id} empty — nothing to do"
    memories = await asyncio.to_thread(G._recall_memories, goal_id, snapshot)
    # Working memory keys under the standing 'goals' domain with
    # subject_id=goal_id (skipper_state.domain FKs to thinking_domains, and
    # per-goal g-* rows no longer exist under Q8 — the subject carries the goal).
    working_all = await asyncio.to_thread(
        list_states, domain="goals", state_type="working_memory", status="active", limit=50)
    working = [w for w in working_all if w.get("subject_id") == goal_id]

    state_lines = [f"GOAL: {snapshot.get('goal_name', goal_id)} ({goal_id})",
                   json.dumps(snapshot, default=str)[:6000]]
    if working:
        state_lines.append("WORKING MEMORY (where prior sessions left off):")
        state_lines += [f"  - {w.get('subject_id')}: {w.get('content','')[:400]}" for w in working]
    if memories:
        state_lines.append("RELEVANT SHARED MEMORIES:")
        state_lines += [f"  - {m.get('content','')[:200]}" for m in memories[:8]]

    # Tools: category-based, like chat. Default = the goals category + core;
    # the session request_tools's any other category ON DEMAND (see
    # work_context._build_tools). report_milestone is always present; hands are
    # mouthless (no messaging tool in the set). `loaded_cats` accumulates the
    # categories the worker request_tools'd; the after_round hook rebuilds the
    # toolset and re-injects the loaded-category awareness so the model always
    # knows what it does and doesn't have.
    loaded_cats: set[str] = set()

    def _rebuild_tools():
        t, r, cats = G._build_tools(loaded_categories=loaded_cats)
        t.append(_REPORT_MILESTONE_TOOL)
        return t, set(r) | {"report_milestone"}, cats

    tools, _routed0, _cats0 = _rebuild_tools()
    _routed = {"names": _routed0, "cats": _cats0}  # live state, refreshed by after_round

    actions: list[dict] = []
    milestones: list[str] = []

    async def _dispatch(name: str, args: dict) -> str:
        if name == "send_dm":
            return "REFUSED: work sessions cannot message anyone (report_milestone instead)."
        if name == "request_tools":
            cat = (args.get("category") or "").strip()
            if not cat:
                return "no category given"
            loaded_cats.add(cat)
            # the after_round hook rebuilds the toolset with this category loaded
            return f"Loaded '{cat}' tools — available now; use them directly, no confirmation needed."
        if name == "report_milestone":
            msg = (args.get("message") or "").strip()
            if not msg:
                return "empty milestone ignored"
            if milestones:
                return "already reported a milestone this session"
            milestones.append(msg)
            row = await asyncio.to_thread(
                lambda: log_event(kind="event", who_from="skipper", domain="goals",
                                  content=f"milestone on {snapshot.get('goal_name', goal_id)}: {msg}",
                                  subject_id=goal_id,
                                  payload={"milestone": msg, "goal_id": goal_id},
                                  needs_attention=True))
            try:
                from app_platform.attention import kick
                kick()
            except Exception:
                pass
            return f"milestone raised ({row['id']}) — the voice will decide delivery"
        if name == "update_working_memory":
            from data_layer.skipper_state import upsert_working_memory
            await asyncio.to_thread(
                upsert_working_memory, "goals", goal_id, "goal",
                args.get("summary") or args.get("content") or "")
            actions.append({"type": "memory_updated"})
            return "working memory updated"
        if _routed["names"] and name not in _routed["names"]:
            return (f"Error: tool '{name}' isn't loaded. Call "
                    f"request_tools(category) to load its category first.")
        if "created_by" not in args and name.startswith("create_"):
            args["created_by"] = "skipper"
        import tool_dispatch
        result = await tool_dispatch.call_tool(name, args)
        actions.append({"type": "tool_executed", "tool": name})
        return result

    async def _after_round(messages, current_tools):
        # request_tools during the round may have added categories; rebuild the
        # toolset so the newly-loaded tools are live for the next LLM call, and
        # refresh the dispatch gate set to match. When the loaded categories
        # changed, re-inject the updated awareness so the model tracks what it has.
        new_tools, new_routed, new_cats = _rebuild_tools()
        _routed["names"] = new_routed
        extra = []
        if new_cats != _routed["cats"]:
            _routed["cats"] = new_cats
            extra = [{"role": "system", "content": G._category_awareness(new_cats)}]
        return new_tools, extra

    tier = "smart" if snapshot.get("total_task_count", 0) > 10 else "fast"
    ctx.update_progress(30, f"Working ({tier} tier)...")
    loop_result = await agent_loop.run(
        messages=[
            {"role": "system", "content": _WORKER_GUIDANCE},
            {"role": "system", "content": G._category_awareness(_routed["cats"])},
            {"role": "user", "content": "\n".join(state_lines) +
             "\n\nBegin this work session now."},
        ],
        tools=tools, tier=tier, max_turns=12, max_tool_calls=40,
        tool_dispatch=_dispatch,
        hooks=agent_loop.LoopHooks(after_round=_after_round),
    )

    # Q6 artifact rule: one activity row per PRODUCTIVE session, else nothing.
    if actions:
        await asyncio.to_thread(
            shadow_log_event, kind="activity", who_from="skipper", domain="goals",
            subject_id=goal_id,
            content=(f"[goal_work] {snapshot.get('goal_name', goal_id)}: "
                     f"{len(actions)} action(s) this session"
                     + (f"; milestone: {milestones[0][:80]}" if milestones else "")),
            payload={"goal_id": goal_id, "actions": len(actions)})

    ctx.update_progress(100, "Session complete")
    summary = (f"goal_work session for {goal_id}: {len(actions)} action(s), "
               f"{len(milestones)} milestone(s), "
               f"{loop_result.prompt_tokens + loop_result.completion_tokens} tokens")
    logger.info("GOAL_WORK: %s", summary)
    return summary
