"""Folders — MCP tools.

Ten tools used by the chat agent:

- ``create_folder(name, owner, ...)``
- ``get_folder(folder_id)``
- ``list_folders(owner="", root_only="true")``
- ``add_to_folder(folder_id, entity_id)``
- ``create_doc_in_folder(folder_id, title, content, ...)``
- ``remove_from_folder(folder_id, entity_id)``
- ``move_to_folder(entity_id, from_folder, to_folder)``
- ``delete_folder(folder_id)``
- ``restore_folder(folder_id)``
- ``search_folders(query)``
"""

from app_platform.memory import digest_record
import apps.folders.store as _store


def create_folder(name: str, owner: str = "", parent_folder: str = "",
                  description: str = "", tags: str = "") -> str:
    """Create a new folder for organizing documents and files.

    Folders can be nested (subfolders) and optionally owned by a specific user.
    All folders are visible to everyone regardless of ownership.

    Ack: Creating folder...

    Args:
        name: Folder name (e.g. "Tax Documents", "Vacation Planning").
        owner: Who owns the folder. Leave empty for shared folders.
        parent_folder: Parent folder ID (fld-*) for nesting. Leave empty for root.
        description: Optional description of the folder's purpose.
        tags: Comma-separated tags.

    Returns:
        Confirmation with folder ID.
    """
    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    try:
        folder = _store.create_folder(
            name=name.strip(),
            created_by="skipper",
            owner=owner.strip().lower() if owner else "",
            parent_folder_id=parent_folder.strip() if parent_folder else "",
            description=description.strip() if description else "",
            tags=tag_list,
        )
    except ValueError as e:
        return f"Error: {e}"
    try:
        digest_record("folders", "folder", "created", folder["id"], folder, by=owner.strip().lower() if owner else "")
    except Exception:
        pass
    parent_info = f" inside {parent_folder}" if parent_folder else " (root level)"
    owner_info = f" owned by {folder['owner']}" if folder.get("owner") else " (shared)"
    return f"✅ Created folder **{name}** ({folder['id']}){parent_info}{owner_info}"


def get_folder(folder_id: str) -> str:
    """Get folder details and contents.

    Args:
        folder_id: Folder ID (fld-*).

    Returns:
        Folder info with list of contents (documents and artifacts).
    """
    detail = _store.get_folder_detail(folder_id.strip())
    if not detail:
        return f"Error: Folder '{folder_id}' not found."

    lines = [f"📂 **{detail['name']}** ({detail['id']})"]
    if detail.get("description"):
        lines.append(f"  {detail['description']}")
    lines.append(f"  Owner: {detail.get('owner') or 'shared'} | "
                 f"Items: {detail['item_count']} | "
                 f"Subfolders: {detail['subfolder_count']}")
    if detail.get("tags"):
        lines.append(f"  Tags: {', '.join(detail['tags'])}")

    if len(detail.get("breadcrumbs", [])) > 1:
        path = " > ".join(b["name"] for b in detail["breadcrumbs"])
        lines.append(f"  Path: {path}")

    if detail.get("subfolders"):
        lines.append("\n  **Subfolders:**")
        for sf in detail["subfolders"]:
            lines.append(f"    📂 {sf['name']} ({sf['id']})")

    if detail.get("items"):
        lines.append("\n  **Contents:**")
        for item in detail["items"]:
            icon = "📄" if item["entity_type"] == "document" else "📎"
            title = item.get("title", item["entity_id"])
            extra = ""
            if item.get("word_count"):
                extra = f" ({item['word_count']} words)"
            elif item.get("mime_type"):
                extra = f" ({item['mime_type']})"
            lines.append(f"    {icon} {title} — {item['entity_id']}{extra}")

    if not detail.get("subfolders") and not detail.get("items"):
        lines.append("\n  (empty folder)")

    return "\n".join(lines)


def list_folders(owner: str = "", root_only: str = "true") -> str:
    """List folders, optionally filtered by owner.

    Args:
        owner: Filter by owner name. Empty = all folders.
        root_only: If "true", only show root-level folders (not subfolders).

    Returns:
        List of folders with item counts.
    """
    is_root = root_only.lower().strip() in ("true", "yes", "1", "")
    folders = _store.list_folders(
        owner=owner.strip().lower() if owner else "",
        root_only=is_root,
    )

    if not folders:
        return "No folders found."

    lines = [f"📂 Folders ({len(folders)}):"]
    for f in folders:
        owner_str = f.get("owner") or "shared"
        sub_count = f.get("subfolder_count", 0)
        sub_str = f" + {sub_count} subfolders" if sub_count else ""
        lines.append(f"  📂 {f['name']} ({f['id']}) — {f.get('item_count', 0)} items{sub_str} | {owner_str}")
    return "\n".join(lines)


