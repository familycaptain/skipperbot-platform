"""Artifact Store
================
File attachments for any entity (a-* IDs).

Backed by Postgres via data_layer.artifacts.
Text content stored in TEXT column, binary files in BYTEA.

An artifact can be attached to any entity via related_entity_id.
"""

import mimetypes
import os
import uuid
from datetime import datetime

from config import logger
from app_platform.time import get_timezone
from auto_memory import log_entity_change
from link_registry import create_link, delete_links_for_entity
import data_layer.artifacts as _dl_art


def _now_iso() -> str:
    return datetime.now(get_timezone()).isoformat()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_artifact(
    name: str,
    created_by: str,
    content: str = "",
    source_path: str = "",
    related_entity_id: str = "",
    mime_type: str = "",
    tags: list[str] | None = None,
) -> dict | str:
    """Create an artifact (file attachment).

    Provide EITHER content (text stored directly) OR source_path (file copied in).

    Args:
        name: Display name (e.g. "meeting_notes.md", "screenshot.png").
        created_by: Who created it.
        content: Text content to store directly.
        source_path: Absolute path to an existing file to copy in.
        related_entity_id: Entity this attaches to (e.g. "p-1234", "g-5678").
        mime_type: Optional MIME type. Auto-detected from name if omitted.
        tags: Optional tags for filtering.

    Returns:
        Artifact metadata dict, or error string.
    """
    if not content and not source_path:
        return "Error: Provide either content or source_path."

    if source_path and not os.path.exists(source_path):
        return f"Error: Source file not found: {source_path}"

    artifact_id = f"a-{uuid.uuid4().hex[:8]}"

    # Determine MIME type
    if not mime_type:
        guessed, _ = mimetypes.guess_type(name)
        mime_type = guessed or "application/octet-stream"

    file_data = None
    file_size = 0

    if source_path:
        with open(source_path, "rb") as f:
            file_data = f.read()
        file_size = len(file_data)
    elif content:
        file_size = len(content.encode("utf-8"))

    meta = {
        "id": artifact_id,
        "name": name,
        "mime_type": mime_type,
        "size_bytes": file_size,
        "related_entity_id": related_entity_id.strip() if related_entity_id else "",
        "tags": tags or [],
        "created_by": created_by.lower().strip(),
        "created_at": _now_iso(),
    }
    _dl_art.save_artifact(meta, content=content, file_data=file_data)

    logger.info("ARTIFACT: Created %s (%s, %d bytes) by %s",
                artifact_id, name, file_size, created_by)

    # Bidirectional link: artifact ↔ related entity
    entity_ref = related_entity_id.strip() if related_entity_id else ""
    if entity_ref:
        create_link(entity_ref, artifact_id, relation="has_artifact", created_by=created_by)

        # Register as first-class citizen on goal/project/task entities
        if entity_ref[:2] in ("g-", "p-", "t-"):
            try:
                from apps.goals.store import _load_entity, _save_entity
                parent = _load_entity(entity_ref)
                if parent:
                    parent.setdefault("artifacts", []).append(artifact_id)
                    _save_entity(parent)
            except Exception as e:
                logger.error("ARTIFACT: Failed to register %s on %s: %s", artifact_id, entity_ref, e)

    log_entity_change("created", artifact_id, "artifact",
                      f"{name} ({_human_size(file_size)})",
                      by=created_by,
                      related_entities=[entity_ref] if entity_ref else [])
    return meta


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_artifact_meta(artifact_id: str) -> dict | None:
    """Get metadata for an artifact."""
    return _dl_art.get_artifact(artifact_id)


def get_artifact_content(artifact_id: str) -> str | None:
    """Read text content of an artifact. Returns None for binary files."""
    meta = _dl_art.get_artifact(artifact_id)
    if not meta:
        return None

    # Only read text-ish files
    if meta.get("mime_type", "").startswith("text/") or meta.get("mime_type") in (
        "application/json", "application/xml", "application/yaml",
        "application/javascript", "application/octet-stream",
    ):
        content = _dl_art.get_artifact_content(artifact_id)
        return content if content else None
    return None


