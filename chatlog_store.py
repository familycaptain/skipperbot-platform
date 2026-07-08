"""
SkipperBot Chat Log Store
Persistent per-user chat logs with turn-based embeddings for semantic search.

Backed by Postgres + pgvector via data_layer.chatlogs.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

from app_platform.time import get_timezone
import data_layer.chatlogs as _dl_chat

load_dotenv()

from providers.model_config import provisioned_embedding_dim as _provisioned_embedding_dim
EMBEDDING_DIM = _provisioned_embedding_dim()  # provisioned at setup; default 1536 (MODEL_FLEXIBILITY #44)

def _get_embedding(text: str) -> list[float]:
    """Get an embedding vector via the vendor-neutral provider (MODEL_FLEXIBILITY #44/#71).

    Connector, embedding MODEL, and key ALL come from the "embedding" tier — no hardcoded model
    and no OPENAI_API_KEY assumption. Truncation stays caller-side so vectors are unchanged."""
    from providers.tier_resolver import resolve_embedding
    provider, model, api_key = resolve_embedding("embedding")
    vecs = provider.embed(texts=[text[:8000]], model=model, api_key=api_key)
    return vecs[0]


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def generate_turn_id() -> str:
    """Pre-generate a c-* ID for the current chat turn.
    Call this before processing so the agent can reference it in remember() calls.
    """
    return f"c-{uuid.uuid4().hex[:8]}"


def save_turn(
    user_id: str,
    user_message: str,
    assistant_message: str,
    turn_id: str = "",
    system_prompt: Optional[str] = None,
    selected_tools: Optional[list] = None,
    matched_guides: Optional[list] = None,
    tool_calls: Optional[list] = None,
    channel: str = "web",
) -> dict:
    """
    Save a conversation turn (user + assistant) with an embedding.

    Args:
        user_id: Who was chatting.
        user_message: What the user said.
        assistant_message: What the assistant replied.
        turn_id: Pre-generated c-* ID (from generate_turn_id). Auto-generated if empty.
        system_prompt: Full system prompt sent to the model on this turn (debug).
        selected_tools: List of tool function-name dicts that were exposed to the model.
        matched_guides: Per-category match audit — see tool_router.get_match_debug_for_message.
        channel: Originating surface (web/voice/discord/…). Defaults to 'web' so untagged
            callers (incl. bot notifications) stay visible in the web history reload (issue #23).

    Returns:
        The saved turn record (without embedding for readability).
    """
    # Embed the combined turn text for semantic search
    combined = f"User: {user_message}\nAssistant: {assistant_message}"
    embedding = _get_embedding(combined)

    record = _dl_chat.save_turn(
        user_id=user_id.lower().strip(),
        user_message=user_message,
        assistant_message=assistant_message,
        turn_id=turn_id if turn_id else None,
        embedding=embedding,
        system_prompt=system_prompt,
        selected_tools=selected_tools,
        matched_guides=matched_guides,
        tool_calls=tool_calls,
        channel=channel,
    )

    return {
        "id": record["id"],
        "user_id": record["user_id"],
        "timestamp": record.get("timestamp", ""),
    }


def save_notification(user_id: str, bot_message: str, context: str = ""):
    """Record a bot-initiated direct send in the consciousness log so the
    timeline sees it and follow-ups like "remind me again in an hour" have
    context.

    Phase 5b: this used to write a chat_turns row, which the consciousness
    timeline never read — direct-send callers (print/research/refine runners)
    were invisible to the one mind. Now it writes the log, the single record.

    Args:
        user_id: The recipient.
        bot_message: What the bot sent (e.g. "⏰ Reminder: ...").
        context: Optional context tag (e.g. "reminder_notification") — recorded
                 as the row's source_type and used for domain routing.
    """
    from app_platform.consciousness import shadow_log_event, domain_for_source_type
    src = (context or "notification").strip()
    shadow_log_event(
        kind="message", who_from="skipper", who_to=user_id.lower().strip(),
        domain=domain_for_source_type(src),
        content=bot_message,
        payload={"source_type": src},
        # Already delivered by the caller (Discord/Pushover/WebSocket): this is
        # a record, never a queue entry.
        pre_attended_by="direct-send",
    )


# ---------------------------------------------------------------------------
# Load and search
# ---------------------------------------------------------------------------

def load_recent_turns(user_id: str, max_turns: int = 20) -> list[dict]:
    """Load the most recent conversation turns for session bootstrapping.

    Returns a list of {role, content} dicts ready to inject into a session,
    ordered chronologically (oldest first).

    Args:
        user_id: Whose logs to load.
        max_turns: Maximum number of turns to load (each turn = 2 messages).

    Returns:
        List of message dicts: [{"role": "user", ...}, {"role": "assistant", ...}, ...]
    """
    turns = _dl_chat.get_recent_turns(user_id.lower().strip(), limit=max_turns)
    messages = []
    for turn in turns:
        messages.append({"role": "user", "content": turn["user_message"]})
        messages.append({"role": "assistant", "content": turn["assistant_message"]})
    return messages


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string in various formats."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=get_timezone())
        except ValueError:
            continue
    return None


def search_chatlogs(
    user_id: str,
    query: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 10,
    min_similarity: float = 0.25
) -> list[dict]:
    """
    Search a user's chat logs using pgvector semantic similarity.

    Args:
        user_id: Whose logs to search.
        query: Natural language search query.
        start_date: Optional start date filter (YYYY-MM-DD).
        end_date: Optional end date filter (YYYY-MM-DD).
        max_results: Maximum number of results.
        min_similarity: Minimum cosine similarity threshold.

    Returns:
        List of matching turns sorted by relevance, without embedding vectors.
    """
    query_embedding = _get_embedding(query)

    results = _dl_chat.search_turns(
        user_id=user_id.lower().strip(),
        query_embedding=query_embedding,
        max_results=max_results * 3,  # over-fetch for date filtering
    )

    # Apply date filters
    start_dt = _parse_date(start_date) if start_date else None
    end_dt = _parse_date(end_date) if end_date else None
    if end_dt:
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

    filtered = []
    for turn in results:
        score = turn.get("score", 0)
        if score < min_similarity:
            continue
        if start_dt or end_dt:
            turn_dt = _parse_date(turn.get("timestamp", "")[:10])
            if turn_dt is None:
                continue
            if start_dt and turn_dt < start_dt:
                continue
            if end_dt and turn_dt > end_dt:
                continue
        filtered.append({
            "id": turn["id"],
            "user_id": turn.get("user_id", ""),
            "timestamp": turn.get("timestamp", ""),
            "user_message": turn.get("user_message", ""),
            "assistant_message": turn.get("assistant_message", ""),
            "similarity": round(score, 4),
        })
        if len(filtered) >= max_results:
            break

    return filtered


def list_chatlog_users() -> list[dict]:
    """List all users who have chat logs, with turn counts and date ranges."""
    from data_layer.db import fetch_all
    rows = fetch_all("""
        SELECT user_id, COUNT(*) AS turn_count,
               MIN(created_at)::text AS first_date,
               MAX(created_at)::text AS last_date
        FROM chat_turns
        GROUP BY user_id
        ORDER BY user_id
    """)
    return [
        {
            "user_id": r["user_id"],
            "turn_count": r["turn_count"],
            "first_date": r["first_date"][:10] if r["first_date"] else None,
            "last_date": r["last_date"][:10] if r["last_date"] else None,
        }
        for r in rows
    ]


def format_chatlog_results(results: list[dict]) -> str:
    """Format search results for display."""
    if not results:
        return ""
    lines = [f"Found {len(results)} matching conversations:"]
    for r in results:
        ts = r["timestamp"][:16].replace("T", " ")
        sim_pct = f"{r['similarity'] * 100:.0f}%"
        lines.append(f"\n--- [{ts}] (relevance: {sim_pct}) ---")
        lines.append(f"You: {r['user_message'][:500]}")
        lines.append(f"Skipper: {r['assistant_message'][:500]}")
    return "\n".join(lines)
