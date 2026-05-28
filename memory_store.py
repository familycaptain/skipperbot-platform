"""SkipperBot Memory Store
Persistent shared memory backed by Postgres + pgvector.
Supports save, search, delete, and hybrid semantic + tag retrieval.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

import data_layer.memories as _dl_mem

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _get_embedding(text: str) -> list[float]:
    """Get an embedding vector from OpenAI."""
    response = _openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000]
    )
    return response.data[0].embedding

def get_embedding(text: str) -> list[float]:
    """Public wrapper — embed text for reuse across modules."""
    return _get_embedding(text)



def normalize_tag(tag: str) -> str:
    """Normalize a tag to lowercase singular form."""
    tag = tag.lower().strip()
    if not tag:
        return tag
    # Common plural → singular reductions
    if tag.endswith("ies") and len(tag) > 3:
        return tag[:-3] + "y"     # "memories" → "memory"
    if tag.endswith("ses") or tag.endswith("xes") or tag.endswith("zes"):
        return tag[:-2]           # "boxes" → "box"
    if tag.endswith("shes") or tag.endswith("ches"):
        return tag[:-2]           # "watches" → "watch"
    if tag.endswith("s") and not tag.endswith("ss") and len(tag) > 2:
        return tag[:-1]           # "colors" → "color"
    return tag


def _normalize_tags(tags: list[str]) -> list[str]:
    """Normalize and deduplicate a list of tags."""
    seen = set()
    result = []
    for tag in tags:
        normed = normalize_tag(tag)
        if normed and normed not in seen:
            seen.add(normed)
            result.append(normed)
    return result




def save_memory(
    content: str,
    tags: list[str],
    about: Optional[str] = None,
    saved_by: str = "",
    related_entities: Optional[list[str]] = None,
    source_chat_id: Optional[str] = None,
) -> dict:
    """
    Save a new memory to Postgres with embedding.

    Args:
        content: The fact or detail to remember.
        tags: List of lowercase keyword tags.
        about: Primary subject — a person name ("alice") or entity ID ("p-1234").
        saved_by: Who saved this memory (user_id).
        related_entities: Additional entity IDs this memory relates to
                          (e.g. ["g-abc123", "p-def456"]).
        source_chat_id: Optional c-* ID of the chat turn that prompted this memory.

    Returns:
        The saved memory record.
    """
    about_val = about.strip() if about else None
    if about_val and not _is_entity_id(about_val):
        about_val = about_val.lower()

    # Embed the content for semantic search
    try:
        embedding = _get_embedding(content)
    except Exception as e:
        logger.warning("MEMORY: Failed to embed memory, saving without embedding: %s", e)
        embedding = None

    return _dl_mem.save_memory(
        content=content,
        tags=_normalize_tags(tags),
        about=about_val,
        saved_by=saved_by,
        related_entities=related_entities,
        source_chat_id=source_chat_id,
        embedding=embedding,
    )


def _is_entity_id(val: str) -> bool:
    """Check if a string looks like an entity ID (e.g. g-abc123, p-def456)."""
    prefixes = ("g-", "p-", "t-", "r-", "j-", "n-", "l-", "li-", "a-", "k-", "m-")
    return any(val.startswith(p) for p in prefixes)


def search_memories(
    query_tags: Optional[list[str]] = None,
    about: Optional[str] = None,
    query_text: Optional[str] = None,
    entity_id: Optional[str] = None,
    max_results: int = 10,
    query_embedding: Optional[list[float]] = None,
) -> list[dict]:
    """
    Search memories using hybrid semantic + tag/entity scoring.
    pgvector cosine distance is the primary signal; tag overlap,
    about-field match, and entity ID match act as additive boosts.

    Args:
        query_tags: Tags to match against.
        about: Filter to memories about a specific person or entity ID.
        query_text: Free text — will be embedded for semantic search.
        entity_id: Filter to memories referencing this entity (checks both
                   'about' and 'related_entities' fields).
        max_results: Maximum number of results to return.

    Returns:
        List of matching memory records, most relevant first.
    """
    normed_query_tags = _normalize_tags(query_tags) if query_tags else None

    # Embed the query text for semantic search (skip if caller provided one)
    if query_embedding is None and query_text:
        try:
            query_embedding = _get_embedding(query_text)
        except Exception as e:
            logger.warning("MEMORY: Failed to embed query, falling back to tag search: %s", e)

    return _dl_mem.search_memories(
        query_tags=normed_query_tags,
        about=about,
        query_text=query_text,
        entity_id=entity_id,
        max_results=max_results,
        query_embedding=query_embedding,
    )


def delete_memory(memory_id: str) -> bool:
    """
    Delete a memory by its ID.

    Args:
        memory_id: The ID of the memory to delete.

    Returns:
        True if deleted, False if not found.
    """
    return _dl_mem.delete_memory(memory_id)


_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "like",
    "through", "after", "over", "between", "out", "up", "down", "off",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "where", "how",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
    "tell", "know", "think", "say", "get", "make", "go", "see",
    "come", "take", "want", "look", "use", "find", "give", "let",
    "hey", "hi", "hello", "please", "thanks", "thank", "okay", "ok",
    "yeah", "yes", "no", "sure", "right", "well", "now", "then",
    "here", "there", "also", "still", "already", "much", "many",
    "really", "actually", "probably", "maybe", "always", "never",
    "sometimes", "often", "again", "why", "don", "doesn", "didn",
    "won", "wouldn", "shouldn", "couldn", "isn", "aren", "wasn",
    "weren", "hasn", "haven", "hadn", "whats", "what's", "hows",
    "how's", "whos", "who's", "wheres", "where's", "favorite",
}


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text, filtering stop words."""
    words = text.lower().split()
    clean = []
    for w in words:
        cleaned = "".join(c for c in w if c.isalnum())
        if cleaned and cleaned not in _STOP_WORDS and len(cleaned) > 1:
            clean.append(cleaned)
    return clean