def get_artifact_path(artifact_id: str) -> str | None:
    """Get the filesystem path to an artifact's file.

    Writes content from Postgres to a temp file for callers that need a path.
    """
    meta = _dl_art.get_artifact(artifact_id)
    if not meta:
        return None

    import tempfile
    # Try text content first, then binary
    content = _dl_art.get_artifact_content(artifact_id)
    if content:
        suffix = os.path.splitext(meta.get("name", "file"))[1] or ".txt"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="w")
        tmp.write(content)
        tmp.close()
        return tmp.name

    file_data = _dl_art.get_artifact_file_data(artifact_id)
    if file_data:
        suffix = os.path.splitext(meta.get("name", "file"))[1] or ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(file_data)
        tmp.close()
        return tmp.name

    return None


def list_artifacts(
    related_entity_id: str = "",
    created_by: str = "",
    tag: str = "",
) -> list[dict]:
    """List artifacts with optional filters."""
    all_arts = _dl_art.get_all_artifacts()
    results = []
    for meta in all_arts:
        if related_entity_id and meta.get("related_entity_id") != related_entity_id.strip():
            continue
        if created_by and meta.get("created_by") != created_by.lower().strip():
            continue
        if tag and tag.lower() not in [t.lower() for t in meta.get("tags", [])]:
            continue
        results.append(meta)

    return results


def format_artifacts(artifacts: list[dict]) -> str:
    """Format artifact list for display."""
    if not artifacts:
        return "No artifacts found."

    lines = [f"Artifacts ({len(artifacts)}):"]
    for a in artifacts:
        entity = f" → {a['related_entity_id']}" if a.get("related_entity_id") else ""
        tags = f" [{', '.join(a['tags'])}]" if a.get("tags") else ""
        size = _human_size(a.get("size_bytes", 0))
        lines.append(f"  [{a['id']}] {a['name']} ({size}){entity}{tags}")
        lines.append(f"    Type: {a.get('mime_type', '?')}  Created: {a['created_at'][:16]} by {a['created_by']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_artifact_content(
    artifact_id: str,
    content: str,
    updated_by: str = "",
) -> dict | str:
    """Replace the file content of an existing artifact in place.

    The artifact keeps its same a-* ID, links, and position in the parent's
    artifacts[] array.  Only the file bytes and size_bytes in meta change.

    Args:
        artifact_id: The artifact to update.
        content: New text content to write.
        updated_by: Who is updating it.

    Returns:
        Updated meta dict, or error string.
    """
    meta = _dl_art.get_artifact(artifact_id)
    if not meta:
        return f"Error: Artifact '{artifact_id}' not found."

    new_size = len(content.encode("utf-8"))
    meta["size_bytes"] = new_size
    meta["updated_at"] = _now_iso()
    if updated_by:
        meta["updated_by"] = updated_by.lower().strip()
    _dl_art.save_artifact(meta, content=content)

    logger.info("ARTIFACT: Updated %s (%s, %d bytes) by %s",
                artifact_id, meta["name"], new_size, updated_by or "?")
    log_entity_change("updated", artifact_id, "artifact",
                      f"{meta['name']} content replaced ({_human_size(new_size)})",
                      by=updated_by or "system",
                      related_entities=[meta.get("related_entity_id", "")] if meta.get("related_entity_id") else [])
    return meta


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_artifact(artifact_id: str) -> bool:
    """Delete an artifact."""
    meta = _dl_art.get_artifact(artifact_id)
    if not meta:
        return False

    # Remove from parent entity's artifacts[] array
    entity_ref = meta.get("related_entity_id", "")
    if entity_ref and entity_ref[:2] in ("g-", "p-", "t-"):
        try:
            from apps.goals.store import _load_entity, _save_entity
            parent = _load_entity(entity_ref)
            if parent and artifact_id in parent.get("artifacts", []):
                parent["artifacts"].remove(artifact_id)
                _save_entity(parent)
        except Exception as e:
            logger.error("ARTIFACT: Failed to unregister %s from %s: %s", artifact_id, entity_ref, e)

    # Clean up link_registry entries
    delete_links_for_entity(artifact_id)

    _dl_art.delete_artifact(artifact_id)
    logger.info("ARTIFACT: Deleted %s", artifact_id)
    log_entity_change("deleted", artifact_id, "artifact", meta.get("name", "?"))
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.0f} {unit}" if unit == "B" else f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"