def add_to_folder(folder_id: str, entity_id: str) -> str:
    """Add an existing document or artifact to a folder.

    This triggers the folder intelligence pipeline, which extracts facts
    and creates searchable embeddings from the content.

    Ack: Adding to folder...

    Args:
        folder_id: Target folder ID (fld-*).
        entity_id: Document (d-*) or artifact (a-*) ID to add.

    Returns:
        Confirmation message.
    """
    result = _store.add_item(folder_id.strip(), entity_id.strip(), added_by="skipper")
    if isinstance(result, str):
        return result
    return (f"✅ Added {entity_id} to folder {folder_id}. "
            f"Intelligence processing will extract facts and create embeddings.")


def create_doc_in_folder(folder_id: str, title: str, content: str = "",
                         tags: str = "", created_by: str = "skipper") -> str:
    """Create a new document directly inside a folder.
    Creates the document and adds it to the folder in one step.
    Triggers the folder intelligence pipeline automatically.

    Ack: Creating document in folder...

    Args:
        folder_id: Target folder ID (fld-*) to create the document in.
        title: Document title.
        content: Document content (markdown). Can be empty for a blank doc.
        tags: Comma-separated tags for the document.
        created_by: Who is creating the document (default: "skipper").

    Returns:
        Confirmation with document ID and folder name.
    """
    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    result = _store.create_doc_in_folder(
        folder_id=folder_id.strip(),
        title=title.strip(),
        created_by=created_by.strip() if created_by else "skipper",
        content=content,
        tags=tag_list,
    )
    if isinstance(result, str):
        return result
    doc = result["doc"]
    folder = result["folder"]
    return (f"✅ Created document **{doc['title']}** ({doc['id']}) "
            f"in folder **{folder['name']}** ({folder['id']}). "
            f"Intelligence processing queued.")


def remove_from_folder(folder_id: str, entity_id: str) -> str:
    """Remove a document or artifact from a folder.

    The document/artifact itself is NOT deleted — just removed from the folder.
    Associated folder knowledge (facts/embeddings) for this item will be cleaned up.

    Args:
        folder_id: Folder ID (fld-*).
        entity_id: Document (d-*) or artifact (a-*) ID to remove.

    Returns:
        Confirmation message.
    """
    result = _store.remove_item(folder_id.strip(), entity_id.strip(), removed_by="skipper")
    if result:
        return f"✅ Removed {entity_id} from folder {folder_id}."
    return f"Error: {entity_id} not found in folder {folder_id}."


def move_to_folder(entity_id: str, from_folder: str, to_folder: str) -> str:
    """Move a document or artifact from one folder to another.

    Ack: Moving item...

    Args:
        entity_id: Document (d-*) or artifact (a-*) ID.
        from_folder: Source folder ID (fld-*).
        to_folder: Destination folder ID (fld-*).

    Returns:
        Confirmation message.
    """
    result = _store.move_item(
        entity_id.strip(), from_folder.strip(), to_folder.strip(),
        moved_by="skipper",
    )
    if isinstance(result, str):
        return result
    return f"✅ Moved {entity_id} from {from_folder} to {to_folder}. Intelligence processing queued."


def delete_folder(folder_id: str) -> str:
    """Delete a folder. Contents are not deleted — they remain as standalone
    documents/artifacts. Sub-folders become root-level folders.

    Args:
        folder_id: Folder ID (fld-*) to delete.

    Returns:
        Confirmation message.
    """
    record = _store.get_folder(folder_id.strip()) or {"id": folder_id.strip()}
    result = _store.delete_folder(folder_id.strip(), deleted_by="skipper")
    if result:
        try:
            digest_record("folders", "folder", "deleted", folder_id.strip(), record, by=record.get("owner", ""))
        except Exception:
            pass
        return f"✅ Deleted folder {folder_id}. Contents and subfolders are preserved."
    return f"Error: Folder '{folder_id}' not found."


def restore_folder(folder_id: str) -> str:
    """Restore a previously deleted folder.

    Ack: Restoring folder...

    Args:
        folder_id: Folder ID (fld-*) to restore.

    Returns:
        Confirmation message.
    """
    result = _store.restore_folder(folder_id.strip(), restored_by="skipper")
    if result:
        return f"✅ Restored folder {folder_id}."
    return f"Error: Folder '{folder_id}' not found or is not deleted."


def search_folders(query: str) -> str:
    """Search folders by name, description, or tags.

    Args:
        query: Search text.

    Returns:
        Matching folders with item counts.
    """
    folders = _store.search_folders(query.strip())
    if not folders:
        return f"No folders matching '{query}'."

    lines = [f"Found {len(folders)} folder(s) matching '{query}':"]
    for f in folders:
        owner_str = f.get("owner") or "shared"
        lines.append(f"  📂 {f['name']} ({f['id']}) — {f.get('item_count', 0)} items | {owner_str}")
    return "\n".join(lines)
