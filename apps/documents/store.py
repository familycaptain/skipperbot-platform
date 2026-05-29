"""Documents — business logic.

Friendly create / get / append / update / search / delete helpers on
top of ``apps.documents.data``. Handles:

- ``d-*`` ID generation
- ``digest_record`` + ``log_entity_change`` on every mutation
- Embedding-on-save (calls OpenAI for the 1536-dim vector and
  persists it via ``apps.documents.data.update_embedding``)
- Folder reprocess trigger when a doc changes (so the Folders app's
  intelligence stays in sync)
- Link-registry edges to the doc's ``related_entity_id`` and
  ``parent_doc_id`` so the Links graph reflects doc threading

Ported from ``doc_store.py`` for sub-chunk 10c-part-2. Functionally
identical; only changes are routing all persistence through
``apps.documents.data`` and the job-submission for folder reprocess
through ``app_platform.jobs`` (which it was already doing).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config import logger, TIMEZONE
from auto_memory import log_entity_change
from link_registry import create_link, delete_links_for_entity
from apps.documents import data as _dl_doc


# ---------------------------------------------------------------------------
# Embedding helper — compute & store document embeddings for semantic search
# ---------------------------------------------------------------------------

def _embed_document(doc_id: str, title: str, content: str, tags: list[str]):
    """Compute and store an embedding for a document (fire-and-forget safe)."""
    try:
        from memory_store import get_embedding
        # Build an embeddable summary: title + tags + first ~2000 chars of content
        text = f"{title}\n{', '.join(tags)}\n{content[:2000]}"
        embedding = get_embedding(text[:8000])
        _dl_doc.update_embedding(doc_id, embedding)
    except Exception as e:
        logger.warning("DOC: Failed to embed document %s: %s", doc_id, e)


CENTRAL_TZ = ZoneInfo(TIMEZONE)


def _now_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


def _trigger_folder_reprocess(doc_id: str) -> None:
    """If this document belongs to any folders, queue intelligence reprocessing."""
    try:
        import data_layer.folders as _dl_folders
        folders = _dl_folders.get_folders_containing(doc_id)
        if not folders:
            return
        from app_platform.jobs import submit_job
        for folder in folders:
            submit_job(
                "folder_intelligence",
                config={"folder_id": folder["id"], "entity_id": doc_id},
                created_by="system:doc_update_hook",
            )
        logger.info(
            "DOC: Queued folder reprocess for %s across %d folders",
            doc_id, len(folders),
        )
    except Exception:
        logger.debug("DOC: Folder reprocess hook skipped for %s", doc_id, exc_info=True)


# ---------------------------------------------------------------------------
# Tokenization helpers for search
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Extract lowercase word tokens from text for search matching."""
    return set(_WORD_RE.findall(text.lower()))


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_doc(
    title: str,
    created_by: str,
    content: str = "",
    tags: list[str] | None = None,
    related_entity_id: str = "",
    parent_doc_id: str = "",
    version: int = 1,
) -> dict:
    """Create a new document.

    Args:
        title: Document title (e.g. "Solar Panel Research").
        created_by: Who created it.
        content: Initial markdown content. If empty, a heading is generated.
        tags: Optional tags for categorization/search.
        related_entity_id: Optional entity to link to (e.g. "p-1234").
        parent_doc_id: Optional parent document ID for versioning (e.g. "d-abc123").
        version: Version number (defaults to 1; set to 2+ for revisions).

    Returns:
        Document metadata dict.
    """
    doc_id = f"d-{uuid.uuid4().hex[:8]}"

    if not content:
        content = f"# {title}\n"

    # Normalize tags
    tag_list = [t.strip().lower() for t in (tags or []) if t.strip()]

    meta = {
        "id": doc_id,
        "title": title,
        "tags": tag_list,
        "created_by": created_by.lower().strip(),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "word_count": len(content.split()),
        "related_entity_id": related_entity_id.strip() if related_entity_id else "",
        "parent_doc_id": parent_doc_id.strip() if parent_doc_id else "",
        "version": version,
        "content": content,
    }
    _dl_doc.save_document(meta)

    # Link to related entity if provided
    entity_ref = related_entity_id.strip() if related_entity_id else ""
    if entity_ref:
        create_link(entity_ref, doc_id, relation="has_doc", created_by=created_by)

    # Link to parent doc if this is a revision
    parent_ref = parent_doc_id.strip() if parent_doc_id else ""
    if parent_ref:
        create_link(parent_ref, doc_id, relation="has_revision", created_by=created_by)

    related = [e for e in [entity_ref, parent_ref] if e]
    logger.info(
        "DOC: Created %s '%s' (v%d, %d words) by %s",
        doc_id, title, version, meta["word_count"], created_by,
    )
    log_entity_change(
        "created", doc_id, "doc",
        f"{title} (v{version}, {meta['word_count']} words)",
        by=created_by,
        related_entities=related,
    )

    # Compute embedding for semantic search
    _embed_document(doc_id, title, content, tag_list)

    return meta


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_doc(doc_id: str) -> dict | None:
    """Get a document's metadata and content.

    Returns:
        Dict with meta fields + 'content' key, or None if not found.
    """
    return _dl_doc.get_document(doc_id)


