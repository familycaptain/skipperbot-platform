"""
Unified Agent Loop
==================
The universal LLM + tool execution engine for SkipperBot.

Every LLM interaction — chat, thinking, exploration — runs through this
single module. Callers provide messages, tools, a tool dispatcher, and
optional hooks for caller-specific behavior (acks, events, interceptions).

Phase 2.8 of the Thinking Architecture.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

from config import logger, openai_client, OPENAI_MODEL


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    """Record of a single tool call made during the loop."""
    name: str
    args: dict
    result: str
    tool_call_id: str


@dataclass
class AgentResult:
    """Result returned by the agent loop."""
    response_text: str | None
    messages: list[dict]
    tool_calls_made: list[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    turns: int = 0


@dataclass
class LoopHooks:
    """Optional callbacks for caller-specific behavior during the loop.

    before_tool_call(name, args, tool_call_id)
        Called before each tool is dispatched. Can send ack messages, etc.

    after_tool_call(name, args, result, tool_call_id) -> str | None
        Called after each tool returns. Can transform the result (return new
        string) or return None to keep original. Used for event notifications,
        direct-display interception, proposal interception, etc.

    after_round(messages, tools) -> (list | None, list[dict])
        Called after all tool calls in a round are processed, before the next
        LLM call. Returns (new_tools_or_None, extra_messages_to_append).
        Used for tool refresh/rebuild and injecting system constraints.
    """
    before_tool_call: Optional[Callable[..., Awaitable[None]]] = None
    after_tool_call: Optional[Callable[..., Awaitable[Optional[str]]]] = None
    after_round: Optional[Callable[..., Awaitable[tuple]]] = None


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

async def run(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    max_turns: int = 20,
    max_tool_calls: int = 50,
    tool_dispatch: Callable[[str, dict], Awaitable[str]] = None,
    hooks: LoopHooks | None = None,
) -> AgentResult:
    """Run the agent loop: LLM call → tool execution → repeat.

    Args:
        messages: Full message list (system + history + current user turn).
        tools: OpenAI-format tool definitions (or None for no tools).
        model: Model name (defaults to OPENAI_MODEL from config).
        max_turns: Max LLM round-trips before forced stop.
        max_tool_calls: Max total tool calls before forced stop.
        tool_dispatch: async (name, args) -> result string. REQUIRED if tools are provided.
        hooks: Optional caller-specific callbacks (see LoopHooks).

    Returns:
        AgentResult with response text, full message history, tool call
        records, token counts, and number of turns.
    """
    model = model or OPENAI_MODEL
    hooks = hooks or LoopHooks()
    result = AgentResult(response_text=None, messages=messages)

    total_tool_calls = 0

    for turn in range(max_turns):
        t_start = time.monotonic()
        completion = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model=model,
            messages=messages,
            tools=tools if tools else None,
        )
        elapsed = time.monotonic() - t_start
        logger.info("AGENT_LOOP: turn=%d llm_call=%.2fs", turn + 1, elapsed)

        if completion.usage:
            result.prompt_tokens += completion.usage.prompt_tokens
            result.completion_tokens += completion.usage.completion_tokens
            # Log prompt cache stats (OpenAI auto-caches identical prompt prefixes)
            ptd = getattr(completion.usage, "prompt_tokens_details", None)
            cached = getattr(ptd, "cached_tokens", 0) if ptd else 0
            if cached:
                pct = round(100 * cached / completion.usage.prompt_tokens) if completion.usage.prompt_tokens else 0
                logger.info("AGENT_LOOP: turn=%d prompt=%d cached=%d (%d%%) completion=%d",
                            turn + 1, completion.usage.prompt_tokens, cached, pct,
                            completion.usage.completion_tokens)
            else:
                logger.info("AGENT_LOOP: turn=%d prompt=%d (no cache hit) completion=%d",
                            turn + 1, completion.usage.prompt_tokens,
                            completion.usage.completion_tokens)

        assistant_message = completion.choices[0].message
        result.turns = turn + 1

        # No tool calls → final response
        if not assistant_message.tool_calls:
            result.response_text = assistant_message.content
            break

        # --- Tool execution round ---
        messages.append(assistant_message)

        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            tool_call_id = tool_call.id

            logger.debug("AGENT_LOOP: tool_call %s(%s)", tool_name,
                         json.dumps(tool_args, indent=2))

            # Pre-dispatch hook
            if hooks.before_tool_call:
                await hooks.before_tool_call(tool_name, tool_args, tool_call_id)

            # Dispatch
            if tool_dispatch is None:
                tool_result = f"Error: no tool dispatcher configured for {tool_name}"
            else:
                tool_result = await tool_dispatch(tool_name, tool_args)

            logger.debug("AGENT_LOOP: tool_result %s: %s", tool_name,
                         (tool_result[:500] if tool_result else "(empty)"))

            # Post-dispatch hook (can transform result)
            if hooks.after_tool_call:
                transformed = await hooks.after_tool_call(
                    tool_name, tool_args, tool_result, tool_call_id
                )
                if transformed is not None:
                    tool_result = transformed

            record = ToolCallRecord(
                name=tool_name,
                args=tool_args,
                result=tool_result or "(no output)",
                tool_call_id=tool_call_id,
            )
            result.tool_calls_made.append(record)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": tool_result or "(no output)",
            })

            total_tool_calls += 1
            if total_tool_calls >= max_tool_calls:
                logger.warning("AGENT_LOOP: max_tool_calls (%d) reached, stopping",
                               max_tool_calls)
                break

        # Backfill stub responses for any unexecuted tool_calls so the
        # message sequence stays valid (every tool_call_id needs a response).
        executed_ids = {m["tool_call_id"] for m in messages
                        if isinstance(m, dict) and m.get("role") == "tool"}
        for tc in assistant_message.tool_calls:
            if tc.id not in executed_ids:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "(skipped — tool call limit reached)",
                })

        # Post-round hook (tool refresh, extra system messages, etc.)
        if hooks.after_round:
            new_tools, extra_messages = await hooks.after_round(messages, tools)
            if new_tools is not None:
                tools = new_tools
            for msg in extra_messages:
                messages.append(msg)

        if total_tool_calls >= max_tool_calls:
            # Force a final response with no tools
            completion = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model=model,
                messages=messages,
            )
            if completion.usage:
                result.prompt_tokens += completion.usage.prompt_tokens
                result.completion_tokens += completion.usage.completion_tokens
            result.response_text = completion.choices[0].message.content
            result.turns += 1
            break
    else:
        # max_turns exhausted — force final response with no tools
        logger.warning("AGENT_LOOP: max_turns (%d) reached, forcing final response", max_turns)
        completion = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model=model,
            messages=messages,
        )
        if completion.usage:
            result.prompt_tokens += completion.usage.prompt_tokens
            result.completion_tokens += completion.usage.completion_tokens
        result.response_text = completion.choices[0].message.content
        result.turns += 1

    result.messages = messages
    logger.info("AGENT_LOOP: complete — turns=%d, tools=%d, tokens=%d/%d",
                result.turns, len(result.tool_calls_made),
                result.prompt_tokens, result.completion_tokens)
    return result
