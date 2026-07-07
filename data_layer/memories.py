"""Memories — Postgres CRUD + pgvector Search
=============================================
Drop-in replacement for memory_store.py's flat-file persistence.
Embeddings stored as vector(1536) columns; similarity search via pgvector.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import Json

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)

from providers.model_config import provisioned_embedding_dim as _provisioned_embedding_dim
EMBEDDING_DIM = _provisioned_embedding_dim()  # provisioned at setup; default 1536 (MODEL_FLEXIBILITY #44)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_memory(
    content: str,
    tags: list[str],
    about: Optional[str] = None,
    saved_by: str = "",
    related_entities: Optional[list[str]] = None,
    source_chat_id: Optional[str] = None,
    embedding: Optional[list[float]] = None,
) -> dict:
    """Save a new memory to Postgres.

    Args:
        content: The fact or detail to remember.
        tags: List of lowercase keyword tags.
        about: Primary subject (person name or entity ID).
        saved_by: Who saved this memory.
        related_entities: Additional entity IDs this memory relates to.
        source_chat_id: Chat turn ID that prompted this memory.
        embedding: Pre-computed embedding vector (1536 floats).

    Returns:
        The saved memory record dict.
    """
    record = {
        "id": f"m-{uuid.uuid4().hex[:8]}",
        "content": content,
        "tags": tags,
        "about": about.strip() if about else None,
        "saved_by": saved_by.lower().strip() if saved_by else "",
        "related_entities": related_entities or [],
        "source_chat_id": source_chat_id.strip() if source_chat_id else "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    emb_str = _vec_to_pgvector(embedding) if embedding else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO memories (id, content, tags, about, saved_by,
                                      related_entities, source_chat_id,
                                      embedding, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                record["id"], record["content"], record["tags"],
                record["about"] or "", record["saved_by"],
                record["related_entities"], record["source_chat_id"],
                emb_str, record["created_at"],
            ))
        conn.commit()

    return record


# ---------------------------------------------------------------------------
# Search (pgvector cosine similarity + tag/entity boosts)
# ---------------------------------------------------------------------------

def search_memories(
    query_tags: Optional[list[str]] = None,
    about: Optional[str] = None,
    query_text: Optional[str] = None,
    entity_id: Optional[str] = None,
    max_results: int = 10,
    query_embedding: Optional[list[float]] = None,
) -> list[dict]:
    """Hybrid semantic + tag search using pgvector.

    Uses cosine distance as the primary signal, with tag/about/entity
    boosts applied in Python (same scoring logic as the flat-file version).
    """
    if query_embedding:
        emb_str = _vec_to_pgvector(query_embedding)
        # fetch_all_vector bumps ivfflat.probes so the cosine search hits
        # every list — see data_layer/db.py for why this matters.
        from data_layer.db import fetch_all_vector
        rows = fetch_all_vector(f"""
            SELECT {_ROW_COLUMNS}, 1 - (embedding <=> %s::vector) AS cosine_sim
            FROM memories
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (emb_str, emb_str, max_results * 5))
    else:
        # No embedding — fall back to tag/entity filtering
        rows = fetch_all(
            f"SELECT {_ROW_COLUMNS}, 0.0 AS cosine_sim FROM memories "
            "ORDER BY created_at DESC LIMIT %s",
            (max_results * 5,),
        )

    normed_query_tags = query_tags or []
    normed_about = about.strip().lower() if about else None
    search_entity = entity_id.strip() if entity_id else None

    scored = []
    for row in rows:
        score = float(row.get("cosine_sim", 0)) * 10  # scale 0–1 → 0–10

        # Tag overlap boost
        if normed_query_tags:
            mem_tags = set(row.get("tags") or [])
            overlap = len(set(normed_query_tags) & mem_tags)
            score += overlap * 2

        # About field match
        mem_about = (row.get("about") or "").lower()
        if normed_about:
            if mem_about == normed_about:
                score += 3
            elif mem_about and mem_about != normed_about:
                score -= 1

        # Entity ID match
        if search_entity:
            mem_entities = set(row.get("related_entities") or [])
            if row.get("about"):
                mem_entities.add(row["about"])
            if search_entity in mem_entities:
                score += 5

        if score > 0.5:
            scored.append((score, _row_to_dict(row)))

    scored.sort(key=lambda x: (x[0], x[1].get("created_at", "")), reverse=True)

    # Dedup by about + tags
    seen_keys = set()
    results = []
    for _score, mem in scored:
        about_key = mem.get("about") or "_general"
        tag_key = tuple(sorted(mem.get("tags", [])))
        dedup_key = (about_key, tag_key)
        if dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            results.append(mem)
        if len(results) >= max_results:
            break

    return results


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_memory(memory_id: str) -> bool:
    """Delete a memory by ID."""
    count = execute("DELETE FROM memories WHERE id = %s", (memory_id,))
    return count > 0


# ---------------------------------------------------------------------------
# Bulk read (for backfill, stats, etc.)
# ---------------------------------------------------------------------------

# The columns _row_to_dict consumes. NEVER "SELECT *" on memories: * includes
# the embedding vector (~19KB of text per row), so an unbounded fetch
# materializes GIGABYTES client-side for data the caller throws away. This
# exact mistake OOM-killed the production agent roughly every other hour —
# the document domain calls load_all() at every cycle start, a multi-GB
# seconds-long transient that never showed in docker stats.
_ROW_COLUMNS = ("id, content, tags, about, saved_by, related_entities, "
                "source_chat_id, created_at")


def load_all() -> list[dict]:
    """Load all memories (no embeddings fetched OR returned).

    NOTE: unbounded — materializes the whole table. The documents domain no
    longer uses this (it calls load_after_cursor); retained for any other
    consumer. Prefer load_after_cursor for per-cycle work.
    """
    rows = fetch_all(f"SELECT {_ROW_COLUMNS} FROM memories ORDER BY created_at")
    return [_row_to_dict(r) for r in rows]


def load_after_cursor(cursor_id: str, limit: int) -> list[dict]:
    """Return up to `limit` memories after `cursor_id`, ascending (created_at, id).

    Bounded, index-backed (idx_memories_created_at_id) replacement for load_all()
    in the documents domain's hourly observe cycle: it fetches only the next
    window of memories instead of materializing the whole table each cycle.

      * cursor_id empty (first run)      -> the OLDEST `limit` rows, ascending;
                                            the backlog drains across cycles.
      * cursor_id present and FOUND      -> rows strictly after the cursor by the
                                            composite (created_at, id) keyset,
                                            ascending — same-instant rows ordered
                                            by id, so none is skipped or repeated.
      * cursor_id present but NOT found  -> the MOST-RECENT `limit` rows, ascending
        (the cursor memory was deleted)    (mirrors the old all_memories[-N:]
                                            fallback: jump to the recent window and
                                            do NOT revisit the older backlog).

    Never selects the embedding vector (_ROW_COLUMNS only) — the OOM guard.
    `cursor_id` and `limit` are always psycopg2 bind params, never interpolated.
    """
    if not cursor_id:
        # First run — oldest window; successive cycles walk forward.
        rows = fetch_all(
            f"SELECT {_ROW_COLUMNS} FROM memories ORDER BY created_at, id LIMIT %s",
            (limit,),
        )
        return [_row_to_dict(r) for r in rows]

    cursor_row = fetch_one(
        "SELECT created_at, id FROM memories WHERE id = %s", (cursor_id,)
    )
    if cursor_row is None:
        # Cursor memory deleted — fall back to the most-recent window, ascending.
        rows = fetch_all(
            f"SELECT {_ROW_COLUMNS} FROM memories "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (limit,),
        )
        return [_row_to_dict(r) for r in reversed(rows)]

    # Keyset: rows strictly after the cursor's (created_at, id), ascending, bounded.
    rows = fetch_all(
        f"SELECT {_ROW_COLUMNS} FROM memories "
        "WHERE (created_at, id) > (%s, %s) "
        "ORDER BY created_at, id LIMIT %s",
        (cursor_row["created_at"], cursor_row["id"], limit),
    )
    return [_row_to_dict(r) for r in rows]


def count_after_cursor(cursor_id: str) -> Optional[int]:
    """Count memories strictly after `cursor_id` by the (created_at, id) keyset.

    Index-backed companion to load_after_cursor for catchup-mode detection —
    lets the documents domain compute TRUE remaining-unprocessed without a
    whole-table load (never len(batch), which the bounded fetch would cap).

      * cursor_id empty          -> total table count (first run: all unprocessed).
      * cursor_id present, FOUND  -> COUNT of rows strictly after the cursor.
      * cursor_id present, NOT found -> None, so the caller falls back to its
                                        recent-window size (parity: the deleted
                                        cursor abandons the older backlog).
    """
    if not cursor_id:
        return count_memories()
    cursor_row = fetch_one(
        "SELECT created_at, id FROM memories WHERE id = %s", (cursor_id,)
    )
    if cursor_row is None:
        return None
    row = fetch_one(
        "SELECT COUNT(*) AS cnt FROM memories WHERE (created_at, id) > (%s, %s)",
        (cursor_row["created_at"], cursor_row["id"]),
    )
    return row["cnt"] if row else 0


def list_recent_memories(user_id: str = "", limit: int = 50) -> list[dict]:
    """Return the most recent memories, newest first.

    Used by the voice prompt builder to inject recent context at session
    start (the OpenAI Realtime session prompt is set once before the user
    speaks, so we can't do per-utterance semantic recall like the web UI;
    upfront recency-ordered memory injection is the next-best thing).

    `user_id` (lowercase) restricts to memories about that person OR memories
    with no `about` (shared/global facts). Pass "" to skip the filter.
    """
    user = (user_id or "").strip().lower()
    if user:
        rows = fetch_all(
            f"SELECT {_ROW_COLUMNS} FROM memories "
            "WHERE about = %s OR about IS NULL OR about = '' "
            "ORDER BY created_at DESC LIMIT %s",
            (user, limit),
        )
    else:
        rows = fetch_all(
            f"SELECT {_ROW_COLUMNS} FROM memories ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
    return [_row_to_dict(r) for r in rows]


def count_memories() -> int:
    """Return total memory count."""
    row = fetch_one("SELECT COUNT(*) AS cnt FROM memories")
    return row["cnt"] if row else 0


def count_embeddings() -> int:
    """Return count of memories that have embeddings."""
    row = fetch_one("SELECT COUNT(*) AS cnt FROM memories WHERE embedding IS NOT NULL")
    return row["cnt"] if row else 0


def update_embedding(memory_id: str, embedding: list[float]):
    """Set the embedding for a specific memory (used by backfill)."""
    emb_str = _vec_to_pgvector(embedding)
    execute("UPDATE memories SET embedding = %s WHERE id = %s", (emb_str, memory_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec_to_pgvector(embedding: list[float]) -> str:
    """Convert a float list to pgvector string format."""
    return "[" + ",".join(f"{v:.8g}" for v in embedding) + "]"


def _row_to_dict(row: dict) -> dict:
    """Convert a memories table row to the dict shape memory_store expects."""
    return {
        "id": row["id"],
        "content": row["content"],
        "tags": row.get("tags") or [],
        "about": row.get("about") or None,
        "saved_by": row.get("saved_by") or "",
        "related_entities": row.get("related_entities") or [],
        "source_chat_id": row.get("source_chat_id") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
