"""
SkipperBot Chat Log Store — Phase 5b: the consciousness log is the record.

What remains here: turn-id generation, the direct-send notification recorder
(writes the log), and log-backed user listing. The chat_turns table is frozen
(read-only, zero-loss); nothing writes it anymore.
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

def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string in various formats."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=get_timezone())
        except ValueError:
            continue
    return None


def list_chatlog_users() -> list[dict]:
    """List everyone with conversation history, from the consciousness log
    (Phase 5b — includes the backfilled legacy turns)."""
    from data_layer.db import fetch_all
    rows = fetch_all("""
        SELECT CASE WHEN who_from = 'skipper' THEN who_to ELSE who_from END AS user_id,
               COUNT(*) AS turn_count,
               MIN(created_at)::text AS first_date,
               MAX(created_at)::text AS last_date
        FROM consciousness_log
        WHERE kind = 'message'
          AND (who_from <> 'skipper' OR who_to IS NOT NULL)
        GROUP BY 1 HAVING CASE WHEN who_from = 'skipper' THEN who_to ELSE who_from END IS NOT NULL
        ORDER BY 1
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


