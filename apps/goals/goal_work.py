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
    from apps.goals import domain as G
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
    working = await asyncio.to_thread(
        list_states, domain=goal_id, state_type="working_memory", status="active", limit=20)

    state_lines = [f"GOAL: {snapshot.get('goal_name', goal_id)} ({goal_id})",
                   json.dumps(snapshot, default=str)[:6000]]
    if working:
        state_lines.append("WORKING MEMORY (where prior sessions left off):")
        state_lines += [f"  - {w.get('subject_id')}: {w.get('content','')[:400]}" for w in working]
    if memories:
        state_lines.append("RELEVANT SHARED MEMORIES:")
        state_lines += [f"  - {m.get('content','')[:200]}" for m in memories[:8]]

    # Tools: routed MCP set (goals/docs/knowledge/research/web baselines) MINUS
    # any messaging tool, plus working-memory + milestone. Hands have no mouth.
    tools, routed = G._build_tools("\n".join(state_lines))
    tools = [t for t in tools if t.get("function", {}).get("name") != "send_dm"]
    tools.append(_REPORT_MILESTONE_TOOL)

    actions: list[dict] = []
    milestones: list[str] = []

    async def _dispatch(name: str, args: dict) -> str:
        if name == "send_dm":
            return "REFUSED: work sessions cannot message anyone (report_milestone instead)."
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
                upsert_working_memory, goal_id,
                args.get("subject_id") or goal_id, "goal",
                args.get("summary") or args.get("content") or "")
            actions.append({"type": "memory_updated"})
            return "working memory updated"
        if routed and name not in routed:
            return f"Error: tool '{name}' not in the routed set."
        if "created_by" not in args and name.startswith("create_"):
            args["created_by"] = "skipper"
        import tool_dispatch
        result = await tool_dispatch.call_tool(name, args)
        actions.append({"type": "tool_executed", "tool": name})
        return result

    tier = "smart" if snapshot.get("total_task_count", 0) > 10 else "fast"
    ctx.update_progress(30, f"Working ({tier} tier)...")
    loop_result = await agent_loop.run(
        messages=[
            {"role": "system", "content": _WORKER_GUIDANCE},
            {"role": "user", "content": "\n".join(state_lines) +
             "\n\nBegin this work session now."},
        ],
        tools=tools, tier=tier, max_turns=12, max_tool_calls=40,
        tool_dispatch=_dispatch,
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
