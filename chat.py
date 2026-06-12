"""
SkipperBot Chat Engine
Session management layer — owns conversation history, persistence, and UX.
Domain logic (prompt assembly, memory/knowledge, tools, agent loop) lives
in chat_domain.py and is dispatched through the thinking scheduler as a
priority-0 domain.
"""

import asyncio
import os
import random

from config import logger
from chatlog_store import save_turn, load_recent_turns, generate_turn_id
from chat_domain import ChatRequest, ChatResult

from typing import Optional, Callable, Awaitable

sessions: dict[str, list[dict]] = {}

# Sliding window: max conversation turns kept in session (1 turn = user + assistant)
# 50 turns = 100 messages ≈ safe for most context windows. Resolved from the
# System settings panel (scope=platform) → MAX_SESSION_TURNS env → default 50;
# guarded so a DB hiccup at import falls back to env. Restart to change.
def _max_session_turns() -> int:
    val = None
    try:
        from app_platform import settings as _settings
        val = _settings.get("max_session_turns", scope="platform", default=None)
    except Exception:
        val = os.getenv("MAX_SESSION_TURNS")
    try:
        return int(val) if val not in (None, "") else 50
    except (TypeError, ValueError):
        return 50


MAX_SESSION_TURNS = _max_session_turns()

# ---------------------------------------------------------------------------
# Varied thinking / keepalive message pools (zero-token, keyword + random)
# ---------------------------------------------------------------------------
_THINKING_MEMORY = [
    "Let me think about what I know...",
    "Hmm, let me recall...",
    "One sec, checking my memory...",
    "Let me see what I remember...",
    "Give me a moment to think back...",
]
_THINKING_KNOWLEDGE = [
    "Let me check my notes on that...",
    "Searching through what I've read...",
    "Let me look that up...",
    "One moment, checking the knowledge base...",
    "Let me dig into what I've got on that...",
]
_THINKING_GENERAL = [
    "Let me think about that...",
    "One moment...",
    "Let me look into it...",
    "Hmm, give me a sec...",
    "Let me dig into that...",
    "Thinking...",
    "Working on it...",
    "Let me see...",
]

_MEMORY_KEYWORDS = {"remember", "recall", "know about", "told you", "mentioned", "said", "who is", "who are"}
_KNOWLEDGE_KEYWORDS = {"wiki", "docs", "documentation", "article", "site", "page", "read about", "ingested"}

KEEPALIVE_MESSAGES = [
    "Still working on it...",
    "Bear with me...",
    "Almost there...",
    "Still digging into that...",
    "Hang tight...",
    "Still on it...",
    "Taking a bit longer than usual...",
]


def _pick_thinking_message(user_message: str, has_memories: bool, has_knowledge: bool) -> str:
    """Pick a varied, context-appropriate thinking message. Zero token cost."""
    msg_lower = user_message.lower()
    is_memory = any(w in msg_lower for w in _MEMORY_KEYWORDS)
    is_knowledge = any(w in msg_lower for w in _KNOWLEDGE_KEYWORDS)

    if is_memory and has_memories and not is_knowledge:
        return random.choice(_THINKING_MEMORY)
    if is_knowledge and has_knowledge and not is_memory:
        return random.choice(_THINKING_KNOWLEDGE)
    return random.choice(_THINKING_GENERAL)