def get_relevant_memories(
    user_message: str,
    user_id: str = "",
    max_results: int = 5,
    query_embedding: Optional[list[float]] = None,
) -> list[dict]:
    """
    Retrieve memories relevant to a user message for injection into chat context.
    Uses semantic embedding search with keyword tag boost.

    Args:
        user_message: The user's chat message.
        user_id: The current user's ID.
        max_results: Max memories to return.

    Returns:
        List of relevant memory records.
    """
    clean_words = _extract_keywords(user_message)
    query_tags = _normalize_tags(clean_words) if clean_words else []

    # Check if any extracted word looks like a person name (matches "about" field)
    about_person = None
    if query_tags:
        from data_layer.db import fetch_all
        rows = fetch_all("SELECT DISTINCT about FROM memories WHERE about IS NOT NULL AND about != ''")
        known_people = {r["about"] for r in rows}
        for tag in query_tags:
            if tag in known_people:
                about_person = tag
                break

    return search_memories(
        query_tags=query_tags,
        about=about_person,
        query_text=user_message,
        max_results=max_results,
        query_embedding=query_embedding,
    )


def backfill_embeddings() -> dict:
    """
    Backfill embeddings for memories that are missing them in Postgres.

    Returns:
        dict with 'total', 'existing', 'backfilled', 'failed' counts.
    """
    total = _dl_mem.count_memories()
    existing = _dl_mem.count_embeddings()

    if existing >= total:
        return {"total": total, "existing": existing, "backfilled": 0, "failed": 0}

    logger.info("MEMORY: Backfilling embeddings for %d memories (have %d)", total, existing)

    # Load memories without embeddings
    from data_layer.db import fetch_all
    missing = fetch_all(
        "SELECT id, content FROM memories WHERE embedding IS NULL ORDER BY created_at"
    )

    backfilled = 0
    failed = 0
    for row in missing:
        try:
            embedding = _get_embedding(row["content"])
            _dl_mem.update_embedding(row["id"], embedding)
            backfilled += 1
        except Exception as e:
            logger.warning("MEMORY: Failed to embed %s: %s", row["id"], e)
            failed += 1

    logger.info("MEMORY: Backfilled %d embeddings (%d failed)", backfilled, failed)
    return {"total": total, "existing": existing, "backfilled": backfilled, "failed": failed}


def format_memories_for_context(memories: list[dict]) -> str:
    """
    Format a list of memories into a string for injection into chat context.

    Args:
        memories: List of memory records.

    Returns:
        Formatted string, or empty string if no memories.
    """
    if not memories:
        return ""
    lines = ["Relevant memories:"]
    for mem in memories:
        about = f" (about {mem['about']})" if mem.get("about") else ""
        refs = mem.get("related_entities", [])
        ref_str = f" [refs: {', '.join(refs)}]" if refs else ""
        date = mem.get("created_at", "")[:10]
        date_str = f" [recorded: {date}]" if date else ""
        lines.append(f"- {mem['content']}{about}{ref_str}{date_str}")
    return "\n".join(lines)
