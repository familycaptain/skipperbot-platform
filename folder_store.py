"""Folder Store
==============
Business logic layer for the Folders app. Thin wrapper around
data_layer.folders with link management, changelog logging,
cross-app convenience, and intelligence triggering.
"""

import logging

from config import TIMEZONE
from auto_memory import log_entity_change
from link_registry import create_link, delete_links_for_entity
import data_layer.folders as _dl
import data_layer.documents as _dl_doc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Folder CRUD
# ---------------------------------------------------------------------------

def create_folder(
    name: str,
    created_by: str,
    owner: str = "",
    parent_folder_id: str = "",
    related_entity_id: str = "",
    description: str = "",
    icon: str = "folder",
    color: str = "",
    tags: list[str] | None = None,
) -> dict:
    """Create a new folder with changelog and link management."""
    folder = _dl.create_folder(
        name=name,
        created_by=created_by,
        owner=owner,
        parent_folder_id=parent_folder_id,
        related_entity_id=related_entity_id,
        description=description,
        icon=icon,
        color=color,
        tags=tags,
    )

    # Link to parent folder
    if parent_folder_id:
        from data_layer.links import ensure_edge
        ensure_edge(folder["id"], parent_folder_id, "child_of", "parent_of")

    # Link to related entity
    if related_entity_id:
        from data_layer.links import ensure_edge
        ensure_edge(folder["id"], related_entity_id, "folder_for", "has_folder")

    logger.info("FOLDER: Created %s '%s' by %s", folder["id"], name, created_by)
    log_entity_change("created", folder["id"], "folder", name, by=created_by)
    return folder


def get_folder(folder_id: str) -> dict | None:
    return _dl.get_folder(folder_id)


def get_folder_detail(folder_id: str) -> dict | None:
    """Get folder with its items, subfolders, and breadcrumbs."""
    folder = _dl.get_folder(folder_id)
    if not folder:
        return None

    items = _dl.get_items(folder_id)
    subfolders = _dl.get_child_folders(folder_id)
    breadcrumbs = _dl.get_breadcrumbs(folder_id)

    # Enrich items with document/artifact metadata
    enriched_items = []
    for item in items:
        enriched = {**item}
        if item["entity_id"].startswith("d-"):
            doc = _dl_doc.get_document(item["entity_id"])
            if doc:
                enriched["title"] = doc.get("title", "")
                enriched["word_count"] = doc.get("word_count", 0)
                enriched["tags"] = doc.get("tags", [])
        elif item["entity_id"].startswith("a-"):
            try:
                from data_layer.artifacts import get_artifact
                art = get_artifact(item["entity_id"])
                if art:
                    enriched["title"] = art.get("name", art.get("original_name", ""))
                    enriched["mime_type"] = art.get("mime_type", "")
                    enriched["tags"] = art.get("tags", [])
            except ImportError:
                pass
        enriched_items.append(enriched)

    return {
        **folder,
        "items": enriched_items,
        "subfolders": subfolders,
        "breadcrumbs": breadcrumbs,
        "item_count": len(items),
        "subfolder_count": len(subfolders),
    }


def list_folders(owner: str = "", root_only: bool = True) -> list[dict]:
    """List folders with item counts."""
    folders = _dl.get_all_folders(owner=owner, root_only=root_only)
    for f in folders:
        f["item_count"] = _dl.get_item_count(f["id"])
        f["subfolder_count"] = len(_dl.get_child_folders(f["id"]))
    return folders


def update_folder(folder_id: str, updated_by: str, **kwargs) -> dict | None:
    """Update folder fields with changelog."""
    folder = _dl.update_folder(folder_id, **kwargs)
    if folder:
        changes = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        logger.info("FOLDER: Updated %s: %s by %s", folder_id, changes, updated_by)
        log_entity_change("updated", folder_id, "folder", changes, by=updated_by)
    return folder


def delete_folder(folder_id: str, deleted_by: str = "") -> bool:
    """Soft-delete a folder with cleanup."""
    folder = _dl.get_folder(folder_id)
    if not folder:
        return False

    delete_links_for_entity(folder_id)
    result = _dl.delete_folder(folder_id)

    if result:
        logger.info("FOLDER: Deleted %s '%s' by %s", folder_id, folder["name"], deleted_by)
        log_entity_change("deleted", folder_id, "folder", folder["name"], by=deleted_by)
    return result


def restore_folder(folder_id: str, restored_by: str = "") -> bool:
    """Restore a soft-deleted folder."""
    result = _dl.restore_folder(folder_id)
    if result:
        folder = _dl.get_folder(folder_id)
        name = folder["name"] if folder else folder_id
        logger.info("FOLDER: Restored %s '%s' by %s", folder_id, name, restored_by)
        log_entity_change("restored", folder_id, "folder", name, by=restored_by)
    return result


def search_folders(query: str) -> list[dict]:
    folders = _dl.search_folders(query)
    for f in folders:
        f["item_count"] = _dl.get_item_count(f["id"])
    return folders


def get_breadcrumbs(folder_id: str) -> list[dict]:
    return _dl.get_breadcrumbs(folder_id)


# ---------------------------------------------------------------------------
# Item management
# ---------------------------------------------------------------------------

