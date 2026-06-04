"""
Artifact Tools - Attach files and documents to any entity.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from app_platform.memory import digest_record
from tools.secret_guard import is_secret_path
from artifact_store import (
    create_artifact as _create_artifact,
    get_artifact_meta as _get_meta,
    get_artifact_content as _get_content,
    list_artifacts as _list_artifacts,
    format_artifacts as _format_artifacts,
    delete_artifact as _delete_artifact,
    update_artifact_content as _update_content,
)


def attach_artifact(
    name: str,
    created_by: str,
    content: str = "",
    source_path: str = "",
    related_entity_id: str = "",
    tags: str = "",
) -> str:
    """Create a file attachment on any entity.

    Provide EITHER content (text) OR source_path (existing file to copy).

    Args:
        name: Filename (e.g. "notes.md", "diagram.png").
        created_by: Who is creating this (person name).
        content: Text content to store directly.
        source_path: Absolute path to existing file to copy in.
        related_entity_id: Entity to attach to (e.g. "p-1234", "g-5678").
        tags: Comma-separated tags for filtering.

    Returns:
        Confirmation with artifact ID.
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        # Sandbox source_path: only copy in files that live under the app root,
        # and never secret/credential files. Without this, an absolute path lets
        # the model exfiltrate /app/.env, ~/.pgpass, /etc/*, etc. (audit #19).
        if source_path and source_path.strip():
            sp = os.path.realpath(source_path.strip())
            if not (sp == APP_ROOT or sp.startswith(APP_ROOT + os.sep)):
                return "Error: source_path must be a file within the app folder."
            if is_secret_path(sp):
                return "Error: attaching secret/credential files is not permitted."

        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None

        result = _create_artifact(
            name=name.strip(),
            created_by=created_by.strip().lower(),
            content=content,
            source_path=source_path.strip() if source_path else "",
            related_entity_id=related_entity_id.strip() if related_entity_id else "",
            tags=tag_list,
        )

        if isinstance(result, str):
            return result  # Error

        try:
            digest_record("artifacts", "artifact", "created", result["id"], result, by=created_by.strip())
        except Exception:
            pass
        out = f"Artifact created (ID: {result['id']}).\n"
        out += f"  Name: {result['name']}\n"
        out += f"  Type: {result['mime_type']}\n"
        out += f"  Size: {result['size_bytes']} bytes\n"
        if result.get("related_entity_id"):
            out += f"  Attached to: {result['related_entity_id']}\n"
        if result.get("tags"):
            out += f"  Tags: {', '.join(result['tags'])}\n"
        return out
    except Exception as e:
        return f"Error in attach_artifact: {str(e)}"


def read_artifact(artifact_id: str) -> str:
    """Read an artifact's text content.

    Args:
        artifact_id: The artifact ID (e.g. "a-1234abcd").

    Returns:
        The text content, or info about the artifact if binary.
    """
    try:
        if not artifact_id or not artifact_id.strip():
            return "Error: artifact_id is required."

        meta = _get_meta(artifact_id.strip())
        if not meta:
            return f"Error: Artifact '{artifact_id}' not found."

        content = _get_content(artifact_id.strip())
        if content is not None:
            header = f"[{meta['id']}] {meta['name']} ({meta['mime_type']})\n---\n"
            return header + content

        return (
            f"Artifact {meta['id']} is binary ({meta['mime_type']}, "
            f"{meta['size_bytes']} bytes). Cannot display text content."
        )
    except Exception as e:
        return f"Error in read_artifact: {str(e)}"


def list_entity_artifacts(
    related_entity_id: str = "",
    created_by: str = "",
    tag: str = "",
) -> str:
    """List artifacts, optionally filtered.

    Args:
        related_entity_id: Show only artifacts attached to this entity.
        created_by: Filter by creator.
        tag: Filter by tag.

    Returns:
        Formatted list of artifacts.
    """
    try:
        artifacts = _list_artifacts(
            related_entity_id=related_entity_id.strip() if related_entity_id else "",
            created_by=created_by.strip().lower() if created_by else "",
            tag=tag.strip() if tag else "",
        )
        return _format_artifacts(artifacts)
    except Exception as e:
        return f"Error in list_entity_artifacts: {str(e)}"


def update_artifact(artifact_id: str, content: str, updated_by: str = "") -> str:
    """Replace the content of an existing artifact in place.

    The artifact keeps its same ID, links, and position in the parent entity's
    artifacts[] array. Use this instead of delete + recreate when updating a
    document (e.g. re-crawl manifest, revised notes).

    Args:
        artifact_id: The artifact ID to update (e.g. "a-1234abcd").
        content: New text content to write.
        updated_by: Who is updating it.

    Returns:
        Confirmation with updated metadata.
    """
    try:
        if not artifact_id or not artifact_id.strip():
            return "Error: artifact_id is required."
        if not content:
            return "Error: content is required."

        result = _update_content(
            artifact_id=artifact_id.strip(),
            content=content,
            updated_by=updated_by.strip().lower() if updated_by else "",
        )

        if isinstance(result, str):
            return result  # Error

        try:
            digest_record("artifacts", "artifact", "updated", result["id"], result, by=updated_by.strip().lower() if updated_by else "")
        except Exception:
            pass
        out = f"Artifact updated (ID: {result['id']}).\n"
        out += f"  Name: {result['name']}\n"
        out += f"  Size: {result['size_bytes']} bytes\n"
        if result.get("related_entity_id"):
            out += f"  Attached to: {result['related_entity_id']}\n"
        return out
    except Exception as e:
        return f"Error in update_artifact: {str(e)}"


def delete_artifact_by_id(artifact_id: str) -> str:
    """Delete an artifact.

    Args:
        artifact_id: The artifact ID to delete.

    Returns:
        Confirmation.
    """
    try:
        if not artifact_id or not artifact_id.strip():
            return "Error: artifact_id is required."
        record = _get_meta(artifact_id.strip()) or {"id": artifact_id.strip()}
        deleted = _delete_artifact(artifact_id.strip())
        if deleted:
            try:
                digest_record("artifacts", "artifact", "deleted", artifact_id.strip(), record, by=record.get("created_by", ""))
            except Exception:
                pass
            return f"Artifact {artifact_id.strip()} deleted."
        return f"Artifact '{artifact_id}' not found."
    except Exception as e:
        return f"Error in delete_artifact_by_id: {str(e)}"
