"""Routines — Skipper running a saved prompt on a schedule (#109).

A "routine" is a ``public.schedules`` row: WHEN (recurrence + time) plus
``linked_entity_type='job'`` / ``linked_entity_id='agentic'`` plus a
``job_config`` jsonb carrying the spec:

    {prompt_doc_id, tool_categories, tier}

When the schedule is due, the schedule trigger submits an ``agentic`` job with
that job_config as its config. ``handle_agentic`` then loads the PROMPT from its
d-* document, loads the chosen tool CATEGORIES (+ request_tools for more on
demand — the same category model chat and goal_work use), and runs the agent
loop with the SAME tools a chat turn gets. There are NO artificial limits: the
prompt drives everything — if it says to notify someone, the routine uses the
ordinary notification tools, exactly like chat. Delivery is the prompt's job.
"""
import json
import logging

logger = logging.getLogger("apps.agentic")

# Every agentic job gets core (memory/lookups); the task's own tool_categories
# are added on top, and it can request_tools for anything else at runtime.
_ALWAYS = {"core"}


def _build_tools(loaded_categories):
    """The SAME tool set a chat turn gets, scoped to the loaded categories:
    routed MCP tools + the local tools (send_notification, send_message_to_user,
    request_tools, open_app, …). A routine has no artificial limits — if
    its prompt says to notify someone, it uses the ordinary notification tool,
    exactly like chat. Returns (tools, allowed_names, loaded_category_set)."""
    import mcp_client
    from tool_router import get_category_tool_names, META_TOOL_NAMES
    from local_tools import LOCAL_TOOLS

    cats = set(loaded_categories) | _ALWAYS
    routed = set()
    for c in cats:
        routed |= get_category_tool_names(c)
    allowed = routed | META_TOOL_NAMES

    mcp_tools = []
    if mcp_client.mcp_tools:
        allt = mcp_client.get_openai_tools()
        mcp_tools = [t for t in allt if t["function"]["name"] in routed]
    local = [t for t in LOCAL_TOOLS if t["function"]["name"] in allowed]
    tools = mcp_tools + local
    return tools, {t["function"]["name"] for t in tools}, cats


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
    "You are Skipper autonomously running a ROUTINE you were set up to do "
    "for this household. Carry out the routine exactly as described below, using your "
    "tools — including notifying people if the routine says to (use the ordinary "
    "notification tools, just like in chat). Be thorough but BOUNDED: do the routine, "
    "then stop. End with a short summary of what you did."
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
        actions.append(name)
        # Local tools (send_notification, send_message_to_user, open_app, …) run
        # locally, exactly as in chat; everything else goes through MCP dispatch.
        from local_tools import LOCAL_TOOL_NAMES, handle_local_tool
        if name in LOCAL_TOOL_NAMES:
            return await handle_local_tool(name, args, "skipper")
        import tool_dispatch
        return await tool_dispatch.call_tool(name, args)

    async def _after_round(messages, current_tools):
        new_tools, new_routed, new_cats = _rebuild()
        _state["routed"] = new_routed
        extra = []
        if new_cats != _state["cats"]:
            _state["cats"] = new_cats
            extra = [{"role": "system", "content": _awareness(new_cats)}]
        return new_tools, extra

    ctx.update_progress(30, "Running the routine...")
    result = await agent_loop.run(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "system", "content": _awareness(cats)},
            {"role": "user", "content": prompt.strip() + "\n\nRun this routine now."},
        ],
        tools=tools, tier=tier, max_turns=15, max_tool_calls=40,
        tool_dispatch=_dispatch,
        hooks=agent_loop.LoopHooks(after_round=_after_round),
    )

    ctx.update_progress(100, "Routine complete")
    out = f"routine ({prompt_doc_id}): {len(actions)} action(s)"
    logger.info("AGENTIC: %s", out)
    return out
