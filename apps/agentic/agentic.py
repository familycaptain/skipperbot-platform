"""Agentic jobs — Skipper running a saved prompt on a schedule (#109).

An "agentic task" is a ``public.schedules`` row: WHEN (recurrence + time) plus
``linked_entity_type='job'`` / ``linked_entity_id='agentic'`` plus a
``job_config`` jsonb carrying the spec:

    {prompt_doc_id, tool_categories, needs_attention, tier}

When the schedule is due, the schedule trigger submits an ``agentic`` job with
that job_config as its config. ``handle_agentic`` then:
  1. loads the PROMPT from its d-* document,
  2. loads the chosen tool CATEGORIES (+ request_tools for more on demand — the
     same category model chat and goal_work use; the task always knows which
     whole categories it does and doesn't have),
  3. runs the agent loop, and
  4. if the task is ``needs_attention``, raises a needs_attention EVENT (domain
     'agentic') so the VOICE (the agentic skill in handlers.py) delivers the
     result to the family.

Mouthless like the hands: no messaging tools — one voice, many hands.
"""
import json
import logging

logger = logging.getLogger("apps.agentic")

# Every agentic job gets core (memory/lookups); the task's own tool_categories
# are added on top, and it can request_tools for anything else at runtime.
_ALWAYS = {"core"}

_MESSAGING_TOOLS = {
    "send_dm", "send_message", "send_message_to_user", "send_notification",
    "send_discord_dm", "broadcast_announcement",
}


def _build_tools(loaded_categories):
    """Category-based tool set: the task's loaded categories + core, plus
    request_tools. Returns (tools, routed_names, loaded_category_set)."""
    import mcp_client
    from tool_router import get_category_tool_names
    from local_tools import REQUEST_TOOLS_TOOL

    cats = set(loaded_categories) | _ALWAYS
    routed = set()
    for c in cats:
        routed |= get_category_tool_names(c)

    tools = []
    if mcp_client.mcp_tools:
        allt = mcp_client.get_openai_tools()
        tools = [t for t in allt if t["function"]["name"] in routed
                 and t["function"]["name"] not in _MESSAGING_TOOLS]
    tools.append(REQUEST_TOOLS_TOOL)
    routed = (routed - _MESSAGING_TOOLS) | {"request_tools"}
    return tools, routed, cats


def _awareness(loaded):
    from tool_router import TOOL_CATEGORIES
    not_loaded = sorted(c for c in TOOL_CATEGORIES if c not in loaded)
    return (
        "## Your tool categories\n"
        f"LOADED right now (use these tools freely): {', '.join(sorted(loaded))}.\n"
        "You ONLY have the tools in the LOADED categories above. To do something "
        "that needs another category, call request_tools(\"<category>\") FIRST, "
        "then use it.\n"
        + (f"AVAILABLE to request: {', '.join(not_loaded)}." if not_loaded else "")
    )


_SYSTEM = (
    "You are Skipper autonomously running a SCHEDULED TASK you were set up to do "
    "for this household. Carry out the task described below using your tools. You "
    "CANNOT message anyone directly — produce the actual work (create/update "
    "documents, records, findings). Be thorough but BOUNDED: do the task, then "
    "stop. Your final message should be a short summary of what you did or found "
    "— if this task is set to notify the family, that summary is what they hear."
)


async def handle_agentic(job: dict, ctx) -> str:
    """Job handler for job_type='agentic'."""
    import asyncio
    import agent_loop

    config = job.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}

    prompt_doc_id = (config.get("prompt_doc_id") or "").strip()
    initial_cats = set(config.get("tool_categories") or [])
    needs_attention = bool(config.get("needs_attention"))
    tier = config.get("tier") or "smart"

    if not prompt_doc_id:
        return "agentic job has no prompt_doc_id — nothing to do"

    from apps.documents.data import get_document_content
    prompt = await asyncio.to_thread(get_document_content, prompt_doc_id)
    if not prompt or not prompt.strip():
        return f"agentic prompt doc {prompt_doc_id} is empty/missing — nothing to do"

    ctx.update_progress(15, "Loading prompt + tools...")
    loaded_cats = set(initial_cats)

    def _rebuild():
        return _build_tools(loaded_cats)

    tools, routed, cats = _rebuild()
    _state = {"routed": routed, "cats": cats}
    actions: list[str] = []

    async def _dispatch(name: str, args: dict) -> str:
        if name in _MESSAGING_TOOLS:
            return ("REFUSED: scheduled tasks cannot message anyone directly. Do the "
                    "work; if the family should hear the result, it is delivered "
                    "through Skipper's voice after you finish.")
        if name == "request_tools":
            c = (args.get("category") or "").strip()
            if not c:
                return "no category given"
            loaded_cats.add(c)
            return f"Loaded '{c}' tools — available now; use them directly."
        if _state["routed"] and name not in _state["routed"]:
            return (f"Error: tool '{name}' isn't loaded. Call "
                    f"request_tools(category) to load its category first.")
        if "created_by" not in args and name.startswith("create_"):
            args["created_by"] = "skipper"
        import tool_dispatch
        result = await tool_dispatch.call_tool(name, args)
        actions.append(name)
        return result

    async def _after_round(messages, current_tools):
        new_tools, new_routed, new_cats = _rebuild()
        _state["routed"] = new_routed
        extra = []
        if new_cats != _state["cats"]:
            _state["cats"] = new_cats
            extra = [{"role": "system", "content": _awareness(new_cats)}]
        return new_tools, extra

    ctx.update_progress(30, "Running the task...")
    result = await agent_loop.run(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "system", "content": _awareness(cats)},
            {"role": "user", "content": prompt.strip() + "\n\nRun this task now."},
        ],
        tools=tools, tier=tier, max_turns=15, max_tool_calls=40,
        tool_dispatch=_dispatch,
        hooks=agent_loop.LoopHooks(after_round=_after_round),
    )

    summary = (result.response_text or "").strip()

    delivered = False
    if needs_attention and summary:
        # Raise a needs_attention EVENT — the voice (agentic skill) delivers it.
        try:
            from app_platform.consciousness import log_event
            from app_platform.attention import kick
            await asyncio.to_thread(lambda: log_event(
                kind="event", who_from="skipper", domain="agentic",
                content=summary[:2000],
                payload={"agentic_job": job.get("id"), "prompt_doc_id": prompt_doc_id},
                needs_attention=True))
            kick()
            delivered = True
        except Exception:
            logger.warning("AGENTIC: could not raise needs_attention event", exc_info=True)

    ctx.update_progress(100, "Task complete")
    out = (f"agentic task ({prompt_doc_id}): {len(actions)} action(s)"
           + (" · result raised to the voice" if delivered else ""))
    logger.info("AGENTIC: %s", out)
    return out