async def process_chat(
    user_id: str,
    user_message: str,
    send_progress: Optional[Callable[[str], Awaitable[None]]] = None,
    channel: str = "discord",
    app_context: dict | None = None,
    send_event: Optional[Callable[[dict], Awaitable[None]]] = None,
) -> str:
    """
    Process a chat message — session management + domain dispatch.

    Owns: session history, /clear, bootstrap, thinking indicator,
    persistence, digest. Delegates the actual LLM work to
    chat_domain.handle_chat() via the thinking scheduler.
    """
    # /clear — wipe session history so the next message relies on memory/knowledge only
    if user_message.strip().lower().startswith("/clear"):
        sessions[user_id] = []
        logger.info("SESSION: Cleared session for '%s'", user_id)
        if send_progress:
            try:
                await send_progress("\U0001f9f9 Responding without chat history.")
            except Exception:
                pass
        # If there's a message after /clear, process it as the actual question
        remainder = user_message.strip()[len("/clear"):].strip()
        if not remainder:
            return "Session cleared. I'll rely on my memory and knowledge from here."
        user_message = remainder

    if user_id not in sessions:
        # Bootstrap from durable chat logs so context survives restarts
        recent = await asyncio.to_thread(load_recent_turns, user_id, max_turns=MAX_SESSION_TURNS)
        if recent:
            # Insert a boundary so the LLM knows prior turns are history,
            # not pending actions to re-execute.
            recent.append({
                "role": "assistant",
                "content": "[Session resumed — all actions above were already completed in a prior session.]"
            })
            logger.debug("SESSION: Bootstrapped %d messages from chat logs for '%s'", len(recent), user_id)
        else:
            logger.debug("SESSION: New session for user '%s'", user_id)
        sessions[user_id] = recent

    sessions[user_id].append({"role": "user", "content": user_message})

    # Pre-generate a chat turn ID so the agent can reference it in remember() calls
    current_turn_id = generate_turn_id()

    # Schedule a delayed thinking message — only shows if we're still working after 5s.
    _thinking_task = None
    if send_progress:
        async def _delayed_thinking():
            await asyncio.sleep(5)
            try:
                await send_progress(_pick_thinking_message(user_message, True, True))
            except Exception:
                pass
        _thinking_task = asyncio.create_task(_delayed_thinking())

    # --- Dispatch to chat domain via thinking scheduler (priority-0) ---
    from thinking_scheduler import dispatch_chat

    request = ChatRequest(
        user_id=user_id,
        user_message=user_message,
        session_messages=sessions[user_id],
        turn_id=current_turn_id,
        channel=channel,
        app_context=app_context,
        send_progress=send_progress,
        send_event=send_event,
    )

    result = await dispatch_chat(request)
    response_text = result.response_text

    # Cancel the delayed thinking message if it hasn't fired yet
    if _thinking_task and not _thinking_task.done():
        _thinking_task.cancel()

    # --- Session management ---
    sessions[user_id].append({"role": "assistant", "content": response_text or ""})

    # Sliding window: trim to last MAX_SESSION_TURNS turns (each turn = 2 messages)
    max_messages = MAX_SESSION_TURNS * 2
    if len(sessions[user_id]) > max_messages:
        sessions[user_id] = sessions[user_id][-max_messages:]
        logger.debug("SESSION [%s]: Trimmed to last %d turns", user_id, MAX_SESSION_TURNS)

    # Fire-and-forget: persist turn + digest in background (don't block response)
    async def _post_turn():
        try:
            # Persist the tools the model actually CALLED this turn (name/args/
            # result), so the web UI can replay them on session resume and for
            # diagnostics. Results truncated to keep rows reasonable.
            _tool_calls = [
                {"name": tc.name, "args": tc.args,
                 "result": (tc.result or "")[:4000], "id": tc.tool_call_id}
                for tc in (getattr(result, "tool_calls_made", None) or [])
            ]
            await asyncio.to_thread(
                save_turn, user_id=user_id, user_message=user_message,
                assistant_message=response_text or "", turn_id=current_turn_id,
                system_prompt=getattr(result, "system_prompt", "") or None,
                selected_tools=getattr(result, "selected_tools", None) or None,
                matched_guides=getattr(result, "matched_guides", None) or None,
                tool_calls=_tool_calls or None,
            )
        except Exception as e:
            logger.error("CHATLOG: Failed to save turn for '%s': %s", user_id, str(e))
        try:
            from data_layer.memory_queue import enqueue
            enqueue(
                source_type="chat_turn",
                payload={
                    "user_message":       user_message,
                    "assistant_response": response_text or "",
                    "user_id":            user_id,
                    "turn_id":            current_turn_id,
                },
            )
        except Exception as e:
            logger.error("DIGEST: Failed to enqueue turn '%s': %s", current_turn_id, str(e))

    asyncio.create_task(_post_turn())

    logger.debug("SESSION [%s]: %d messages in history", user_id, len(sessions[user_id]))

    return response_text
