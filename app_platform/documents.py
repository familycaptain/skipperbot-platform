"""Platform Documents Service
=============================
Stable contract that every other app uses to read or mutate
documents. Forwards to ``apps.documents.store`` (friendly helpers that
fire digest_record + embed-on-save + folder-reprocess) and
``apps.documents.data`` (low-level CRUD + search).

This shim mirrors the ``app_platform.notifications`` /
``reminders`` / ``schedules`` / ``jobs`` patterns established in
earlier chunks. Apps use a short, stable import path —
``from app_platform.documents import create_doc, get_doc`` — that is
documented in ``APP_PACKAGES.md`` as the way to talk to documents. If
we ever swap implementations, all consumers stay unchanged.

Usage from an app or platform module:

    from app_platform.documents import create_doc, search_docs

    doc = create_doc(
        title="Research findings",
        content="…markdown body…",
        tags=["research"],
        created_by="alice",
    )
"""

from __future__ import annotations

# ---- Store layer (friendly helpers — digest_record + auto_memory) ----
from apps.documents.store import (
    create_doc,
    get_doc,
    get_doc_meta,
    list_docs,
    search_docs,
    update_doc,
    append_to_doc,
    update_doc_meta,
    delete_doc,
    format_doc_list,
)

# ---- Data layer (low-level CRUD + semantic / hybrid search) ----
from apps.documents.data import (
    save_document,
    get_document,
    get_document_content,
    get_all_documents,
    update_content,
    delete_document,
    search_documents,
    search_documents_hybrid,
    update_embedding,
)

__all__ = [
    # Store layer
    "create_doc", "get_doc", "get_doc_meta", "list_docs", "search_docs",
    "update_doc", "append_to_doc", "update_doc_meta", "delete_doc",
    "format_doc_list",
    # Data layer
    "save_document", "get_document", "get_document_content",
    "get_all_documents", "update_content", "delete_document",
    "search_documents", "search_documents_hybrid", "update_embedding",
]
