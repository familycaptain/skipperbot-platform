"""SkipperBot Knowledge Store
Persistent knowledge base backed by Postgres + pgvector via data_layer.knowledge.
Supports ingestion from URLs, chunking, semantic search, and source management.
"""

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

from auto_memory import log_entity_change
import data_layer.knowledge as _dl_know

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
from providers.model_config import provisioned_embedding_dim as _provisioned_embedding_dim
EMBEDDING_DIM = _provisioned_embedding_dim()  # provisioned at setup; default 1536 (MODEL_FLEXIBILITY #44)
CHUNK_SIZE = 500        # target tokens per chunk (approx 4 chars per token)
CHUNK_OVERLAP = 50      # overlap tokens between chunks
CHARS_PER_TOKEN = 4     # rough approximation

def _get_embedding(text: str) -> list[float]:
    """Get an embedding vector via the vendor-neutral provider (issue #39).

    No truncation here (knowledge chunks are pre-sized via CHARS_PER_TOKEN) — the
    provider never truncates or rewrites the model, so vectors are unchanged."""
    from providers.registry import get_embedding_provider
    vecs = get_embedding_provider().embed(texts=[text], model=EMBEDDING_MODEL)
    return vecs[0]


# ---------------------------------------------------------------------------
# Text extraction and chunking
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> dict:
    """Fetch a URL and extract clean text content.

    Returns:
        dict with 'title', 'text', 'url', and 'links' (list of URLs found on page).
    """
    headers = {
        "User-Agent": "SkipperBot/1.0 (Knowledge Ingestion)"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script, style, nav, footer elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # Extract text
    text = soup.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Extract links on same domain for potential crawling
    from urllib.parse import urljoin, urlparse
    base_domain = urlparse(url).netloc
    links = []
    for a_tag in soup.find_all("a", href=True):
        href = urljoin(url, a_tag["href"])
        if urlparse(href).netloc == base_domain and href != url:
            links.append(href)
    # Deduplicate, preserve order
    seen = set()
    unique_links = []
    for link in links:
        clean = link.split("#")[0].rstrip("/")
        if clean not in seen and clean != url.rstrip("/"):
            seen.add(clean)
            unique_links.append(clean)

    return {
        "title": title,
        "text": text,
        "url": url,
        "links": unique_links
    }


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks of approximately chunk_size tokens.

    Tries to split on paragraph/sentence boundaries when possible.
    """
    char_size = chunk_size * CHARS_PER_TOKEN
    char_overlap = overlap * CHARS_PER_TOKEN

    if len(text) <= char_size:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + char_size

        if end < len(text):
            # Try to break at paragraph boundary
            para_break = text.rfind("\n\n", start + char_size // 2, end)
            if para_break > start:
                end = para_break
            else:
                # Try sentence boundary
                sent_break = text.rfind(". ", start + char_size // 2, end)
                if sent_break > start:
                    end = sent_break + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - char_overlap
        if start >= len(text):
            break

    return chunks




# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_url(url: str, source_name: Optional[str] = None, crawl_id: str = "") -> dict:
    """Fetch a URL, chunk its content, embed chunks, and store everything.

    Args:
        url: The URL to fetch and ingest.
        source_name: Optional human-readable name for this source.
        crawl_id: Optional crawl manifest ID to group this source under.

    Returns:
        dict with source_id, title, chunk_count, and links found on the page.
    """
    page = fetch_page(url)

    if not page["text"].strip():
        return {"error": f"No text content found at {url}"}

    # Remove existing source for this URL if re-ingesting
    existing_sources = _dl_know.get_all_sources()
    for src in existing_sources:
        if src.get("url", "").rstrip("/") == url.rstrip("/"):
            remove_source(src["id"])
            break

    # Create source record
    source_id = f"k-{uuid.uuid4().hex[:8]}"
    source = {
        "id": source_id,
        "name": source_name or page["title"],
        "url": url,
        "chunk_count": 0,
        "crawl_id": crawl_id,
        "ingested_at": datetime.now(timezone.utc).isoformat()
    }

    # Chunk the text
    text_chunks = chunk_text(page["text"])
    if not text_chunks:
        return {"error": f"No usable text chunks from {url}"}

    # Embed all chunks and persist to Postgres
    chunk_records = []
    for i, text in enumerate(text_chunks):
        embedding = _get_embedding(text)
        chunk = {
            "id": str(uuid.uuid4())[:8],
            "source_id": source_id,
            "chunk_index": i,
            "text": text,
        }
        _dl_know.save_chunk(chunk, embedding=embedding)
        chunk_records.append(chunk)

    # Save source
    source["chunk_count"] = len(chunk_records)
    _dl_know.save_source(source)

    log_entity_change("ingested", source_id, "knowledge",
                      f"{source['name']} ({url}) — {len(chunk_records)} chunks")

    return {
        "source_id": source_id,
        "title": source["name"],
        "url": url,
        "chunk_count": len(chunk_records),
        "links": page["links"][:20]  # Cap at 20 links to avoid noise
    }


def search_knowledge(query: str, max_results: int = 5, min_similarity: float = 0.3, query_embedding: list[float] | None = None) -> list[dict]:
    """Search the knowledge base using pgvector semantic similarity.

    Args:
        query: The search query.
        max_results: Maximum number of chunks to return.
        min_similarity: Minimum cosine similarity threshold.

    Returns:
        List of matching chunks with similarity scores, sorted best first.
    """
    if query_embedding is None:
        query_embedding = _get_embedding(query)

    results = _dl_know.search_chunks(query_embedding, max_results=max_results * 2)

    scored = []
    for chunk in results:
        sim = chunk.get("score", 0)
        if sim >= min_similarity:
            scored.append({
                "chunk_id": chunk["id"],
                "source_id": chunk["source_id"],
                "text": chunk["text"],
                "similarity": round(sim, 4)
            })
        if len(scored) >= max_results:
            break

    return scored


def list_sources() -> list[dict]:
    """List all ingested sources (without embedding data)."""
    return _dl_know.get_all_sources()


def remove_source(source_id: str) -> bool:
    """Remove a source and all its chunks.

    Args:
        source_id: The ID of the source to remove.

    Returns:
        True if removed, False if not found.
    """
    source = _dl_know.get_source(source_id)
    if not source:
        return False

    _dl_know.delete_chunks_for_source(source_id)
    _dl_know.delete_source(source_id)

    log_entity_change("removed", source_id, "knowledge",
                      f"Source {source_id} removed")
    return True


def get_relevant_knowledge(user_message: str, max_results: int = 3, query_embedding: list[float] | None = None) -> list[dict]:
    """Retrieve knowledge chunks relevant to a user message.
    Designed to be called from chat.py for automatic context injection.

    Args:
        user_message: The user's chat message.
        max_results: Max chunks to return.

    Returns:
        List of relevant chunk dicts with text and similarity.
    """
    return search_knowledge(user_message, max_results=max_results, query_embedding=query_embedding)


def format_knowledge_for_context(chunks: list[dict]) -> str:
    """Format knowledge chunks for injection into chat context.

    Args:
        chunks: List of chunk dicts from search_knowledge.

    Returns:
        Formatted string, or empty string if no chunks.
    """
    if not chunks:
        return ""

    # Look up source names
    sources = {s["id"]: s for s in _dl_know.get_all_sources()}

    lines = ["Relevant knowledge:"]
    for chunk in chunks:
        source = sources.get(chunk["source_id"], {})
        source_name = source.get("name", "Unknown")
        lines.append(f"[From: {source_name}]")
        lines.append(chunk["text"][:1000])  # Cap chunk display
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Crawl manifests
# ---------------------------------------------------------------------------

def create_crawl_manifest(
    root_url: str,
    name: str,
    source_ids: list[str],
    pages_crawled: int,
    pages_failed: int,
    total_chunks: int,
) -> dict:
    """Create or update a crawl manifest grouping sources from a single crawl.

    If a manifest with the same root_url already exists, it is updated in place
    (same kc-* ID) so that artifacts and links referencing it stay valid.

    Returns:
        The manifest record.
    """
    crawls = _dl_know.get_all_crawls()
    existing = None
    for c in crawls:
        if c.get("root_url", "").rstrip("/") == root_url.rstrip("/"):
            existing = c
            break

    now = datetime.now(timezone.utc).isoformat()

    if existing:
        existing["name"] = name
        existing["source_ids"] = source_ids
        existing["pages_crawled"] = pages_crawled
        existing["pages_failed"] = pages_failed
        existing["total_chunks"] = total_chunks
        existing["crawled_at"] = now
        _dl_know.save_crawl(existing)
        log_entity_change("re-crawled", existing["id"], "knowledge_crawl",
                          f"{name} — {pages_crawled} pages, {total_chunks} chunks from {root_url}")
        return existing

    crawl_id = f"kc-{uuid.uuid4().hex[:8]}"
    manifest = {
        "id": crawl_id,
        "name": name,
        "root_url": root_url,
        "source_ids": source_ids,
        "pages_crawled": pages_crawled,
        "pages_failed": pages_failed,
        "total_chunks": total_chunks,
        "crawled_at": now,
    }
    _dl_know.save_crawl(manifest)

    log_entity_change("crawled", crawl_id, "knowledge_crawl",
                      f"{name} — {pages_crawled} pages, {total_chunks} chunks from {root_url}")
    return manifest


def list_crawls() -> list[dict]:
    """List all crawl manifests."""
    return _dl_know.get_all_crawls()


def get_crawl(crawl_id: str) -> dict | None:
    """Get a single crawl manifest by ID."""
    for c in _dl_know.get_all_crawls():
        if c["id"] == crawl_id:
            return c
    return None


def format_crawl_manifest(manifest: dict) -> str:
    """Format a crawl manifest as a markdown summary suitable for artifact content."""
    sources = {s["id"]: s for s in _dl_know.get_all_sources()}

    lines = [
        f"# Knowledge Crawl: {manifest['name']}",
        "",
        f"- **Crawl ID:** {manifest['id']}",
        f"- **Root URL:** {manifest['root_url']}",
        f"- **Pages crawled:** {manifest['pages_crawled']}",
        f"- **Pages failed:** {manifest['pages_failed']}",
        f"- **Total chunks:** {manifest['total_chunks']}",
        f"- **Crawled at:** {manifest['crawled_at'][:19]}",
        "",
        "## Sources",
        "",
    ]
    for sid in manifest.get("source_ids", []):
        src = sources.get(sid)
        if src:
            lines.append(f"- `{sid}` — {src.get('url', '?')} ({src.get('chunk_count', 0)} chunks)")
        else:
            lines.append(f"- `{sid}` — (removed)")

    lines.append("")
    lines.append("Use `query_knowledge` to search content from these sources.")
    return "\n".join(lines)


def migrate_chunk_embeddings() -> dict:
    """No-op — embeddings are now stored in Postgres pgvector.

    Returns:
        dict with counts indicating no migration needed.
    """
    return {"total": 0, "migrated": 0, "already_binary": 0}
