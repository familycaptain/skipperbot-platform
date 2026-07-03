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

from config import logger
from providers.base import Turn, ToolCall
from providers.tier_resolver import resolve_chat, TierNotConfigured


# Soft-fail message when no model is configured (keyless boot before onboarding) or the selected
# tier has no key. str() of this reaches the user directly as the assistant's reply.
_SETUP_NEEDED_MSG = (
    "I can't respond yet — no language model is configured for this Skipper. "
    "Finish onboarding → Models to choose a provider and model."
)


def _is_no_api_key(exc: Exception) -> bool:
    """A provider raised the sanitized keyless failure (mirrors the '<name> call failed (NoApiKey)'
    shape from openai_provider / openai_compat) — never inspects a key value."""
    return "NoApiKey" in str(exc)


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
# Neutral-turn bridge (issue #39)
#
# The loop's PUBLIC contract stays OpenAI-dict-shaped: callers pass OpenAI-format
# `messages`, LoopHooks.after_round exchanges OpenAI dicts, and AgentResult.messages
# is OpenAI dicts. Neutralization is INTERNAL — we convert the dict messages to
# neutral Turns only at the moment of the provider call, and append OpenAI-format
# dicts back onto `messages`. So behavior + the caller contract are unchanged; only
# the LLM call now routes through the vendor-neutral provider.
# ---------------------------------------------------------------------------

def _messages_to_turns(messages: list[dict]) -> list[Turn]:
    turns: list[Turn] = []
    for m in messages:
        tcs = None
        if m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                fn = tc["function"]
                args = fn["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tcs.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args or {}))
        turns.append(Turn(role=m.get("role"), content=m.get("content"),
                          tool_calls=tcs, tool_call_id=m.get("tool_call_id"),
                          name=m.get("name")))
    return turns


def _assistant_dict(chat_result) -> dict:
    """Reconstruct the OpenAI-format assistant message dict from a neutral ChatResult,
    so `messages` stays uniformly dict-shaped (the public contract)."""
    msg: dict = {"role": "assistant", "content": chat_result.message.content}
    if chat_result.tool_calls:
        msg["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            for tc in chat_result.tool_calls
        ]
    return msg


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

async def run(
    messages: list[dict],
    tools: list[dict] | None = None,
    tier: str = "smart",
    max_turns: int = 20,
    max_tool_calls: int = 50,
    tool_dispatch: Callable[[str, dict], Awaitable[str]] = None,
    hooks: LoopHooks | None = None,
) -> AgentResult:
    """Run the agent loop: LLM call → tool execution → repeat.

    Args:
        messages: Full message list (system + history + current user turn).
        tools: OpenAI-format tool definitions (or None for no tools).
        tier: Model tier ("smart" | "fast"). The connector, MODEL, and key are ALL resolved
            from the selected tier (MODEL_FLEXIBILITY #44/#71) — the loop no longer reads a
            model id or an OPENAI_API_KEY from config/env.
        max_turns: Max LLM round-trips before forced stop.
        max_tool_calls: Max total tool calls before forced stop.
        tool_dispatch: async (name, args) -> result string. REQUIRED if tools are provided.
        hooks: Optional caller-specific callbacks (see LoopHooks).

    Returns:
        AgentResult with response text, full message history, tool call
        records, token counts, and number of turns. If no model is configured (or the tier
        has no key), returns a soft-fail AgentResult whose response_text is an actionable
        "Finish onboarding → Models" message — it never crashes the caller.
    """
    hooks = hooks or LoopHooks()
    result = AgentResult(response_text=None, messages=messages)

    # Resolve the tier -> (provider, model, key) ONCE. The key is threaded into every provider
    # call below; it is never logged or reprd. A missing tier (keyless boot) soft-fails here.
    try:
        provider, model, api_key = resolve_chat(tier)
    except TierNotConfigured:
        result.response_text = _SETUP_NEEDED_MSG
        return result

    total_tool_calls = 0

    for turn in range(max_turns):
        t_start = time.monotonic()
        try:
            chat_result = await asyncio.to_thread(
                provider.chat,
                turns=_messages_to_turns(messages),
                tools=tools if tools else None,
                model=model,
                api_key=api_key,
            )
        except RuntimeError as exc:
            # The tier resolved a connector but no usable key -> sanitized soft-fail (the key is
            # never inspected). Any other RuntimeError is a genuine call failure — re-raise.
            if _is_no_api_key(exc):
                result.response_text = _SETUP_NEEDED_MSG
                return result
            raise
        elapsed = time.monotonic() - t_start
        logger.info("AGENT_LOOP: turn=%d llm_call=%.2fs", turn + 1, elapsed)

        usage = chat_result.usage
        result.prompt_tokens += usage.prompt_tokens
        result.completion_tokens += usage.completion_tokens
        # Log prompt cache stats (OpenAI auto-caches identical prompt prefixes)
        cached = usage.cached_tokens
        if cached:
            pct = round(100 * cached / usage.prompt_tokens) if usage.prompt_tokens else 0
            logger.info("AGENT_LOOP: turn=%d prompt=%d cached=%d (%d%%) completion=%d",
                        turn + 1, usage.prompt_tokens, cached, pct, usage.completion_tokens)
        else:
            logger.info("AGENT_LOOP: turn=%d prompt=%d (no cache hit) completion=%d",
                        turn + 1, usage.prompt_tokens, usage.completion_tokens)

        result.turns = turn + 1
        tool_calls = chat_result.tool_calls

        # No tool calls → final response
        if not tool_calls:
            result.response_text = chat_result.content
            break

        # --- Tool execution round ---
        messages.append(_assistant_dict(chat_result))

        for tool_call in tool_calls:
            tool_name = tool_call.name
            tool_args = tool_call.arguments
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
        for tc in tool_calls:
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
            final = await asyncio.to_thread(
                provider.chat,
                turns=_messages_to_turns(messages),
                tools=None,
                model=model,
                api_key=api_key,
            )
            result.prompt_tokens += final.usage.prompt_tokens
            result.completion_tokens += final.usage.completion_tokens
            result.response_text = final.content
            result.turns += 1
            break
    else:
        # max_turns exhausted — force final response with no tools
        logger.warning("AGENT_LOOP: max_turns (%d) reached, forcing final response", max_turns)
        final = await asyncio.to_thread(
            provider.chat,
            turns=_messages_to_turns(messages),
            tools=None,
            model=model,
            api_key=api_key,
        )
        result.prompt_tokens += final.usage.prompt_tokens
        result.completion_tokens += final.usage.completion_tokens
        result.response_text = final.content
        result.turns += 1

    result.messages = messages
    logger.info("AGENT_LOOP: complete — turns=%d, tools=%d, tokens=%d/%d",
                result.turns, len(result.tool_calls_made),
                result.prompt_tokens, result.completion_tokens)
    return result
