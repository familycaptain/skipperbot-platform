"""Chat Logs — Postgres CRUD + pgvector Search
===============================================
Drop-in replacement for chatlog_store.py's flat-file persistence.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536


def ensure_chatlog_schema() -> None:
    """Idempotently add chat_turns columns that post-date the baseline (safe to
    call on every boot). Lets existing deployments pick up ``tool_calls``
    without a baseline re-run; fresh installs get it from 000_baseline.sql too.
    """
    from data_layer.db import execute
    execute("ALTER TABLE public.chat_turns ADD COLUMN IF NOT EXISTS tool_calls jsonb")


def save_turn(
    user_id: str,
    user_message: str,
    assistant_message: str,
    turn_id: Optional[str] = None,
    embedding: Optional[list[float]] = None,
    system_prompt: Optional[str] = None,
    selected_tools: Optional[list[Any]] = None,
    matched_guides: Optional[list[Any]] = None,
    tool_calls: Optional[list[Any]] = None,
) -> dict:
    """Save a chat turn to Postgres.

    Optional debug capture (``system_prompt``, ``selected_tools``,
    ``matched_guides``) lets us audit exactly what the LLM saw on this turn
    and which tool guides got injected via keyword routing. ``tool_calls`` is
    the list of tools the model actually invoked this turn (name/args/result) —
    persisted so the web UI can replay them on session resume and for diagnostics.
    """
    record = {
        "id": turn_id or f"c-{uuid.uuid4().hex[:8]}",
        "user_id": user_id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    emb_str = _vec(embedding) if embedding else None
    selected_tools_json = Json(selected_tools) if selected_tools is not None else None
    matched_guides_json = Json(matched_guides) if matched_guides is not None else None
    tool_calls_json = Json(tool_calls) if tool_calls is not None else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO chat_turns (id, user_id, user_message, assistant_message,
                                        embedding, created_at,
                                        system_prompt, selected_tools, matched_guides,
                                        tool_calls)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                record["id"], record["user_id"],
                record["user_message"], record["assistant_message"],
                emb_str, record["created_at"],
                system_prompt, selected_tools_json, matched_guides_json,
                tool_calls_json,
            ))
        conn.commit()
    return record


def get_recent_turns(user_id: str, limit: int = 20) -> list[dict]:
    """Get most recent chat turns for a user, oldest first."""
    rows = fetch_all("""
        SELECT * FROM (
            SELECT * FROM chat_turns WHERE user_id = %s
            ORDER BY created_at DESC LIMIT %s
        ) sub ORDER BY created_at ASC
    """, (user_id, limit))
    return [_row(r) for r in rows]


def search_turns(
    user_id: str,
    query_embedding: list[float],
    max_results: int = 10,
) -> list[dict]:
    """Semantic search over chat turns for a specific user."""
    from data_layer.db import fetch_all_vector  # raises ivfflat.probes for full recall
    emb_str = _vec(query_embedding)
    rows = fetch_all_vector("""
        SELECT *, 1 - (embedding <=> %s::vector) AS score
        FROM chat_turns
        WHERE user_id = %s AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (emb_str, user_id, emb_str, max_results))
    return [_row(r) | {"score": float(r["score"])} for r in rows]


def get_turns_since(user_id: str, since: str, limit: int = 20) -> list[dict]:
    """Get chat turns for a user since a given ISO timestamp, oldest first.

    Used by the thinking loop to pull conversation context — e.g., replies
    since a pending_action DM was sent.
    """
    rows = fetch_all("""
        SELECT * FROM chat_turns
        WHERE user_id = %s AND created_at >= %s
        ORDER BY created_at ASC
        LIMIT %s
    """, (user_id, since, limit))
    return [_row(r) for r in rows]


def count_turns(user_id: str) -> int:
    row = fetch_one("SELECT COUNT(*) AS cnt FROM chat_turns WHERE user_id = %s", (user_id,))
    return row["cnt"] if row else 0


def update_embedding(turn_id: str, embedding: list[float]):
    """Set the embedding for a specific chat turn."""
    emb_str = _vec(embedding)
    execute("UPDATE chat_turns SET embedding = %s WHERE id = %s", (emb_str, turn_id))


def _vec(embedding: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in embedding) + "]"


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row.get("user_id") or "",
        "timestamp": row["created_at"].isoformat() if row.get("created_at") else "",
        "user_message": row.get("user_message") or "",
        "assistant_message": row.get("assistant_message") or "",
        # jsonb auto-decoded by psycopg2 → list of {name, args, result, id} (or None)
        "tool_calls": row.get("tool_calls") or [],
    }
