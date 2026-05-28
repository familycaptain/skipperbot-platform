"""Knowledge Base — Postgres CRUD + pgvector Search
===================================================
Drop-in replacement for knowledge_store.py's flat-file persistence.
Sources, chunks (with embeddings), and crawls.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def save_source(source: dict) -> dict:
    """Insert or update a knowledge source."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_sources (id, name, url, chunk_count, crawl_id, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, url = EXCLUDED.url,
                    chunk_count = EXCLUDED.chunk_count, crawl_id = EXCLUDED.crawl_id
            """, (
                source["id"], source["name"], source.get("url", ""),
                source.get("chunk_count", 0), source.get("crawl_id", ""),
                source.get("ingested_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()
    return source


def get_source(source_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM knowledge_sources WHERE id = %s", (source_id,))
    return _source_row(row) if row else None


def get_all_sources() -> list[dict]:
    return [_source_row(r) for r in fetch_all("SELECT * FROM knowledge_sources ORDER BY ingested_at")]


def delete_source(source_id: str) -> bool:
    return execute("DELETE FROM knowledge_sources WHERE id = %s", (source_id,)) > 0


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------

def save_chunk(chunk: dict, embedding: Optional[list[float]] = None) -> dict:
    """Insert or update a knowledge chunk with optional embedding."""
    emb_str = _vec(embedding) if embedding else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_chunks (id, source_id, chunk_index, text, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    text = EXCLUDED.text, embedding = COALESCE(EXCLUDED.embedding, knowledge_chunks.embedding)
            """, (
                chunk["id"], chunk["source_id"], chunk.get("chunk_index", 0),
                chunk["text"], emb_str,
            ))
        conn.commit()
    return chunk


def search_chunks(query_embedding: list[float], max_results: int = 10) -> list[dict]:
    """Semantic search over knowledge chunks using pgvector cosine distance."""
    from data_layer.db import fetch_all_vector  # raises ivfflat.probes for full recall
    emb_str = _vec(query_embedding)
    rows = fetch_all_vector("""
        SELECT *, 1 - (embedding <=> %s::vector) AS score
        FROM knowledge_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (emb_str, emb_str, max_results))
    return [_chunk_row(r) | {"score": float(r["score"])} for r in rows]


def get_chunks_for_source(source_id: str) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM knowledge_chunks WHERE source_id = %s ORDER BY chunk_index",
        (source_id,),
    )
    return [_chunk_row(r) for r in rows]


def delete_chunks_for_source(source_id: str) -> int:
    return execute("DELETE FROM knowledge_chunks WHERE source_id = %s", (source_id,))


# ---------------------------------------------------------------------------
# Crawls
# ---------------------------------------------------------------------------

def save_crawl(crawl: dict) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_crawls (id, name, root_url, source_ids,
                                              pages_crawled, pages_failed, total_chunks, crawled_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    source_ids = EXCLUDED.source_ids,
                    pages_crawled = EXCLUDED.pages_crawled,
                    pages_failed = EXCLUDED.pages_failed,
                    total_chunks = EXCLUDED.total_chunks
            """, (
                crawl["id"], crawl["name"], crawl.get("root_url", ""),
                crawl.get("source_ids", []),
                crawl.get("pages_crawled", 0), crawl.get("pages_failed", 0),
                crawl.get("total_chunks", 0),
                crawl.get("crawled_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()
    return crawl


def get_all_crawls() -> list[dict]:
    return [_crawl_row(r) for r in fetch_all("SELECT * FROM knowledge_crawls ORDER BY crawled_at")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec(embedding: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in embedding) + "]"


def _source_row(row: dict) -> dict:
    return {
        "id": row["id"], "name": row["name"], "url": row.get("url", ""),
        "chunk_count": row.get("chunk_count", 0), "crawl_id": row.get("crawl_id", ""),
        "ingested_at": row["ingested_at"].isoformat() if row.get("ingested_at") else "",
    }


def _chunk_row(row: dict) -> dict:
    return {
        "id": row["id"], "source_id": row["source_id"],
        "chunk_index": row.get("chunk_index", 0), "text": row["text"],
    }


def _crawl_row(row: dict) -> dict:
    return {
        "id": row["id"], "name": row["name"], "root_url": row.get("root_url", ""),
        "source_ids": row.get("source_ids", []),
        "pages_crawled": row.get("pages_crawled", 0),
        "pages_failed": row.get("pages_failed", 0),
        "total_chunks": row.get("total_chunks", 0),
        "crawled_at": row["crawled_at"].isoformat() if row.get("crawled_at") else "",
    }
