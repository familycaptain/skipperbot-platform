"""Documents — data layer (SQL CRUD + search).

Owns reads + writes for the ``app_documents.documents`` table,
including keyword search, semantic search (pgvector cosine), and the
hybrid combiner used by both the chat tools and the document thinking
domain.

Ported from ``data_layer/documents.py`` for sub-chunk 10c-part-1.
Functionally identical; only difference is routing all queries through
the ``*_in_schema`` helpers from ``app_platform.db`` so the documents
app's table lands in (and reads from) the ``app_documents`` schema.

A new ``fetch_all_vector_in_schema`` helper was added to
``app_platform.db`` for this app's semantic-search query (which needs
``SET LOCAL ivfflat.probes`` to get exact top-k from the ivfflat
index).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_all_vector_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)
from data_layer.links import ensure_edge  # platform infra — links live in public.*


logger = logging.getLogger(__name__)

SCHEMA = "app_documents"


# ---------------------------------------------------------------------------
# Memory-digestion hint
# ---------------------------------------------------------------------------

_DOCUMENT_HINT = (
    "Focus on: the document's title, the topics it covers (tags), and the "
    "first line or two of content. Documents are how chat answers 'we wrote "
    "something about that, didn't we?'."
)


# ---------------------------------------------------------------------------
# Backfill registry
# ---------------------------------------------------------------------------

BACKFILL_ENTITIES = [
    {
        "entity_type": "document",
        "list_fn": lambda: get_all_documents(),
        "context_hint": _DOCUMENT_HINT,
    },
]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_document(doc: dict):
    """Insert or update a document (metadata + content)."""
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (id, title, content, tags, word_count,
                                       related_entity_id, parent_doc_id, version,
                                       created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    tags = EXCLUDED.tags,
                    word_count = EXCLUDED.word_count,
                    related_entity_id = EXCLUDED.related_entity_id,
                    parent_doc_id = EXCLUDED.parent_doc_id,
                    version = EXCLUDED.version,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    doc["id"], doc.get("title", ""), doc.get("content", ""),
                    doc.get("tags", []), doc.get("word_count", 0),
                    doc.get("related_entity_id", ""), doc.get("parent_doc_id", ""),
                    doc.get("version", 1), doc.get("created_by", ""),
                    doc.get("created_at", datetime.now(timezone.utc).isoformat()),
                    doc.get("updated_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
        conn.commit()
    if doc.get("related_entity_id"):
        ensure_edge(doc["id"], doc["related_entity_id"], "related_to", "related_to")
    if doc.get("parent_doc_id"):
        ensure_edge(doc["id"], doc["parent_doc_id"], "child_of", "parent_of")


def get_document(doc_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM documents WHERE id = %s", (doc_id,))
    return _row(row) if row else None


def get_all_documents() -> list[dict]:
    return [
        _row(r)
        for r in fetch_all_in_schema(
            SCHEMA, "SELECT * FROM documents ORDER BY created_at DESC",
        )
    ]


def get_document_content(doc_id: str) -> str:
    """Get just the content of a document."""
    row = fetch_one_in_schema(SCHEMA, "SELECT content FROM documents WHERE id = %s", (doc_id,))
    return row["content"] if row else ""


def update_content(doc_id: str, content: str, word_count: int | None = None):
    """Update document content and optionally word count."""
    if word_count is not None:
        execute_in_schema(
            SCHEMA,
            "UPDATE documents SET content = %s, word_count = %s, updated_at = %s WHERE id = %s",
            (content, word_count, datetime.now(timezone.utc).isoformat(), doc_id),
        )
    else:
        execute_in_schema(
            SCHEMA,
            "UPDATE documents SET content = %s, updated_at = %s WHERE id = %s",
            (content, datetime.now(timezone.utc).isoformat(), doc_id),
        )


def delete_document(doc_id: str) -> bool:
    return execute_in_schema(SCHEMA, "DELETE FROM documents WHERE id = %s", (doc_id,)) > 0


def search_documents(query: str) -> list[dict]:
    """Simple text search across title and content."""
    pattern = f"%{query}%"
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM documents WHERE title ILIKE %s OR content ILIKE %s ORDER BY created_at DESC",
        (pattern, pattern),
    )
    return [_row(r) for r in rows]


def _hybrid_weight() -> float:
    """Semantic share for hybrid search (Settings → Documents: search_hybrid_weight).
    1.0 = pure semantic, 0.0 = pure keyword. Clamped to [0, 1]."""
    try:
        from app_platform import settings as _settings
        w = float(_settings.get("search_hybrid_weight", scope="app:documents", default="0.5") or 0.5)
    except (TypeError, ValueError):
        w = 0.5
    return max(0.0, min(1.0, w))


def _kw_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens (len >= 2) for keyword overlap scoring."""
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 2}