def get_doc_meta(doc_id: str) -> dict | None:
    """Get just the metadata (no content)."""
    doc = _dl_doc.get_document(doc_id)
    if not doc:
        return None
    doc.pop("content", None)
    return doc


def list_docs(
    tag: str = "",
    created_by: str = "",
    related_entity_id: str = "",
) -> list[dict]:
    """List documents with optional filters. Returns metadata only (no content).

    Args:
        tag: Filter by tag (case-insensitive).
        created_by: Filter by creator.
        related_entity_id: Filter by linked entity.

    Returns:
        List of metadata dicts, sorted by updated_at descending.
    """
    all_docs = _dl_doc.get_all_documents()
    results = []
    for meta in all_docs:
        meta.pop("content", None)

        if tag and tag.lower() not in [t.lower() for t in meta.get("tags", [])]:
            continue
        if created_by and meta.get("created_by") != created_by.lower().strip():
            continue
        if related_entity_id and meta.get("related_entity_id") != related_entity_id.strip():
            continue

        results.append(meta)

    results.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
    return results


def search_docs(query: str, tag: str = "") -> list[dict]:
    """Full-text search across all documents (title, tags, and content).

    Returns documents where ALL query words appear in the combined text of
    title + tags + content. Results are ranked by match density.

    Args:
        query: Search query (space-separated words, case-insensitive).
        tag: Optional tag filter to narrow scope before searching.

    Returns:
        List of metadata dicts (no content) with a 'match_score' field,
        sorted by relevance descending.
    """
    if not query or not query.strip():
        return list_docs(tag=tag)

    query_tokens = _tokenize(query)
    if not query_tokens:
        return list_docs(tag=tag)

    # Use data layer ILIKE search + local token scoring for ranking
    all_docs = _dl_doc.search_documents(query)
    results = []
    for doc in all_docs:
        meta = {k: v for k, v in doc.items() if k != "content"}
        content = doc.get("content", "")

        if tag and tag.lower() not in [t.lower() for t in meta.get("tags", [])]:
            continue

        # Build searchable text: title + tags + content
        search_text = " ".join([
            meta.get("title", ""),
            " ".join(meta.get("tags", [])),
            content,
        ])
        doc_tokens = _tokenize(search_text)

        # All query tokens must be present
        if not query_tokens.issubset(doc_tokens):
            continue

        match_count = sum(1 for t in doc_tokens if t in query_tokens)
        score = match_count / max(len(doc_tokens), 1)

        meta["match_score"] = round(score, 6)
        results.append(meta)

    results.sort(key=lambda d: d.get("match_score", 0), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_doc(
    doc_id: str,
    content: str,
    updated_by: str,
    title: str = "",
    tags: list[str] | None = None,
) -> dict | str:
    """Replace the full content of a document.

    Args:
        doc_id: The document to update.
        content: New markdown content (replaces everything).
        updated_by: Who is updating it.
        title: New title (optional, empty = keep current).
        tags: New tags (optional, None = keep current).

    Returns:
        Updated metadata dict, or error string.
    """
    doc = _dl_doc.get_document(doc_id)
    if not doc:
        return f"Error: Document '{doc_id}' not found."

    meta = {k: v for k, v in doc.items()}
    meta["content"] = content
    meta["word_count"] = len(content.split())
    meta["updated_at"] = _now_iso()
    meta["updated_by"] = updated_by.lower().strip()
    if title and title.strip():
        meta["title"] = title.strip()
    if tags is not None:
        meta["tags"] = [t.strip().lower() for t in tags if t.strip()]
    _dl_doc.save_document(meta)

    logger.info(
        "DOC: Updated %s '%s' (%d words) by %s",
        doc_id, meta["title"], meta["word_count"], updated_by,
    )
    log_entity_change(
        "updated", doc_id, "doc",
        f"{meta['title']} content replaced ({meta['word_count']} words)",
        by=updated_by,
    )

    # Re-embed for semantic search
    _embed_document(doc_id, meta["title"], content, meta.get("tags", []))

    # Trigger folder intelligence reprocessing if this doc is in any folders
    _trigger_folder_reprocess(doc_id)

    return meta


def append_to_doc(
    doc_id: str,
    content: str,
    updated_by: str,
) -> dict | str:
    """Append content to the end of a document.

    Adds a blank line separator before the new content.

    Args:
        doc_id: The document to append to.
        content: Markdown content to add at the end.
        updated_by: Who is appending.

    Returns:
        Updated metadata dict, or error string.
    """
    doc = _dl_doc.get_document(doc_id)
    if not doc:
        return f"Error: Document '{doc_id}' not found."

    existing = doc.get("content", "") or ""
    # Ensure blank line separator
    if existing and not existing.endswith("\n\n"):
        if existing.endswith("\n"):
            existing += "\n"
        else:
            existing += "\n\n"

    new_content = existing + content
    meta = {k: v for k, v in doc.items()}
    meta["content"] = new_content
    meta["word_count"] = len(new_content.split())
    meta["updated_at"] = _now_iso()
    meta["updated_by"] = updated_by.lower().strip()
    _dl_doc.save_document(meta)

    appended_words = len(content.split())
    logger.info(
        "DOC: Appended to %s '%s' (+%d words) by %s",
        doc_id, meta["title"], appended_words, updated_by,
    )
    log_entity_change(
        "updated", doc_id, "doc",
        f"Appended to {meta['title']} (+{appended_words} words)",
        by=updated_by,
    )

    # Re-embed for semantic search
    _embed_document(doc_id, meta["title"], new_content, meta.get("tags", []))

    # Trigger folder intelligence reprocessing if this doc is in any folders
    _trigger_folder_reprocess(doc_id)

    return meta


def update_doc_meta(
    doc_id: str,
    updated_by: str,
    title: str = "",
    tags: list[str] | None = None,
    related_entity_id: str | None = None,
) -> dict | str:
    """Update document metadata without changing content.

    Args:
        doc_id: The document to update.
        updated_by: Who is updating.
        title: New title (empty = keep current).
        tags: New tags (None = keep current).
        related_entity_id: New linked entity (None = keep current, "" = clear).

    Returns:
        Updated metadata dict, or error string.
    """
    doc = _dl_doc.get_document(doc_id)
    if not doc:
        return f"Error: Document '{doc_id}' not found."

    meta = {k: v for k, v in doc.items()}
    changes = []
    if title and title.strip():
        meta["title"] = title.strip()
        changes.append(f"title → {title.strip()}")
    if tags is not None:
        meta["tags"] = [t.strip().lower() for t in tags if t.strip()]
        changes.append(f"tags → {meta['tags']}")
    if related_entity_id is not None:
        old_ref = meta.get("related_entity_id", "")
        new_ref = related_entity_id.strip()
        if old_ref != new_ref:
            meta["related_entity_id"] = new_ref
            if new_ref:
                create_link(new_ref, doc_id, relation="has_doc", created_by=updated_by)
            changes.append(f"linked to {new_ref}" if new_ref else "link cleared")

    if not changes:
        meta.pop("content", None)
        return meta  # no-op

    meta["updated_at"] = _now_iso()
    meta["updated_by"] = updated_by.lower().strip()
    _dl_doc.save_document(meta)

    logger.info("DOC: Meta updated %s: %s", doc_id, "; ".join(changes))
    log_entity_change("updated", doc_id, "doc",
                      "; ".join(changes), by=updated_by)
    return meta


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_doc(doc_id: str) -> bool:
    """Delete a document.

    Returns:
        True if deleted, False if not found.
    """
    doc = _dl_doc.get_document(doc_id)
    if not doc:
        return False

    delete_links_for_entity(doc_id)
    _dl_doc.delete_document(doc_id)

    logger.info("DOC: Deleted %s", doc_id)
    log_entity_change("deleted", doc_id, "doc", doc.get("title", "?"))
    return True


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_doc_list(docs: list[dict]) -> str:
    """Format a list of doc metadata for display."""
    if not docs:
        return "No documents found."

    lines = [f"Documents ({len(docs)}):"]
    for d in docs:
        tags = f" [{', '.join(d.get('tags', []))}]" if d.get("tags") else ""
        entity = f" → {d['related_entity_id']}" if d.get("related_entity_id") else ""
        score = f" (relevance: {d['match_score']:.4f})" if "match_score" in d else ""
        lines.append(f"  [{d['id']}] {d['title']}{tags}{entity}{score}")
        lines.append(
            f"    {d.get('word_count', 0)} words | "
            f"Updated: {d.get('updated_at', d.get('created_at', '?'))[:16]} | "
            f"By: {d.get('updated_by', d.get('created_by', '?'))}"
        )
    return "\n".join(lines)