def add_item(folder_id: str, entity_id: str, added_by: str = "") -> dict | str:
    """Add a document or artifact to a folder. Triggers intelligence pipeline."""
    folder = _dl.get_folder(folder_id)
    if not folder:
        return f"Error: Folder '{folder_id}' not found."

    item = _dl.add_item(folder_id, entity_id, added_by=added_by)
    if not item:
        return f"Error: Could not add '{entity_id}' to folder."

    # Create link
    from data_layer.links import ensure_edge
    ensure_edge(folder_id, entity_id, "contains", "filed_in")

    logger.info("FOLDER: Added %s to %s '%s' by %s",
                entity_id, folder_id, folder["name"], added_by)
    log_entity_change("updated", folder_id, "folder",
                      f"Added {entity_id} to {folder['name']}", by=added_by)

    # Trigger intelligence pipeline (async)
    _trigger_intelligence(folder_id, entity_id)

    return item


def remove_item(folder_id: str, entity_id: str, removed_by: str = "") -> bool:
    """Remove an item from a folder and clean up its knowledge."""
    result = _dl.remove_item(folder_id, entity_id)
    if result:
        # Clean up folder knowledge for this entity in this folder
        _dl.delete_knowledge_for_entity(entity_id, folder_id=folder_id)

        folder = _dl.get_folder(folder_id)
        name = folder["name"] if folder else folder_id
        logger.info("FOLDER: Removed %s from %s by %s", entity_id, folder_id, removed_by)
        log_entity_change("updated", folder_id, "folder",
                          f"Removed {entity_id} from {name}", by=removed_by)
    return result


def move_item(entity_id: str, from_folder: str, to_folder: str,
              moved_by: str = "") -> dict | str:
    """Move an item from one folder to another."""
    if not _dl.remove_item(from_folder, entity_id):
        return f"Error: '{entity_id}' not found in folder '{from_folder}'."

    # Clean up knowledge from old folder
    _dl.delete_knowledge_for_entity(entity_id, folder_id=from_folder)

    item = _dl.add_item(to_folder, entity_id, added_by=moved_by)
    if not item:
        return f"Error: Could not add '{entity_id}' to folder '{to_folder}'."

    # Update link
    from data_layer.links import ensure_edge
    ensure_edge(to_folder, entity_id, "contains", "filed_in")

    logger.info("FOLDER: Moved %s from %s to %s by %s",
                entity_id, from_folder, to_folder, moved_by)

    # Trigger intelligence on the new folder
    _trigger_intelligence(to_folder, entity_id)

    return item


def get_folders_containing(entity_id: str) -> list[dict]:
    return _dl.get_folders_containing(entity_id)


def reorder_items(folder_id: str, entity_ids: list[str]) -> None:
    _dl.reorder_items(folder_id, entity_ids)


# ---------------------------------------------------------------------------
# Cross-app convenience
# ---------------------------------------------------------------------------

def ensure_folder_for_entity(
    entity_id: str,
    name: str,
    created_by: str = "",
    owner: str = "",
    description: str = "",
) -> dict:
    """Get or create a folder linked to a specific entity.

    Used by other apps (e.g. Research) to auto-create folders for their entities.
    """
    existing = _dl.get_folder_by_related_entity(entity_id)
    if existing:
        return existing
    return create_folder(
        name=name,
        created_by=created_by,
        owner=owner,
        related_entity_id=entity_id,
        description=description,
    )


# ---------------------------------------------------------------------------
# Document-in-folder convenience
# ---------------------------------------------------------------------------

def create_doc_in_folder(
    folder_id: str,
    title: str,
    created_by: str,
    content: str = "",
    tags: list[str] | None = None,
) -> dict | str:
    """Create a new document and add it to a folder in one step."""
    folder = _dl.get_folder(folder_id)
    if not folder:
        return f"Error: Folder '{folder_id}' not found."

    from doc_store import create_doc
    doc = create_doc(title=title, created_by=created_by, content=content, tags=tags)

    item = add_item(folder_id, doc["id"], added_by=created_by)
    if isinstance(item, str):
        return item  # error

    return {
        "doc": doc,
        "folder": folder,
        "message": f"Created document '{title}' ({doc['id']}) in folder '{folder['name']}' ({folder_id})",
    }


# ---------------------------------------------------------------------------
# Tree operations
# ---------------------------------------------------------------------------

def get_full_tree(owner: str = "") -> list[dict]:
    """Return the complete folder hierarchy as nested dicts."""
    all_folders = _dl.get_all_folders(owner=owner)
    for f in all_folders:
        f["item_count"] = _dl.get_item_count(f["id"])

    # Build tree from flat list
    by_id = {f["id"]: {**f, "children": []} for f in all_folders}
    roots = []

    for f in all_folders:
        parent = f.get("parent_folder_id", "")
        if parent and parent in by_id:
            by_id[parent]["children"].append(by_id[f["id"]])
        else:
            roots.append(by_id[f["id"]])

    return roots


# ---------------------------------------------------------------------------
# Intelligence trigger
# ---------------------------------------------------------------------------

def _trigger_intelligence(folder_id: str, entity_id: str) -> None:
    """Queue intelligence processing for a folder item.

    Uses the job queue for async processing with retries and progress tracking.
    Falls back to fire-and-forget if job queue is unavailable.
    """
    try:
        from app_platform.jobs import submit_job
        submit_job(
            "folder_intelligence",
            config={"folder_id": folder_id, "entity_id": entity_id},
            created_by="system:folder_store",
        )
        logger.info("FOLDER: Queued intelligence job for %s in %s", entity_id, folder_id)
    except Exception:
        logger.warning("FOLDER: Could not queue intelligence job for %s in %s, "
                       "will process inline on next opportunity",
                       entity_id, folder_id, exc_info=True)