def search_documents_hybrid(
    query_text: str | None = None,
    query_embedding: list[float] | None = None,
    query_tags: list[str] | None = None,
    tag_filter: str = "",
    max_results: int = 15,
    weight: float | None = None,
) -> list[dict]:
    """Hybrid document search blending semantic + keyword by ``weight``.

    weight (Settings → Documents: search_hybrid_weight): 1.0 = pure semantic
    (pgvector cosine), 0.0 = pure keyword (token overlap on title+tags+content).
    query_tags add a small overlap boost; tag_filter restricts to docs carrying
    that tag. Returns metadata (no content) with a ``match_score``, ranked.
    """
    if weight is None:
        weight = _hybrid_weight()

    candidates: dict[str, dict] = {}
    sem: dict[str, float] = {}   # doc_id -> cosine 0..1
    kw: dict[str, float] = {}    # doc_id -> keyword coverage 0..1

    # --- semantic arm ---
    if weight > 0 and query_embedding:
        emb_str = _vec_to_pgvector(query_embedding)
        rows = fetch_all_vector_in_schema(
            SCHEMA,
            """
            SELECT *, 1 - (embedding <=> %s::vector) AS cosine_sim
            FROM documents
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (emb_str, emb_str, max_results * 3),
        )
        for r in rows:
            candidates[r["id"]] = r
            sem[r["id"]] = max(0.0, float(r.get("cosine_sim", 0.0)))

    # --- keyword arm ---
    if weight < 1 and query_text and query_text.strip():
        q_tokens = _kw_tokens(query_text)
        if q_tokens:
            for r in search_documents(query_text):
                text = " ".join([
                    r.get("title", ""),
                    " ".join(r.get("tags") or []),
                    r.get("content", ""),
                ])
                matched = len(q_tokens & _kw_tokens(text))
                if matched:
                    candidates[r["id"]] = r
                    kw[r["id"]] = matched / len(q_tokens)

    # No usable signal → recent docs (preserves the old fallback behavior).
    if not candidates:
        rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM documents ORDER BY updated_at DESC LIMIT %s",
            (max_results * 3,),
        )
        for r in rows:
            candidates[r["id"]] = r

    normed_tags = [t.lower().strip() for t in (query_tags or []) if t.strip()]
    tag_f = (tag_filter or "").lower().strip()

    scored = []
    for did, row in candidates.items():
        doc_tags = set(t.lower() for t in (row.get("tags") or []))
        if tag_f and tag_f not in doc_tags:
            continue
        score = weight * sem.get(did, 0.0) + (1 - weight) * kw.get(did, 0.0)
        if normed_tags:
            score += 0.1 * len(set(normed_tags) & doc_tags)  # small tag boost
        meta = _row_no_content(row)
        meta["match_score"] = round(score, 6)
        scored.append((score, meta))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _score, doc in scored[:max_results]]


def update_embedding(doc_id: str, embedding: list[float]):
    """Update the embedding vector for a document."""
    emb_str = _vec_to_pgvector(embedding)
    execute_in_schema(
        SCHEMA,
        "UPDATE documents SET embedding = %s::vector WHERE id = %s",
        (emb_str, doc_id),
    )


def _vec_to_pgvector(vec: list[float]) -> str:
    """Convert a Python list of floats to pgvector literal."""
    return "[" + ",".join(str(f) for f in vec) + "]"


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "content": row.get("content") or "",
        "tags": row.get("tags") or [],
        "word_count": row.get("word_count", 0),
        "related_entity_id": row.get("related_entity_id") or "",
        "parent_doc_id": row.get("parent_doc_id") or "",
        "version": row.get("version", 1),
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _row_no_content(row: dict) -> dict:
    """Row dict without content — for search results and metadata listings."""
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "tags": row.get("tags") or [],
        "word_count": row.get("word_count", 0),
        "related_entity_id": row.get("related_entity_id") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }
