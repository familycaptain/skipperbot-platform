"""
Chat Domain Handler
===================
Core chat processing — context assembly, memory/knowledge retrieval,
tool routing, agent loop execution, and post-processing.

This is the "thinking" component of chat, registered as a priority-0
domain in the thinking system. Session management, transport, and
UX concerns (typing indicators, delayed messages) stay in chat.py.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from config import logger, load_system_prompt, get_dynamic_system_context, DEBUG_TOKENS
import mcp_client
from local_tools import LOCAL_TOOLS, LOCAL_TOOL_NAMES, handle_local_tool
from memory_store import get_relevant_memories, format_memories_for_context, get_embedding
from knowledge_store import get_relevant_knowledge, format_knowledge_for_context
from app_platform.folders import get_relevant_folder_knowledge, format_folder_knowledge_for_context
from tool_router import (
    get_tools_for_message, get_guides_for_message, get_category_tool_names,
    get_guides_for_categories, get_match_debug_for_message,
    META_TOOL_NAMES, DISABLED_CHAT_TOOLS, reload_routes, get_ack_template, TOOL_CATEGORIES,
)
import agent_loop

# ---------------------------------------------------------------------------
# Mutating tool sets — trigger frontend app refreshes via send_event
# ---------------------------------------------------------------------------

GOAL_MUTATING_TOOLS = {
    "create_goal", "create_project", "create_task", "update_item", "stop_onboarding",
    "delete_item", "update_entity_notes", "set_task_order", "set_task_dependency",
    "set_task_parent", "set_project_order", "set_project_dependency",
    "set_goal_order", "set_goal_dependency", "enable_project_nag", "disable_project_nag",
}

DOC_MUTATING_TOOLS = {
    "create_doc", "update_doc", "append_to_doc", "delete_doc",
    "update_doc_meta", "enhance_doc",
}

REMINDER_MUTATING_TOOLS = {
    "set_reminder", "set_nag", "cancel_reminder_by_id",
    "modify_reminder_by_id", "snooze_reminder",
}

RECIPE_MUTATING_TOOLS = {
    "create_recipe", "update_recipe", "delete_recipe",
    "create_recipe_category", "update_recipe_category", "delete_recipe_category",
}

BRAINSTORM_MUTATING_TOOLS = {
    "create_idea", "update_idea", "delete_idea", "graduate_idea",
    "update_idea_document", "append_to_idea_document",
}

TODO_MUTATING_TOOLS = {
    "add_todo_item", "mark_todo_done", "add_list_item", "remove_list_item",
    "move_list_items",
}


# ---------------------------------------------------------------------------
# Request / Result
# ---------------------------------------------------------------------------

@dataclass
class ChatRequest:
    """Everything the chat domain needs to process a message."""
    user_id: str
    user_message: str
    session_messages: list[dict]   # conversation history (role/content dicts)
    turn_id: str
    channel: str = "discord"       # "discord" | "web" | "voice"
    app_context: dict | None = None
    send_progress: Optional[Callable[[str], Awaitable[None]]] = None
    send_event: Optional[Callable[[dict], Awaitable[None]]] = None
    # Tool-router SLOTS: categories the model has request_tools'd, persisted across turns by
    # the session layer (chat.py owns the per-user list and passes it by reference, so in-turn
    # loads/evictions survive to the next turn). NOT the pinned voice/app-context categories.
    loaded_categories: list[str] = field(default_factory=list)


@dataclass
class ChatResult:
    """Result of processing a chat message through the domain."""
    response_text: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls_made: list = field(default_factory=list)
    # Debug capture for chat_turns audit columns. Populated on every turn so
    # we can see exactly what system prompt was sent, which tools were exposed,
    # and which keywords triggered each routed tool guide.
    system_prompt: str = ""
    selected_tools: list = field(default_factory=list)
    matched_guides: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

async def handle_chat(req: ChatRequest) -> ChatResult:
    """Core chat domain handler — context assembly + agent loop.

    Orchestrates: system prompt → scrum items → memory/knowledge →
    tool routing → agent loop with hooks → post-processing.
    """
    extra_categories: set[str] = set()

    if req.channel == "voice" and req.app_context:
        try:
            from app_platform.voice.prompting import get_default_categories
            extra_categories.update(get_default_categories(req.app_context))
        except Exception as exc:
            logger.debug("VOICE: Could not load default voice categories: %s", exc)

    # 1. STATIC system prompt — persona + channel rules (cacheable prefix)
    static_system = _build_system_prompt(req, extra_categories)

    # 2. DYNAMIC context — changes every call (time, turn_id, app, scrum, memory, guides)
    dynamic_context = (
        get_dynamic_system_context(req.user_id) + "\n\n"
        f"Current chat turn ID: {req.turn_id}\n"
        "When calling remember(), pass this as source_chat_id to link "
        "memories back to this conversation."
    )

    # App context (web only — entity being viewed, document content, etc.)
    if req.channel == "web" and req.app_context:
        dynamic_context = _inject_app_context(dynamic_context, req.app_context, extra_categories)
    elif req.channel == "voice" and req.app_context:
        dynamic_context = _inject_voice_context(dynamic_context, req.app_context)

    # Skipper's own active work (goals/projects/tasks it owns).
    # Note: scrum-item injection used to live here too, but scrum is an
    # OPTIONAL app — wiring it into the platform's chat loop meant the
    # public release queried a non-existent `scrum_items` table on every
    # turn. The scrum app will register its own prompt-extender hook
    # when it lands as a separate package in Phase 1c.
    dynamic_context = await _inject_skipper_work_context(dynamic_context)
    # When first-run onboarding is live, re-frame it as the agent's ACTIVE script to walk
    # (gently, in order, capture-don't-configure) instead of background work — and PIN the goals
    # tools so it can mark each agenda topic done (update_item) and actually advance.
    dynamic_context, _is_onboarding = await _inject_onboarding_context(dynamic_context)
    if _is_onboarding:
        extra_categories.add("app:goals")

    # Reply-to-proactive-DM continuity: if a thinking domain DM'd this user and
    # it's still unresolved, flag it so a reply gets the sender's intent/cadence.
    dynamic_context, _has_pending_dm = await _inject_proactive_dm_context(
        dynamic_context, req.user_id)

    # Memory + knowledge retrieval
    t_retrieval = time.monotonic()
    dynamic_context = await _retrieve_context(
        req.user_message, dynamic_context, req.user_id
    )
    logger.info("PERF: retrieval %.2fs", time.monotonic() - t_retrieval)

    # 3. Tool routing — use message + recent session context for keyword matching
    _SESSION_BOUNDARY = "[Session resumed"
    current_session_msgs = req.session_messages
    for _i, _m in enumerate(req.session_messages):
        if _m.get("content", "").startswith(_SESSION_BOUNDARY):
            current_session_msgs = req.session_messages[_i + 1:]
            break
    context_window = current_session_msgs[-20:]  # last 10 turns
    context_text = req.user_message + "\n" + "\n".join(
        m["content"] for m in context_window if m.get("content")
    )
    # SLOT MODEL (replaces the eager `get_tools_for_message(context_text)` load that exploded
    # the prompt). Always-on: the 'core' category + META tools. The model loads what it needs
    # into a small set of swap SLOTS via request_tools (each load auto-evicts the oldest).
    # PINNED (never evicted) = extra_categories: voice channel defaults + the web app-context
    # entity. (context_text above is kept only for the keyword audit column.)
    routed_tool_names = get_category_tool_names("core")

    if req.channel == "web" and req.app_context:
        _ctx_entity_type = req.app_context.get("entityType", "")
        if _ctx_entity_type == "idea":
            extra_categories.add("brainstorming")
        elif _ctx_entity_type == "document":
            extra_categories.add("documents")
        elif _ctx_entity_type in ("goal", "project", "task"):
            extra_categories.add("goals")

    SLOT_CAPACITY = 2
    slots: list[str] = req.loaded_categories  # persisted across turns (mutated in place)

    def _loaded_categories() -> set[str]:
        """Everything currently exposed: pinned (extra_categories) + the swap slots."""
        return set(extra_categories) | set(slots)

    def _load_slot(category: str) -> tuple:
        """Load a category into a slot; auto-evict the oldest when full. Returns (loaded, evicted)."""
        category = (category or "").lower().strip()
        # Validate via the RESOLVER (handles the 'app:<id>' prefix + normalization), NOT a raw
        # TOOL_CATEGORIES dict-key check — that rejected valid app categories and spun the loop.
        if not category or not get_category_tool_names(category):
            return None, None
        if category in extra_categories or category in slots:
            return None, None  # already available
        evicted = slots.pop(0) if len(slots) >= SLOT_CAPACITY else None
        slots.append(category)
        return category, evicted

    # Deterministically expose the reply-guide tool when a proactive DM is pending.
    if _has_pending_dm:
        routed_tool_names.add("get_proactive_reply_guide")

    # Dynamic slot state + how to load more (cheap; the category catalog itself is in BEHAVIOR.md).
    _loaded_now = sorted(_loaded_categories())
    dynamic_context += (
        "\n\n## Tool categories (slots)\n"
        f"Loaded now: {', '.join(_loaded_now) if _loaded_now else 'core only'} "
        f"(you have {SLOT_CAPACITY} swap slots, {len(slots)} used).\n"
        "To act in an area whose tools you don't see, call request_tools(category) — it loads that "
        "category's tools AND its guide into a slot (auto-unloads your oldest slot if full). Choose "
        "the right category from the conversation (incl. back-references like 'do it'); never invent "
        "a tool you haven't loaded.\n"
    )

    # Inject guides for the LOADED categories only (tools + guide travel together).
    guide_content = get_guides_for_categories(_loaded_categories())
    if guide_content:
        dynamic_context += "\n\n" + guide_content
        logger.debug("GUIDES: injected guides for loaded categories: %s", _loaded_now)

    # Capture per-category routing audit for the chat_turns debug columns.
    # This is computed once on the same context_text used above so it reflects
    # exactly which keywords fired and which guides were therefore eligible.
    matched_guides_debug = get_match_debug_for_message(context_text, extra_categories)

    # 4. Build messages — TWO system messages for prompt caching
    #    OpenAI caches identical message prefixes; the static portion stays
    #    the same across calls so it gets cached at ~50% cost reduction.
    messages = [
        {"role": "system", "content": static_system},
        {"role": "system", "content": dynamic_context},
        *[
            {**m, "content": m.get("content") or ""} if m.get("role") != "tool" else m
            for m in req.session_messages
        ]
    ]

    # 7. Build tools
    def _build_tools() -> list | None:
        """Build the filtered tool list from MCP + LOCAL tools.

        OpenAI enforces a hard limit of 128 tools per request.
        If the routed set exceeds that, we keep META + core tools first,
        then fill remaining slots from other matched categories.
        """
        MAX_TOOLS = 128

        allowed = routed_tool_names | META_TOOL_NAMES
        # Add the loaded categories: pinned (voice/app-context) + the swap slots.
        for cat in _loaded_categories():
            allowed |= get_category_tool_names(cat)

        # Never offer the disabled (code-authoring / shell / MCP-control) tools to
        # the LLM, no matter how they were routed or requested. Applied last so no
        # routing/request/context path can reintroduce them.
        allowed -= DISABLED_CHAT_TOOLS

        # Filter MCP tools to only those in allowed set
        mcp_tools = []
        if mcp_client.mcp_tools:
            all_mcp = mcp_client.get_openai_tools()
            mcp_tools = [t for t in all_mcp if t["function"]["name"] in allowed]

        # Filter LOCAL tools to only those in allowed set or meta-tools
        local_tools = [t for t in LOCAL_TOOLS if t["function"]["name"] in allowed]
        # open_app's app catalog is DYNAMIC (installed+enabled apps reported by the
        # web client) — swap the static schema for one with the live list appended.
        if any(t["function"]["name"] == "open_app" for t in local_tools):
            from local_tools import build_open_app_tool
            local_tools = [build_open_app_tool() if t["function"]["name"] == "open_app" else t
                           for t in local_tools]

        combined = mcp_tools + local_tools

        # Enforce OpenAI 128-tool cap
        if len(combined) > MAX_TOOLS:
            logger.warning("TOOL ROUTER: %d tools exceed OpenAI limit of %d — truncating",
                           len(combined), MAX_TOOLS)
            # Prioritize: LOCAL/meta tools first, then core MCP, then explicitly
            # requested/context categories (extra_categories), then the rest.
            # extra_categories tools MUST survive — the LLM was told they're available.
            priority_names = META_TOOL_NAMES | get_category_tool_names("core")
            for _cat in _loaded_categories():
                priority_names |= get_category_tool_names(_cat)
            priority = [t for t in combined if t["function"]["name"] in priority_names]
            rest = [t for t in combined if t["function"]["name"] not in priority_names]
            combined = (priority + rest)[:MAX_TOOLS]

        logger.debug("TOOL ROUTER: %d tools selected (%d MCP + %d local) for message: %s",
                     len(combined), len(mcp_tools), len(local_tools), req.user_message[:80])
        return combined if combined else None

    tools = _build_tools()

    # Track every tool ever exposed across the conversation. Tools can be
    # rebuilt mid-loop (request_tools, restart_mcp_server) — we audit the
    # union so the saved record reflects the full surface the LLM saw.
    selected_tool_names: set[str] = set()
    if tools:
        selected_tool_names.update(t["function"]["name"] for t in tools)

    # ------------------------------------------------------------------
    # 8. Agent loop hooks (closures over local state)
    # ------------------------------------------------------------------

    sent_acks: set[str] = set()
    direct_display_sent: str | None = None
    dd_tool_count = 0
    total_tool_count = 0
    needs_tool_refresh = False
    needs_tool_rebuild = False

    async def _dispatch_tool(tool_name: str, tool_args: dict) -> str:
        """Route tool call to LOCAL handler or direct in-process dispatch."""
        if tool_name in LOCAL_TOOL_NAMES:
            return await handle_local_tool(tool_name, tool_args, from_user=req.user_id)
        import tool_dispatch
        return await tool_dispatch.call_tool(tool_name, tool_args)

    async def _before_tool(tool_name: str, tool_args: dict, tool_call_id: str):
        """Pre-dispatch hook: send ack messages + tool call event for UI."""
        if req.send_progress:
            ack = get_ack_template(tool_name, tool_args)
            if ack and ack not in sent_acks:
                sent_acks.add(ack)
                try:
                    await req.send_progress(ack)
                except Exception as e:
                    logger.warning("PROGRESS: Failed to send ack: %s", e)

        if req.send_event:
            try:
                await req.send_event({
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "tool_call_id": tool_call_id,
                })
            except Exception as e:
                logger.warning("TOOL_CALL_EVENT: Failed to send: %s", e)

    async def _after_tool(tool_name: str, tool_args: dict, tool_result: str,
                          tool_call_id: str) -> str | None:
        """Post-dispatch hook: events, interceptions, direct-display."""
        nonlocal direct_display_sent, dd_tool_count, total_tool_count
        nonlocal needs_tool_refresh, needs_tool_rebuild
        result = tool_result

        # Intercept revision proposals: send via WebSocket, give LLM only the summary
        if result and tool_name == "revise_idea_document" and '"_proposal"' in result:
            try:
                proposal = json.loads(result)
                if isinstance(proposal, dict) and proposal.get("_proposal"):
                    if req.send_event:
                        await req.send_event({
                            "type": "idea_edit_proposal",
                            "idea_id": proposal.get("idea_id", ""),
                            "part_id": proposal.get("part_id", ""),
                            "original": proposal.get("original", ""),
                            "revised": proposal.get("revised", ""),
                            "diffs": proposal.get("diffs", []),
                            "instruction": proposal.get("instruction", ""),
                        })
                    result = proposal.get("summary", "Revision proposal sent to editor.")
                    logger.info("BRAINSTORM: Proposal sent via WebSocket for %s",
                                proposal.get("idea_id"))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("BRAINSTORM: Failed to parse proposal: %s", e)

        # Notify frontend to refresh apps after data mutations
        if req.send_event:
            _EVENT_MAP = {
                "goals_updated": GOAL_MUTATING_TOOLS,
                "doc_updated": DOC_MUTATING_TOOLS,
                "reminders_updated": REMINDER_MUTATING_TOOLS,
                "recipes_updated": RECIPE_MUTATING_TOOLS,
                "brainstorm_updated": BRAINSTORM_MUTATING_TOOLS,
                "todo_updated": TODO_MUTATING_TOOLS,
            }
            for event_type, tool_set in _EVENT_MAP.items():
                if tool_name in tool_set:
                    try:
                        await req.send_event({"type": event_type})
                    except Exception:
                        pass

        total_tool_count += 1

        # Direct-display: tool wants to bypass LLM formatting
        if result and result.lstrip().startswith('{"__direct_display__"'):
            try:
                dd = json.loads(result)
                if isinstance(dd, dict) and dd.get("__direct_display__"):
                    if req.send_progress and dd.get("display"):
                        await req.send_progress(dd["display"])
                        direct_display_sent = dd["display"]
                    dd_tool_count += 1
                    result = dd.get("context") or result
            except (json.JSONDecodeError, TypeError):
                pass

        # Track special tool calls for post-round handling
        if tool_name == "restart_mcp_server":
            needs_tool_refresh = True
        if tool_name == "request_tools":
            category = tool_args.get("category", "").lower().strip()
            if category:
                loaded, evicted = _load_slot(category)
                # ALWAYS rebuild after a request_tools call so a rejected/empty category can't
                # leave the model with no new tools and spin (the runaway we hit).
                needs_tool_rebuild = True
                if loaded:
                    logger.info("TOOL SLOTS: loaded [%s]%s (slots=%s)", loaded,
                                f" evicted [{evicted}]" if evicted else "", slots)
                    if req.send_event:  # Phase 2B: UI tool-bubble
                        try:
                            await req.send_event({"type": "tool_slot", "loaded": loaded,
                                                  "unloaded": evicted, "slots": list(slots)})
                        except Exception:
                            pass

        return result

    async def _after_round(msgs: list[dict], current_tools: list | None) -> tuple:
        """Post-round hook: tool refresh/rebuild and direct-display constraints."""
        nonlocal needs_tool_refresh, needs_tool_rebuild, routed_tool_names, tools
        new_tools = None
        extra_msgs = []

        if needs_tool_refresh:
            logger.debug("TOOL REFRESH: MCP server restarted, re-fetching tools...")
            await mcp_client.connect_to_mcp()
            reload_routes()
            routed_tool_names = get_tools_for_message(req.user_message)
            logger.debug("TOOL REFRESH: Now have %d MCP tools, re-routed %d tool names",
                         len(mcp_client.mcp_tools), len(routed_tool_names))

        if needs_tool_refresh or needs_tool_rebuild:
            new_tools = _build_tools()
            tools = new_tools  # keep outer variable in sync
            if new_tools:
                selected_tool_names.update(
                    t["function"]["name"] for t in new_tools
                )

        needs_tool_refresh = False
        needs_tool_rebuild = False

        # Direct-display constraint injection
        if direct_display_sent:
            if dd_tool_count >= total_tool_count:
                extra_msgs.append({
                    "role": "system",
                    "content": (
                        "IMPORTANT: The tool output has ALREADY been displayed directly "
                        "to the user in full. You have NOTHING to add. Respond with an "
                        "empty message or at most a single brief sentence if you have a "
                        "genuinely new insight. Do NOT repeat, summarize, or rephrase "
                        "ANY of the displayed content."
                    ),
                })
            else:
                extra_msgs.append({
                    "role": "system",
                    "content": (
                        "IMPORTANT: One of the tool outputs above was ALREADY displayed "
                        "directly to the user. Do NOT repeat or summarize that content. "
                        "However, OTHER tool results contain information that was NOT "
                        "direct-displayed — you MUST still relay that content to the user."
                    ),
                })

        return new_tools, extra_msgs

    # ------------------------------------------------------------------
    # 9. Run agent loop
    # ------------------------------------------------------------------

    loop_result = await agent_loop.run(
        messages=messages,
        tools=tools,
        hooks=agent_loop.LoopHooks(
            before_tool_call=_before_tool,
            after_tool_call=_after_tool,
            after_round=_after_round,
        ),
        tool_dispatch=_dispatch_tool,
    )

    response_text = loop_result.response_text

    # ------------------------------------------------------------------
    # 10. Post-processing
    # ------------------------------------------------------------------

    # Suppress duplicate: if a direct display was already sent and the LLM
    # parroted or rephrased it, suppress the response.
    if direct_display_sent and response_text:
        # If ALL tool calls were direct-display, suppress any non-trivial response
        if dd_tool_count >= total_tool_count:
            stripped = response_text.strip()
            # Allow truly minimal responses (e.g. empty, single emoji)
            if len(stripped) > 10:
                logger.info("DIRECT_DISPLAY: Suppressed LLM response "
                            "(all tools were direct-display, %d chars)", len(stripped))
                response_text = None
        else:
            # Mixed results: use line-overlap check for the direct-displayed portion
            display_lines = {l.strip() for l in direct_display_sent.split("\n") if l.strip()}
            response_lines = [l for l in response_text.split("\n") if l.strip()]
            if display_lines and response_lines:
                overlap = sum(1 for l in response_lines if l.strip() in display_lines)
                if overlap > len(response_lines) * 0.5:
                    logger.info("DIRECT_DISPLAY: Suppressed duplicate LLM response "
                                "(%d/%d lines overlapped)", overlap, len(response_lines))
                    response_text = None

    # Prepend token usage when DEBUG_TOKENS is enabled
    if DEBUG_TOKENS and req.channel != "voice" and response_text:
        response_text = (
            f"[{loop_result.prompt_tokens:,} in / "
            f"{loop_result.completion_tokens:,} out]\n{response_text}"
        )

    # Log cycle to thinking_log so chat tokens appear in budget breakdown
    total_tokens = loop_result.prompt_tokens + loop_result.completion_tokens
    if total_tokens > 0:
        try:
            from data_layer.thinking_log import log_cycle
            await asyncio.to_thread(
                log_cycle,
                domain="chat",
                trigger="user_message",
                input_summary=req.user_message[:200],
                reasoning=response_text[:500] if response_text else "",
                model_used="standard",
                tokens_used=total_tokens,
            )
        except Exception as e:
            logger.warning("CHAT_DOMAIN: Failed to log cycle: %s", e)

    full_system_prompt = static_system + "\n\n---DYNAMIC---\n\n" + dynamic_context

    return ChatResult(
        response_text=response_text,
        prompt_tokens=loop_result.prompt_tokens,
        completion_tokens=loop_result.completion_tokens,
        tool_calls_made=loop_result.tool_calls_made,
        system_prompt=full_system_prompt,
        selected_tools=sorted(selected_tool_names),
        matched_guides=matched_guides_debug,
    )


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

def _build_system_prompt(req: ChatRequest, extra_categories: set[str]) -> str:
    """Build the STATIC system prompt: persona + channel rules + active behaviors.

    This portion is identical across calls from the same channel and is
    placed first in the messages array so OpenAI can cache the prefix.
    All per-call dynamic content (turn_id, app context, scrum, memories,
    guides) goes into a separate second system message.
    """
    system_prompt = load_system_prompt(req.user_id)

    # --- Active behavior rules (always injected, never semantic) ---
    try:
        from app_platform.behaviors import get_active_behaviors_for_user
        active_behaviors = get_active_behaviors_for_user(req.user_id)
        if active_behaviors:
            lines = ["\n\n## Active Behavior Rules",
                     "These rules are ALWAYS active. When a user message matches a trigger, "
                     "perform the action immediately without being asked. Do not repeat the "
                     "rule back to the user — just execute the action.\n"]
            for b in active_behaviors:
                lines.append(f"- **Trigger:** {b['trigger_description']}")
                lines.append(f"  **Action:** {b['action_description']}\n")
            system_prompt += "\n".join(lines)
    except Exception as _be:
        logger.debug("BEHAVIORS: Could not load behaviors for %s: %s", req.user_id, _be)

    # --- Channel-specific context (static per channel) ---
    if req.channel == "web":
        system_prompt += (
            "\n\n## Web Desktop\n"
            "This user is on the web interface which has a visual desktop with apps. "
            "When they ask to SEE, SHOW, VIEW, or BROWSE goals, projects, tasks, notes, documents, "
            "investments, positions, portfolio, reminders, etc., "
            "use the open_app tool to open the appropriate app on their desktop instead of "
            "printing text in chat. Examples:\n"
            "- 'show me my goals' → open_app(goals)\n"
            "- 'show me project X' → open_app(app_type='goals', projectId='p-...')\n"
            "- 'open task T' → open_app(app_type='goals', taskId='t-...')\n"
            "- 'show goal G' → open_app(app_type='goals', goalId='g-...')\n"
            "- 'show my documents' → open_app(documents)  [opens the doc list]\n"
            "- 'open doc d-abc123' → open_app(document, {docId: 'd-abc123'})  [opens specific doc]\n"
            "- 'edit notes for T1' → open_app(document, {entityId: 't-...'})  [opens entity notes]\n"
            "- 'show my recipes' → open_app(recipes)\n"
            "- 'show me my positions' → open_app(app_type='investment', tab='portfolio')\n"
            "- 'what are my positions' → open_app(app_type='investment', tab='portfolio')\n"
            "- 'show rebalance' → open_app(app_type='investment', tab='rebalance')\n"
            "- 'show analysis history' → open_app(app_type='investment', tab='history')\n"
            "- 'show my reminders' → open_app(app_type='reminders')\n"
            "- 'show my folders' → open_app(app_type='folders')\n"
            "- 'create a folder named X' → create the folder via API, then open_app(app_type='folder', folderId='fld-...')\n"
            "- 'open folder fld-abc123' → open_app(app_type='folder', folderId='fld-abc123')\n"
            "- 'show my to-do list' → open_app(app_type='todo')  AND get_todo_list(user)\n"
            "- 'add X to my to-do' → add_todo_item(user, X)\n"
            "- 'show my priorities' → open_app(app_type='prioritize')  AND list_focus(user)\n"
            "- 'what are my priorities' → open_app(app_type='prioritize')  AND list_focus(user)\n"
            "- 'show my backlog' → open_app(app_type='prioritize')  AND get_backlog_summary(user)\n"
            "- 'show home issues' → open_app(app_type='home', tab='issues')\n"
            "- 'open home maintenance' → open_app(app_type='home', tab='maintenance')\n"
            "- 'show home app' → open_app(app_type='home')\n"
            "For investment, ALWAYS pass the tab parameter: "
            "'dashboard', 'portfolio' (for positions/holdings), 'rebalance', or 'history'.\n"
            "For home, pass tab='issues', 'maintenance', 'appliances', 'insurance', 'contractors', 'automation', or 'locator'.\n"
            "Only fall back to text output if the user explicitly asks for a summary in chat, "
            "or if you need to answer a specific question about the data.\n\n"
            "## Feature Announcements\n"
            "When the user asks to announce a new feature or app to the family:\n"
            "1. If a spec exists, call read_feature_spec(spec_name) to get context\n"
            "2. Draft a friendly, concise announcement explaining what's new and how to use it\n"
            "3. Show the draft to the user in your response and ASK for approval — then STOP. Do NOT call broadcast_announcement yet.\n"
            "4. ONLY after the user replies with approval (e.g. 'send it', 'looks good', 'yes'), call broadcast_announcement in that next turn.\n"
            "IMPORTANT: NEVER draft and broadcast in the same turn. The user must explicitly approve first.\n"
            "For smaller features without a spec, draft from the user's description.\n"
            "Examples:\n"
            "- 'announce the new to-do app' → read_feature_spec('TODO'), draft, STOP and wait for approval\n"
            "- user says 'send it' → broadcast_announcement(message)\n"
            "- 'tell everyone about the new snooze feature' → draft from description, STOP and wait for approval"
        )
    elif req.channel == "discord":
        system_prompt += (
            "\n\n## Brainstorming on Discord\n"
            "The user is on Discord. Brainstorming tools (create_idea, list_ideas, search_ideas, "
            "read_idea_document, append_to_idea_document, etc.) work here — you can create ideas, "
            "read their documents, and output content in chat. However, the full brainstorming "
            "experience (live editor, real-time updates, markdown preview) is on Skipper Desktop. "
            "When the user interacts with brainstorming ideas, fulfill their request but also "
            "mention: 'For the best brainstorming experience with a live editor, check out Skipper Desktop.'"
            "\nOnly mention this once per conversation, not every message."
        )

    # NOTE: App context is dynamic — injected into the second system message
    # in handle_chat(), not here.

    return system_prompt


def _inject_app_context(system_prompt: str, app_context: dict,
                        extra_categories: set[str]) -> str:
    """Inject active desktop context (entity, document, brainstorming, etc.)."""
    ctx_parts = []
    app_name = app_context.get("app", "")
    view = app_context.get("view", "")
    entity_id = app_context.get("entityId", "")
    entity_name = app_context.get("entityName", "")
    entity_type = app_context.get("entityType", "")
    parent_id = app_context.get("parentId", "")
    parent_name = app_context.get("parentName", "")
    selected_text = app_context.get("selectedText", "")

    if app_name:
        ctx_parts.append(f"Active app: {app_name}")
    if view:
        ctx_parts.append(f"View: {view}")
    if entity_id and entity_name:
        ctx_parts.append(f"Looking at: {entity_name} ({entity_id})")
    elif entity_id:
        ctx_parts.append(f"Looking at entity: {entity_id}")
    if entity_type:
        ctx_parts.append(f"Entity type: {entity_type}")
    if parent_id and parent_name:
        ctx_parts.append(f"Parent: {parent_name} ({parent_id})")

    if ctx_parts:
        context_note = (
            "\n\nWhen the user says 'this', 'it', 'here', 'this task', 'this project', etc., "
            "they are referring to the entity shown above. Use the entity ID directly "
            "in tool calls — do NOT ask them to clarify which entity they mean."
        )
        if entity_type == "document":
            context_note += (
                "\n\nThe user is LOOKING AT this document right now in the editor. "
                "When they say 'this', 'it', 'reformat this', 'edit this', 'fix it', etc., "
                "they mean THIS OPEN DOCUMENT — not any linked entity, not goal notes, not anything else. "
                "Default to the open document unless they explicitly name a different entity."
                "\n\nYou can:"
                "\n- Read its content with get_doc (if not already shown below)"
                "\n- Update it with update_doc — pass the full new content"
                "\n- The desktop auto-refreshes after updates, so just make the change."
                "\nDo NOT ask which entity. Do NOT ask the user to paste content. Just act."
            )
        elif entity_type == "idea":
            part_id = app_context.get("partId", "")
            context_note += (
                "\n\n## BRAINSTORMING MODE ACTIVE"
                "\nThe user has a brainstorming idea open in the editor. You are now in "
                "**brainstorming mode** — a creative, generative mindset."
                "\n\n### Behavior Rules:"
                "\n1. **ALWAYS USE revise_idea_document for ALL document changes.** This is the "
                "primary tool. It shows the user inline diffs (green additions, red deletions) "
                "with Accept/Reject buttons — just like Windsurf. The user reviews and approves "
                "every change. Use it for adding content, editing content, restructuring — everything."
                "\n2. **Be prolific.** Generate many ideas, angles, and possibilities — not "
                "just one or two. Use bullet points, subheadings, and creative exploration. "
                "Think expansively. Quantity breeds quality in brainstorming."
                "\n3. **Build on what's there.** Read the existing content and ADD to it. "
                "Don't repeat what's already written. Extend, branch, deepen."
                "\n4. **Don't ask for permission or clarification** unless truly ambiguous. "
                "The user wants you to generate and write. Just do it."
                "\n5. **Respond briefly in chat** with a short summary of what you proposed. "
                "The actual content appears as a diff in the editor for the user to review."
                "\n6. **Match the user's energy.** If they give a vague prompt like "
                "'add some ideas' or 'flesh this out', go broad and creative. If they give "
                "a specific prompt like 'add a section about X', be focused but thorough."
                "\n\n### Tools (use ONLY brainstorming tools, NOT doc tools):"
                "\n- `revise_idea_document(idea_id, instruction)` — **USE THIS FOR EVERYTHING.** "
                "Proposes changes as inline diffs the user can Accept or Reject. Works for adding "
                "new content, editing existing content, restructuring, rewriting — all of it."
                "\n- `read_idea_document(idea_id)` — read current content"
                "\n- `update_idea(idea_id, ...)` — update metadata (title, status, tags, etc.)"
                "\n- `append_to_idea_document(idea_id, text)` — quick-append without review (avoid)"
                "\n- `update_idea_document(idea_id, content)` — full replace without review (avoid)"
                "\n\n### Important:"
                "\n- ALWAYS prefer `revise_idea_document` over append or update — the user wants "
                "to review changes before they are applied."
                "\n- Your `instruction` should describe the change clearly, e.g. 'Add a section about "
                "Prioritize integration for showing current focus' or 'Rewrite the intro to be more concise'."
                f"\n\n**Idea ID: {entity_id}**"
            )
            if part_id:
                context_note += f"\n**Active part ID: {part_id}**"
            if selected_text:
                context_note += (
                    f"\n\n**The user has highlighted this text in the editor:**"
                    f"\n```\n{selected_text}\n```"
                    "\nWhen they say 'this', 'this section', 'this part', 'change this', etc., "
                    "they are referring to the highlighted text above. Your `instruction` to "
                    "`revise_idea_document` should specifically reference what to do with this section."
                )
            context_note += (
                "\n\nNEVER use create_doc, update_doc, append_to_doc, or other doc tools. "
                "The desktop auto-refreshes after updates."
            )
        elif entity_type in ("goal", "project", "task"):
            context_note += (
                f"\n\nThis is a {entity_type}. You can use update_entity, update_entity_notes, "
                "and other goal tools with this entity ID directly."
            )
        system_prompt += (
            "\n\n## Active Desktop Context\n"
            + "\n".join(ctx_parts)
            + context_note
        )

    # --- Document / idea content ---
    doc_content = app_context.get("documentContent", "")
    if doc_content and entity_type == "document":
        system_prompt += (
            f"\n\n## Open Document Content ({entity_name or entity_id})\n"
            f"The user currently has this document open in the editor:\n"
            f"```\n{doc_content[:8000]}\n```\n"
            "You can see and reference this content directly. When the user says "
            "'reformat this', 'edit this doc', 'fix this', etc., they mean THIS document. "
            "Use update_doc with the document ID to modify it. After editing, the document "
            "editor will auto-refresh to show the changes."
        )
    elif doc_content and entity_type == "idea":
        system_prompt += (
            f"\n\n## Current Idea Document Content ({entity_name or entity_id})\n"
            f"This is what the user sees RIGHT NOW in the editor:\n"
            f"```\n{doc_content[:8000]}\n```\n"
            "\n**Your job: BUILD ON THIS.** Read it carefully, then ADD new content "
            "that extends, deepens, or branches from what's already there. "
            "Do not repeat existing content. Do not describe what you could add — "
            "actually add it using append_to_idea_document or update_idea_document. "
            "The user will see changes appear in the editor in real time."
        )
    elif entity_type == "idea":
        # No content yet — idea doc is empty
        system_prompt += (
            f"\n\n## Idea Document ({entity_name or entity_id})\n"
            "The idea document is currently **empty**. The user is looking at a blank page. "
            "When they ask you to generate ideas, write content, brainstorm, etc., "
            "USE append_to_idea_document to write directly into the doc. "
            "Start with a heading and jump right into generating content."
        )

    if selected_text:
        system_prompt += (
            "\n\n## Selected Text in Document\n"
            f"The user has highlighted the following text in their open document ({entity_id}):\n"
            f"```\n{selected_text[:2000]}\n```\n"
            "When the user says 'edit this', 'rewrite this', 'change this section', etc., "
            "they mean THIS selected text. Use enhance_doc or update_doc to modify "
            "the document, targeting this specific section. After editing, the document "
            "editor will auto-refresh to show the changes."
        )

    return system_prompt


def _inject_voice_context(system_prompt: str, app_context: dict) -> str:
    """Inject device/room context for chained STT voice requests."""
    try:
        from app_platform.voice.prompting import build_device_context
        device_context = build_device_context(app_context)
    except Exception as exc:
        logger.debug("VOICE: Could not build voice device context: %s", exc)
        device_context = ""

    system_prompt += (
        "\n\n## Voice Request Context\n"
        "The user spoke this request through a voice interface. Keep the response "
        "brief, conversational, and suitable for text-to-speech playback. "
        "Do not mention transcription unless there is a clear recognition issue. "
        "For ambiguous home-control requests, use the device room context when "
        "it is available and safe. Require confirmation for dangerous, expensive, "
        "security-related, or irreversible actions.\n"
    )
    if device_context:
        system_prompt += "\n" + device_context
    return system_prompt


# ---------------------------------------------------------------------------
# Skipper active work context
# ---------------------------------------------------------------------------

async def _inject_skipper_work_context(system_prompt: str) -> str:
    """Inject a summary of goals/projects/tasks Skipper currently owns.

    This gives the chat persona awareness of its autonomous work so it can
    answer questions like 'what are you working on?' accurately.
    """
    try:
        # goals is a required app; data layer moved here in the packaging chunk.
        import apps.goals.data as _dl_goals
        from app_platform import config as _platform_config

        # The onboarding goal is rendered concisely (and actively) by
        # _inject_onboarding_context — exclude it here so its full 27-project agenda+tour
        # tree isn't ALSO dumped verbatim every turn (that re-added ~24k tokens onboarding).
        _onb_goal_id = (_platform_config.get("onboarding_seeded", scope="app:goals") or {}).get("goal_id")

        def _fetch():
            all_goals = _dl_goals.list_entities("g-")
            my_goals = [
                g for g in all_goals
                if "skipper" in (g.get("owners") or [])
                and g.get("status") not in ("done", "archived")
                and g.get("id") != _onb_goal_id
            ]
            if not my_goals:
                return None

            lines = []
            for g in my_goals:
                lines.append(f"### {g['name']} ({g['id']}) — {g.get('status', 'active')}")
                projects = _dl_goals.get_projects_for_goal(g["id"])
                for p in projects:
                    lines.append(f"  Project: {p['name']} ({p['id']}) — {p.get('status', '?')}")
                    tasks = _dl_goals.get_tasks_for_project(p["id"])
                    for t in tasks:
                        status_icon = {"done": "\u2705", "in_progress": "\U0001f504", "not_started": "\u2b1c"}.get(
                            t.get("status", ""), "\u2b1c")
                        lines.append(f"    {status_icon} {t['name'][:80]} ({t['id']}) — {t.get('status', '?')}")
            return "\n".join(lines)

        summary = await asyncio.to_thread(_fetch)
        if summary:
            system_prompt += (
                "\n\n## Skipper's Own Active Work (NOT the user's)\n"
                "The following goals, projects, and tasks are YOUR OWN work — you (Skipper) are the "
                "owner and you are autonomously making progress on these through your thinking domains. "
                "These are NOT the user's tasks. When someone asks 'what are you working on?' or "
                "'what project are you doing?', refer to these:\n\n"
                + summary
            )
    except Exception as e:
        logger.debug("SKIPPER_WORK: Could not load active work: %s", e)

    return system_prompt


async def _inject_onboarding_context(system_prompt: str) -> tuple[str, bool]:
    """If the one-time first-run onboarding goal is still active, steer the CHAT agent to
    actively WALK its agenda — rather than treat it as background work and dive into deep app
    setup on the user's first stated intent. Returns (prompt, is_onboarding); the caller pins
    the goals tool category when onboarding so the agent can update_item to mark agenda progress
    (without it the agenda never advances — observed live: 0 update_item calls, every topic stuck
    not_started, so it just kept re-drilling the first intent).

    Why this exists: `_inject_skipper_work_context` frames Skipper's goals as autonomous
    background work ("refer to these when asked what you're working on"). For onboarding that's
    wrong — it's the agent's live script. Live testing showed that without this, on "I want help
    with chores" the agent built out full chore zones/rotations (~20 tool calls) and never walked
    household → intent → location → Discord → integrations.
    """
    try:
        from app_platform import config as platform_config
        seeded = platform_config.get("onboarding_seeded", scope="app:goals") or {}
        goal_id = seeded.get("goal_id")
        if not goal_id:
            return system_prompt, False

        import apps.goals.data as _dl_goals

        def _fetch():
            goal = next((g for g in _dl_goals.list_entities("g-") if g.get("id") == goal_id), None)
            if not goal or goal.get("status") in ("done", "archived"):
                return None
            projects = _dl_goals.get_projects_for_goal(goal_id)
            # Agenda topics are the ordered non-tour projects; tours start with "Try the ".
            return [p for p in projects if not (p.get("name") or "").startswith("Try the ")]

        agenda = await asyncio.to_thread(_fetch)
        if not agenda:
            return system_prompt, False

        done = [p for p in agenda if p.get("status") == "done"]
        current = next((p for p in agenda if p.get("status") != "done"), None)
        rows = "\n".join(
            f"  {'✅' if p.get('status') == 'done' else '⬜'} {p.get('name')} ({p.get('id')})"
            for p in agenda
        )
        focus = (
            f"Current focus: **{current['name']}** ({current['id']}).\n"
            if current else
            "All agenda topics are done — now move to the per-app tours (pruned HARD to their "
            "intent). Do NOT close the goal until those are done or they say they're all set.\n"
        )
        system_prompt += (
            "\n\n## You are ONBOARDING this user RIGHT NOW (active — not background work)\n"
            "This is your live first-run setup. Walk the agenda below IN ORDER, ONE gentle nudge "
            "at a time.\n"
            "- ADVANCE: the moment a topic is covered in conversation, call "
            "update_item(item_id, status=\"done\") for that agenda project, THEN move to the next "
            "⬜ topic in the SAME reply. Do NOT keep re-drilling a topic you've already covered — "
            "advancing the agenda matters more than exhaustively configuring one area.\n"
            "- CAPTURE, don't configure: remember household members + their stated intent so you "
            "can personalize, but do NOT do deep app setup during the agenda (no full chore "
            "rotations/zones/schedules now — that's the per-app tour later, or when they explicitly "
            "ask). A couple of tool calls, not twenty.\n"
            "- TAILOR to the household you actually learn — do NOT assume there are children. Only "
            "pursue child-specific setup (kid chores, school reminders) if the family really "
            "includes kids; for a couple or a single person, match what you suggest to who's there. "
            "Read the household FIRST and let it decide what's even relevant before going down an "
            "app's path.\n"
            "- SKIPPING A TOPIC IS NOT QUITTING. If they skip or decline ONE topic (e.g. 'skip "
            "Discord'), mark just THAT topic done and CONTINUE to the next ⬜ — do NOT close, "
            "cancel, or pause the whole onboarding. Only end onboarding entirely if they clearly "
            "want to stop ALL setup (e.g. 'I'm good, I'll explore on my own').\n"
            "- AGENDA DONE ≠ ONBOARDING DONE. When every agenda topic is done, do NOT close the "
            "goal yet — the per-app tours are the rest of it. PRUNE the tours HARD to their stated "
            "intent: proactively walk only the few apps that match how they want to use Skipper "
            "(e.g. Chores, Reminders) and don't bother walking the rest. Do NOT repeat anything "
            "onboarding already covered — if they already engaged an app (gave chore details, set "
            "reminders), acknowledge and BUILD ON it ('we already started your chores — want me to "
            "finish the rotation?'), never re-introduce it from scratch. Close the goal as COMPLETE "
            "(done, not cancelled) ONLY after the relevant tours are done or they say they're all "
            "set — then they can explore the rest on their own.\n"
            "- HOW to close: when they've done the essentials and are SATISFIED ('I'm all set', "
            "'that's all I need'), mark the onboarding goal DONE (update_item status=\"done\") — a "
            "successful finish. Use stop_onboarding ONLY when they want you to stop reaching out "
            "before they're set ('I'll explore on my own', 'stop asking') — it records a CANCEL, so "
            "don't use it for a happy 'all set'.\n"
            f"Agenda ({len(done)}/{len(agenda)} done):\n{rows}\n{focus}"
        )
        return system_prompt, True
    except Exception as e:
        logger.debug("ONBOARDING_CTX: %s", e)

    return system_prompt, False


async def _inject_proactive_dm_context(system_prompt: str, user_id: str) -> tuple[str, bool]:
    """Flag when the user may be replying to a proactive DM Skipper sent.

    Thinking domains (PM/goals) send proactive DMs and record a pending_action.
    When that user later chats, the normal agent loop has none of the sender's
    context — so a reply like "not yet" or "stop" lands cold. This injects a
    COMPACT block naming the pending message + its kind, and tells the model to
    pull full guidance via get_proactive_reply_guide() if the turn is a reply.
    Returns (system_prompt, has_pending); has_pending force-includes the tool.
    See specs/PROACTIVE_MESSAGING.md.
    """
    try:
        import apps.goals.data as _dl_goals
        pending = await asyncio.to_thread(_dl_goals.pending_dms_for_user, user_id)
    except Exception as e:
        logger.debug("PROACTIVE_REPLY: Could not load pending DMs: %s", e)
        return system_prompt, False

    if not pending:
        return system_prompt, False

    top = pending[0]
    kind = top.get("kind", "goal")
    sent_at = (top.get("sent_at", "") or "")[:16].replace("T", " ")
    dm_text = (top.get("dm_text", "") or "").strip()
    extra = ""
    if len(pending) > 1:
        extra = f" (and {len(pending) - 1} other pending message(s))"

    system_prompt += (
        "\n\n## ⚠ Possible reply to a proactive message\n"
        "You (Skipper) recently reached out to this user on your own initiative; "
        "they have not clearly resolved it, so their next message MAY be a reply"
        f"{extra}. Most recent — kind \"{kind}\", sent {sent_at}:\n"
        f"  “{dm_text}”\n"
        "If the user's message reads as a response to that outreach, you are "
        "CONTINUING that thread: do not restart or re-introduce yourself. Call "
        f"get_proactive_reply_guide(kind=\"{kind}\") for the full guidance before replying. "
        "If the message is clearly unrelated, ignore this and answer normally."
    )
    return system_prompt, True

# NOTE: Scrum-item injection used to live here. It was a tight coupling
# between this platform-layer chat_domain and the optional scrum app —
# the call ran on every chat turn and queried `scrum_items`, which DB-error
# spammed every install that did not have the optional scrum package.
# Removed in the Phase 1d UI-pruning cleanup. When the scrum app lands as
# its own repo, it can register a prompt-extender hook from its own
# handlers.py rather than being hardcoded here.


# ---------------------------------------------------------------------------
# Memory + knowledge retrieval
# ---------------------------------------------------------------------------

async def _retrieve_context(user_message: str, system_prompt: str,
                            user_id: str) -> str:
    """Embed message, retrieve relevant memories + knowledge, inject into prompt."""
    # Embed the user message ONCE and share the vector with both retrievers
    shared_embedding = None
    try:
        shared_embedding = await asyncio.to_thread(get_embedding, user_message)
    except Exception as e:
        logger.warning("PERF: Shared embedding failed, retrievers will embed individually: %s", e)

    # Run memory + knowledge + folder retrieval in parallel
    relevant_task = asyncio.to_thread(
        get_relevant_memories, user_message, user_id=user_id,
        query_embedding=shared_embedding,
    )
    knowledge_task = asyncio.to_thread(
        get_relevant_knowledge, user_message,
        query_embedding=shared_embedding,
    )
    folder_task = asyncio.to_thread(
        get_relevant_folder_knowledge, user_message,
        query_embedding=shared_embedding,
    )
    relevant, knowledge_chunks, folder_results = await asyncio.gather(
        relevant_task, knowledge_task, folder_task)

    memory_context = format_memories_for_context(relevant)
    if memory_context:
        system_prompt += "\n\n" + memory_context
        logger.debug("MEMORY: Injected %d relevant memories for user '%s'",
                     len(relevant), user_id)

    knowledge_context = format_knowledge_for_context(knowledge_chunks)
    if knowledge_context:
        system_prompt += "\n\n" + knowledge_context
        logger.debug("KNOWLEDGE: Injected %d relevant chunks for user '%s'",
                     len(knowledge_chunks), user_id)

    folder_context = format_folder_knowledge_for_context(folder_results)
    if folder_context:
        system_prompt += "\n\n" + folder_context
        logger.debug("FOLDER_KNOWLEDGE: Injected %d relevant folder items for user '%s'",
                     len(folder_results), user_id)

    return system_prompt
