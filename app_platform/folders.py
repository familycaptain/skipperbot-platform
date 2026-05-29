"""Platform Folders Service
==========================
Stable contract that every other app and platform module uses to read
or mutate folders + folder knowledge. Forwards to ``apps.folders.store``
(friendly helpers that fire digest_record + link management +
intelligence-job dispatch), ``apps.folders.data`` (low-level CRUD +
vector search), and ``apps.folders.intelligence`` (chat-side
folder-knowledge retrieval).

Mirrors the ``app_platform.notifications`` / ``reminders`` /
``schedules`` / ``jobs`` / ``documents`` patterns. Apps use a short,
stable import path — ``from app_platform.folders import …`` — that is
documented in ``APP_PACKAGES.md`` as the way to talk to folders.

Usage from an app or platform module::

    from app_platform.folders import (
        get_folder, list_folders, ensure_folder_for_entity,
        get_folders_containing, get_relevant_folder_knowledge,
    )

    folders = list_folders(root_only=True)
    folder = ensure_folder_for_entity("vacation-2026", entity_type="project")
"""

from __future__ import annotations

# ---- Store layer (friendly helpers — digest_record + links + intel dispatch) ----
from apps.folders.store import (
    create_folder,
    get_folder,
    get_folder_detail,
    list_folders,
    update_folder,
    delete_folder,
    restore_folder,
    search_folders,
    get_breadcrumbs,
    add_item,
    remove_item,
    move_item,
    get_folders_containing,
    reorder_items,
    ensure_folder_for_entity,
    create_doc_in_folder,
    get_full_tree,
)

# ---- Data layer (low-level CRUD + vector knowledge search) ----
from apps.folders.data import (
    get_all_folders,
    get_child_folders,
    get_folder_by_related_entity,
    get_item_count,
    save_knowledge_row,
    delete_knowledge_for_entity,
    get_content_hash,
    search_knowledge,
    get_knowledge_for_entity,
)

# ---- Intelligence pipeline (chat-side retrieval + job handler) ----
from apps.folders.intelligence import (
    process_folder_item,
    reprocess_folder_item,
    search_folder_knowledge,
    get_relevant_folder_knowledge,
    format_folder_knowledge_for_context,
)

__all__ = [
    # Store layer
    "create_folder", "get_folder", "get_folder_detail", "list_folders",
    "update_folder", "delete_folder", "restore_folder", "search_folders",
    "get_breadcrumbs", "add_item", "remove_item", "move_item",
    "get_folders_containing", "reorder_items", "ensure_folder_for_entity",
    "create_doc_in_folder", "get_full_tree",
    # Data layer
    "get_all_folders", "get_child_folders", "get_folder_by_related_entity",
    "get_item_count",
    "save_knowledge_row", "delete_knowledge_for_entity", "get_content_hash",
    "search_knowledge", "get_knowledge_for_entity",
    # Intelligence
    "process_folder_item", "reprocess_folder_item",
    "search_folder_knowledge", "get_relevant_folder_knowledge",
    "format_folder_knowledge_for_context",
]
