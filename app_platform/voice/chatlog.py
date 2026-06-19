"""Shared live voice transcript persistence.

This module only turns realtime voice transcripts into normal chat turns and
queues them for the existing memory ingestion worker. It does not digest or
process memory itself.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from chatlog_store import generate_turn_id, save_turn
from config import logger
from app_platform.voice.session import get_session


_RECENT_DEDUPE_SECONDS = 5.0
_MAX_PENDING_USER_TURNS = 20


@dataclass
class _VoiceSessionBuffer:
    pending_users: Deque[str] = field(default_factory=deque)
    recent_assistant_texts: Deque[tuple[float, str]] = field(default_factory=deque)


_LOCK = threading.Lock()
_BUFFERS: dict[str, _VoiceSessionBuffer] = {}
_PENDING_TASKS: set[asyncio.Task] = set()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


async def record_voice_transcript(
    session_id: str,
    role: str,
    text: str,
    *,
    user_id: str | None = None,
) -> str | None:
    """Record a realtime voice transcript event.

    User and assistant transcript events arrive separately. We buffer user
    transcript text and persist a normal chat turn when the next assistant
    transcript arrives.

    Returns the turn id when a chat turn was scheduled for persistence.
    """
    normalized = _normalize_text(text)
    role = (role or "").lower().strip()
    if not session_id or role not in {"user", "assistant"} or not normalized:
        return None

    turn: tuple[str, str, str, str] | None = None
    with _LOCK:
        buffer = _BUFFERS.setdefault(session_id, _VoiceSessionBuffer())
        now = time.monotonic()

        while (
            buffer.recent_assistant_texts
            and now - buffer.recent_assistant_texts[0][0] > _RECENT_DEDUPE_SECONDS
        ):
            buffer.recent_assistant_texts.popleft()

        if role == "user":
            buffer.pending_users.append(normalized)
            while len(buffer.pending_users) > _MAX_PENDING_USER_TURNS:
                dropped = buffer.pending_users.popleft()
                logger.warning(
                    "VOICE_CHATLOG: Dropped unpaired user transcript for %s: %s",
                    session_id[:8],
                    dropped[:120],
                )
            return None

        if any(prior == normalized for _, prior in buffer.recent_assistant_texts):
            logger.debug(
                "VOICE_CHATLOG: Ignored duplicate assistant transcript for %s",
                session_id[:8],
            )
            return None

        buffer.recent_assistant_texts.append((now, normalized))
        if not buffer.pending_users:
            logger.debug(
                "VOICE_CHATLOG: Assistant transcript without pending user for %s: %s",
                session_id[:8],
                normalized[:120],
            )
            return None

        resolved_user_id = user_id or (get_session(session_id) or {}).get("user_id", "")
        if not resolved_user_id:
            logger.warning("VOICE_CHATLOG: Cannot persist %s without user_id", session_id[:8])
            return None

        turn_id = generate_turn_id()
        user_message = buffer.pending_users.popleft()
        turn = (resolved_user_id, user_message, normalized, turn_id)

    if not turn:
        return None

    task = asyncio.create_task(_persist_voice_turn(*turn))
    _PENDING_TASKS.add(task)
    task.add_done_callback(_PENDING_TASKS.discard)
    return turn[3]


async def _persist_voice_turn(
    user_id: str,
    user_message: str,
    assistant_message: str,
    turn_id: str,
) -> None:
    await asyncio.to_thread(
        _persist_voice_turn_sync,
        user_id,
        user_message,
        assistant_message,
        turn_id,
    )


def _persist_voice_turn_sync(
    user_id: str,
    user_message: str,
    assistant_message: str,
    turn_id: str,
) -> None:
    try:
        save_turn(
            user_id=user_id,
            user_message=user_message,
            assistant_message=assistant_message,
            turn_id=turn_id,
            channel="voice",  # tag the surface so voice turns are excluded from the web reload (issue #23)
        )
    except Exception as exc:
        logger.error("VOICE_CHATLOG: Failed to save turn %s for %s: %s", turn_id, user_id, exc)

    try:
        from data_layer.memory_queue import enqueue

        enqueue(
            source_type="chat_turn",
            payload={
                "user_message": user_message,
                "assistant_response": assistant_message,
                "user_id": user_id,
                "turn_id": turn_id,
            },
        )
        logger.debug("VOICE_CHATLOG: Queued voice turn %s for memory ingestion", turn_id)
    except Exception as exc:
        logger.error("VOICE_CHATLOG: Failed to enqueue turn %s: %s", turn_id, exc)


async def drain_voice_persistence(timeout: float = 5.0) -> None:
    """Wait briefly for background voice turn writes before process shutdown."""
    if not _PENDING_TASKS:
        return

    done, pending = await asyncio.wait(list(_PENDING_TASKS), timeout=timeout)
    for task in done:
        try:
            task.result()
        except Exception as exc:
            logger.error("VOICE_CHATLOG: Background persistence task failed: %s", exc)
    if pending:
        logger.warning("VOICE_CHATLOG: %d voice persistence task(s) still pending", len(pending))


def forget_voice_session(session_id: str) -> None:
    """Drop unpaired transcript buffer state for a finished voice session."""
    with _LOCK:
        _BUFFERS.pop(session_id, None)
