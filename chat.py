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
from chatlog_store import generate_turn_id
from chat_domain import ChatRequest, ChatResult

from typing import Optional, Callable, Awaitable

# Tool-router SLOTS per user: the categories the model has request_tools'd, kept across turns
# so a focused task's tools stay loaded (sticky) without re-routing the whole conversation.
# Passed by reference into ChatRequest.loaded_categories so in-turn loads/evictions persist.
session_slots: dict[str, list[str]] = {}

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
    log_event_id: str | None = None,
) -> str:
    """
    Process a chat message — session management + domain dispatch.

    Owns: session history, /clear, bootstrap, thinking indicator,
    persistence, digest. Delegates the actual LLM work to
    chat_domain.handle_chat() via the thinking scheduler.
    """
    # /clear — Phase 5b: history is the consciousness log (continuous, durable);
    # there is no per-session history to wipe. Reset the loaded tool slots and
    # process any trailing message.
    if user_message.strip().lower().startswith("/clear"):
        session_slots[user_id] = []
        logger.info("SESSION: Reset tool slots for '%s'", user_id)
        remainder = user_message.strip()[len("/clear"):].strip()
        if not remainder:
            return ("My memory is continuous now — there's no session history to clear. "
                    "(Loaded tool slots were reset.)")
        user_message = remainder

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

    # Phase 5b: conversation history IS the log timeline — one seq-ordered
    # multi-speaker stream from the consciousness log. (The in-memory sessions
    # dict is gone; the log is durable, so nothing to bootstrap.)
    _session_for_request = [{"role": "user", "content": user_message}]
    try:
        from app_platform.context import build_chat_timeline
        _history = await asyncio.to_thread(build_chat_timeline, user_id, None, log_event_id)
        _session_for_request = _history + [{"role": "user", "content": user_message}]
        logger.debug("SESSION [%s]: log-timeline history (%d msgs)", user_id, len(_history))
    except Exception:
        logger.warning("SESSION [%s]: log-timeline unavailable — bare turn", user_id, exc_info=True)

    request = ChatRequest(
        user_id=user_id,
        user_message=user_message,
        session_messages=_session_for_request,
        turn_id=current_turn_id,
        channel=channel,
        app_context=app_context,
        send_progress=send_progress,
        send_event=send_event,
        loaded_categories=session_slots.setdefault(user_id, []),
    )

    result = await dispatch_chat(request)
    response_text = result.response_text

    # Cancel the delayed thinking message if it hasn't fired yet
    if _thinking_task and not _thinking_task.done():
        _thinking_task.cancel()

    # Completed WRITE actions ride the reply row's payload (write_actions); the
    # timeline re-renders them as the anti-re-execution marker (§12.4) so the
    # model has a CONCRETE signal they already ran. Pairs with the "Don't
    # Repeat Completed Actions" rule in BEHAVIOR.md.
    _writes: set[str] = set()
    try:
        _WRITE_PREFIXES = ("add_", "create_", "send_", "update_", "set_", "log_", "delete_",
                           "remove_", "save_", "mark_", "schedule_", "connect_", "revise_")
        _writes = sorted({tc.name for tc in (result.tool_calls_made or [])
                          if any(tc.name.startswith(p) for p in _WRITE_PREFIXES)})
    except Exception:
        pass

    # Fire-and-forget: persist turn + digest in background (don't block response)
    async def _post_turn():
        _cl_inbound_id = None
        _cl_reply_id = None
        # Phase 5b: the consciousness log IS the record — the chat_turns
        # double-write is retired (the table stays, read-only, zero-loss).
        # Tool calls the model actually made ride the reply row's payload so
        # the scrollback projection replays them with no chat_turns hydration.
        # Results truncated to keep rows reasonable.
        _tool_calls = [
            {"name": tc.name, "args": tc.args,
             "result": (tc.result or "")[:4000], "id": tc.tool_call_id}
            for tc in (getattr(result, "tool_calls_made", None) or [])
        ]
        _reply_payload = {"chat_turn_id": current_turn_id,
                          **({"tool_calls": _tool_calls} if _tool_calls else {}),
                          **({"write_actions": list(_writes)} if _writes else {})}
        try:
            from app_platform.consciousness import shadow_log_event
            if log_event_id:
                # Attention mode: the inbound row already exists as the REAL
                # record; write only the outbound reply — a pure record
                # (§11.5 state 3b: Skipper's own output is never owed).
                _cl_inbound_id = log_event_id
                if response_text:
                    _out = await asyncio.to_thread(
                        shadow_log_event, kind="message", who_from="skipper",
                        who_to=user_id, domain="chat", surface=channel,
                        content=response_text, reply_to=log_event_id,
                        payload=_reply_payload,
                    )
                    _cl_reply_id = (_out or {}).get("id")
            else:
                _inbound = await asyncio.to_thread(
                    shadow_log_event, kind="message", who_from=user_id, who_to="skipper",
                    domain="chat", surface=channel, content=user_message,
                    payload={"chat_turn_id": current_turn_id},
                    pre_attended_by="legacy-pipeline",
                )
                _cl_inbound_id = (_inbound or {}).get("id")
                if response_text:
                    _out = await asyncio.to_thread(
                        shadow_log_event, kind="message", who_from="skipper", who_to=user_id,
                        domain="chat", surface=channel, content=response_text,
                        reply_to=(_inbound or {}).get("id"),
                        # write_actions -> the timeline re-renders the anti-re-execution
                        # marker the legacy session stored inline (§12.4).
                        payload=_reply_payload,
                        pre_attended_by="legacy-pipeline",
                    )
                    _cl_reply_id = (_out or {}).get("id")
        except Exception:
            logger.error("CONSCIOUSNESS: chat log write FAILED for '%s'", user_id, exc_info=True)
        try:
            from data_layer.memory_queue import enqueue
            enqueue(
                source_type="chat_turn",
                payload={
                    "user_message":       user_message,
                    "assistant_response": response_text or "",
                    "user_id":            user_id,
                    "turn_id":            current_turn_id,
                    # Phase 4 (specs/CONSCIOUSNESS.md §11.7): memories anchor on
                    # the log — the inbound cl- row (the fact-bearing utterance
                    # default), with the reply linked for full-exchange hops.
                    "cl_inbound_id":      _cl_inbound_id,
                    "cl_reply_id":        _cl_reply_id,
                },
            )
        except Exception as e:
            logger.error("DIGEST: Failed to enqueue turn '%s': %s", current_turn_id, str(e))

    asyncio.create_task(_post_turn())

    return response_text
