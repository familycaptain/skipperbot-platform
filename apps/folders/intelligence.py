"""Folders — intelligence job handler.

Post-processing pipeline for documents and artifacts added to folders.
Combines two approaches:
  1. Content chunking + embedding (knowledge-style)
  2. LLM fact extraction (digest-style)

When a document or artifact is added to a folder, this module:
  - Loads the content
  - Chunks the raw text and embeds each chunk
  - Extracts structured facts via LLM and embeds each fact
  - Stores everything in the app_folders.folder_knowledge table

Results are searchable via pgvector and recallable during chat.

Registered as the ``folder_intelligence`` job handler at app-load time
via ``apps/folders/handlers.py`` (which calls
``app_platform.jobs.register_handler('folder_intelligence', ...)``).
"""

import hashlib
import json
import logging
import re
from typing import Optional

from config import DUMB_MODEL
from providers.compat import chat_completion
import apps.folders.data as _dl_folders
import app_platform.documents as _dl_doc

logger = logging.getLogger(__name__)

# Embedding model is platform-wide (Settings → System → Embedding model),
# resolved in memory_store; _get_embedding defers to it.
from providers.model_config import provisioned_embedding_dim as _provisioned_embedding_dim
EMBEDDING_DIM = _provisioned_embedding_dim()  # provisioned at setup; default 1536 (MODEL_FLEXIBILITY #44)
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _extraction_model() -> str:
    """Model the folder-intelligence fact extractor uses
    (Settings → Folders: intelligence_extraction_model)."""
    try:
        from app_platform import settings as _settings
        return (_settings.get("intelligence_extraction_model", scope="app:folders",
                              default=DUMB_MODEL) or DUMB_MODEL)
    except Exception:
        return DUMB_MODEL
CHARS_PER_TOKEN = 4

FOLDER_DIGEST_PROMPT = """\
You are a knowledge extraction assistant. Given the content of a document \
or file that has been filed into a folder, extract ALL key facts worth \
remembering.

Rules:
- One fact per distinct piece of information.
- Include WHO/WHAT/WHEN/WHERE details when present.
- Include specific names, dates, numbers, measurements, medical details, \
  financial figures, decisions, preferences, and any other concrete data.
- Each request includes a target number of facts based on the document's
  length and the configured extraction density. Aim for roughly that many,
  but adjust to the document's ACTUAL information density — extract more if
  it's packed with distinct facts, fewer if it's sparse or repetitive.
- Do NOT summarize or compress. Extract distinct pieces of information. \
  A long document with many details should yield many facts.
- Each fact should be self-contained (understandable without the source doc).
- Include the document title context in facts when it adds clarity.

Respond with a JSON array:
[
  {"fact": "...", "tags": ["..."], "about": "...or null", "related_entities": ["..."]}
]

If nothing is worth extracting, respond with: []
"""

_ENTITY_RE = re.compile(
    r"\b([a-z]+-[0-9a-f]{8})\b"
)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _get_embedding(text: str) -> list[float]:
    """Embed text with the platform-wide embedding model.

    Folder-knowledge vectors must share the same model + dimension as the rest
    of the platform's vector space, so this defers to memory_store (driven by
    Settings → System → Embedding model) rather than a per-app model.
    """
    from memory_store import get_embedding
    return get_embedding(text)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks of approximately chunk_size tokens."""
    char_size = chunk_size * CHARS_PER_TOKEN
    char_overlap = overlap * CHARS_PER_TOKEN

    if len(text) <= char_size:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + char_size

        if end < len(text):
            para_break = text.rfind("\n\n", start + char_size // 2, end)
            if para_break > start:
                end = para_break
            else:
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
# Content loading
# ---------------------------------------------------------------------------

def _load_content(entity_id: str) -> tuple[str, str]:
    """Load text content and title for a document or artifact.

    Returns:
        (content, title) tuple. Content may be empty for binary artifacts.
    """
    if entity_id.startswith("d-"):
        doc = _dl_doc.get_document(entity_id)
        if not doc:
            return "", ""
        return doc.get("content", ""), doc.get("title", "")

    if entity_id.startswith("a-"):
        try:
            from data_layer.artifacts import get_artifact
            art = get_artifact(entity_id)
            if not art:
                return "", ""
            content = art.get("content", "") or ""
            title = art.get("name", art.get("original_name", ""))
            if not content:
                parts = [f"Artifact: {title}"]
                if art.get("mime_type"):
                    parts.append(f"Type: {art['mime_type']}")
                if art.get("tags"):
                    parts.append(f"Tags: {', '.join(art['tags'])}")
                if art.get("description"):
                    parts.append(art["description"])
                content = "\n".join(parts)
            return content, title
        except ImportError:
            logger.warning("FOLDER_INTEL: Cannot import artifacts data layer")
            return "", ""

    return "", ""


def _content_hash(content: str) -> str:
    """SHA-256 hash of content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Fact extraction via LLM
# ---------------------------------------------------------------------------

def _facts_per_chunk() -> float:
    """Extraction density (Settings → Folders: facts_per_chunk).

    Target facts ≈ this × chunk_count, where chunk_count ≈ document length.
    1 = sparse (~1 fact per chunk), higher = denser. Clamped to a sane range."""
    try:
        from app_platform import settings as _settings
        v = float(_settings.get("facts_per_chunk", scope="app:folders", default=4) or 4)
    except (TypeError, ValueError):
        v = 4.0
    return max(0.25, min(v, 20.0))


def _extract_facts(content: str, title: str) -> list[dict]:
    """Use LLM to extract structured facts from content.

    The target fact count scales with document length (chunk_count) × the
    configured extraction density (facts_per_chunk).
    """
    if not content or len(content.strip()) < 20:
        return []

    est_tokens = len(content) // CHARS_PER_TOKEN
    chunk_count = max(1, est_tokens // CHUNK_SIZE)        # rough document-length proxy
    target_facts = max(1, round(_facts_per_chunk() * chunk_count))
    visible_tokens = 400 + target_facts * 150
    reasoning_overhead = 4000
    max_tokens = min(visible_tokens + reasoning_overhead, 16000)

    user_content = (
        f"Document title: {title}\n\n"
        f"Approximate length: ~{est_tokens} tokens (~{chunk_count} chunk(s)).\n"
        f"Target: roughly {target_facts} fact(s) — scale to the document's actual "
        f"information density.\n\n---\n\n{content}"
    )

    try:
        completion = chat_completion(
            model=_extraction_model(),
            messages=[
                {"role": "system", "content": FOLDER_DIGEST_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=max_tokens,
        )

        raw = completion.content
        if not raw:
            logger.warning("FOLDER_INTEL: Empty response from model")
            return []

        raw = raw.strip()
        logger.debug("FOLDER_INTEL: Raw fact response (%d chars): %s", len(raw), raw[:200])

        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        facts = json.loads(raw)
        if not isinstance(facts, list):
            logger.warning("FOLDER_INTEL: Expected list, got %s", type(facts).__name__)
            return []

        return facts

    except json.JSONDecodeError as e:
        logger.error("FOLDER_INTEL: JSON parse failed: %s", e)
        return []
    except Exception as e:
        logger.error("FOLDER_INTEL: Fact extraction failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Main processing pipeline
# ---------------------------------------------------------------------------

def process_folder_item(folder_id: str, entity_id: str) -> dict:
    """Post-process a document or artifact added to a folder.

    1. Loads content from documents or artifacts
    2. Checks content hash — skips if unchanged
    3. Chunks and embeds raw content (knowledge-style)
    4. Extracts structured facts via LLM (digest-style)
    5. Embeds each fact
    6. Saves all to folder_knowledge table

    Idempotent — clears existing folder_knowledge rows for this
    entity_id + folder_id before re-processing.

    Returns:
        {chunks: int, facts: int, entity_id: str, error: str}
    """
    result = {"chunks": 0, "facts": 0, "entity_id": entity_id, "error": ""}

    content, title = _load_content(entity_id)
    if not content:
        result["error"] = f"No content found for {entity_id}"
        logger.warning("FOLDER_INTEL: %s", result["error"])
        return result

    new_hash = _content_hash(content)
    existing_hash = _dl_folders.get_content_hash(entity_id)
    if new_hash == existing_hash and existing_hash:
        logger.info("FOLDER_INTEL: Content unchanged for %s, skipping", entity_id)
        result["error"] = "skipped:unchanged"
        return result

    deleted = _dl_folders.delete_knowledge_for_entity(entity_id, folder_id=folder_id)
    if deleted:
        logger.info("FOLDER_INTEL: Cleared %d old knowledge rows for %s in %s",
                     deleted, entity_id, folder_id)

    chunks = chunk_text(content)
    for i, chunk in enumerate(chunks):
        try:
            embedding = _get_embedding(chunk)
            _dl_folders.save_knowledge_row(
                folder_id=folder_id,
                entity_id=entity_id,
                chunk_type="content",
                text=chunk,
                embedding=embedding,
                source_title=title,
                content_hash=new_hash,
            )
            result["chunks"] += 1
        except Exception as e:
            logger.error("FOLDER_INTEL: Failed to embed chunk %d for %s: %s", i, entity_id, e)

    raw_facts = _extract_facts(content, title)

    for item in raw_facts:
        fact_text = item.get("fact", "").strip()
        if not fact_text:
            continue

        tags = item.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags.append("folder_intel")

        llm_related = item.get("related_entities", [])
        if not isinstance(llm_related, list):
            llm_related = []
        regex_related = _ENTITY_RE.findall(fact_text)
        all_tags = list(set(tags + llm_related + regex_related))

        try:
            embedding = _get_embedding(fact_text)
            _dl_folders.save_knowledge_row(
                folder_id=folder_id,
                entity_id=entity_id,
                chunk_type="fact",
                text=fact_text,
                embedding=embedding,
                tags=all_tags,
                source_title=title,
                content_hash=new_hash,
            )
            result["facts"] += 1
        except Exception as e:
            logger.error("FOLDER_INTEL: Failed to embed fact for %s: %s", entity_id, e)

    logger.info("FOLDER_INTEL: Processed %s in %s — %d chunks, %d facts",
                entity_id, folder_id, result["chunks"], result["facts"])
    return result


def reprocess_folder_item(entity_id: str) -> list[dict]:
    """Re-process an entity across ALL folders it belongs to.

    Called when a document's content is updated.
    Full-replace: deletes old folder_knowledge rows, re-chunks,
    re-extracts facts, re-embeds. Skips if content_hash unchanged.

    Returns:
        List of result dicts, one per folder.
    """
    folders = _dl_folders.get_folders_containing(entity_id)
    if not folders:
        return []

    results = []
    for folder in folders:
        result = process_folder_item(folder["id"], entity_id)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Search and retrieval
# ---------------------------------------------------------------------------

def search_folder_knowledge(
    query: str,
    folder_id: str = "",
    chunk_type: str = "",
    max_results: int = 5,
    min_similarity: float = 0.3,
    query_embedding: Optional[list[float]] = None,
) -> list[dict]:
    """Semantic search over folder knowledge using pgvector.

    Args:
        query: Search text (will be embedded if query_embedding not provided).
        folder_id: Optional — limit search to a specific folder.
        chunk_type: Optional — 'content' or 'fact' (empty = both).
        max_results: Max results to return.
        min_similarity: Cosine similarity threshold.
        query_embedding: Pre-computed embedding to reuse.

    Returns:
        List of matching chunks/facts with similarity scores.
    """
    if query_embedding is None:
        query_embedding = _get_embedding(query)

    return _dl_folders.search_knowledge(
        query_embedding=query_embedding,
        folder_id=folder_id,
        chunk_type=chunk_type,
        max_results=max_results,
        min_similarity=min_similarity,
    )


def get_relevant_folder_knowledge(
    user_message: str,
    max_results: int = 3,
    query_embedding: Optional[list[float]] = None,
) -> list[dict]:
    """Retrieve folder knowledge relevant to a user message.

    Designed to be called from chat_domain.py for context injection.
    Searches BOTH facts and content chunks, preferring facts.
    """
    if query_embedding is None:
        query_embedding = _get_embedding(user_message)

    facts = _dl_folders.search_knowledge(
        query_embedding=query_embedding,
        chunk_type="fact",
        max_results=max_results,
        min_similarity=0.35,
    )

    remaining = max_results - len(facts)
    if remaining > 0:
        chunks = _dl_folders.search_knowledge(
            query_embedding=query_embedding,
            chunk_type="content",
            max_results=remaining,
            min_similarity=0.4,
        )
        facts.extend(chunks)

    return facts


def format_folder_knowledge_for_context(results: list[dict]) -> str:
    """Format folder knowledge for injection into chat system prompt.

    Groups by source document/folder for readability.
    """
    if not results:
        return ""

    lines = ["## Relevant Folder Knowledge"]

    grouped: dict[str, list[dict]] = {}
    for r in results:
        key = f"{r.get('folder_name', '?')} / {r.get('source_title', '?')}"
        grouped.setdefault(key, []).append(r)

    for source, items in grouped.items():
        lines.append(f"\n**{source}:**")
        for item in items:
            prefix = "📌" if item.get("chunk_type") == "fact" else "📄"
            score = item.get("score", 0)
            lines.append(f"- {prefix} {item['text'][:300]} (relevance: {score:.2f})")

    return "\n".join(lines)
