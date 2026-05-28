"""Folders — Postgres CRUD + pgvector Search
=============================================
Data layer for folders, folder items, and folder knowledge.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536


def _gen_id(prefix: str = "fld") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Folders — CRUD
# ---------------------------------------------------------------------------

def create_folder(
    name: str,
    created_by: str = "",
    owner: str = "",
    parent_folder_id: str = "",
    related_entity_id: str = "",
    description: str = "",
    icon: str = "folder",
    color: str = "",
    sort_order: int = 0,
    tags: list[str] | None = None,
) -> dict:
    """Create a new folder and return it. Raises ValueError on duplicate name within same parent."""
    # Check for duplicate name at the same level (same parent_folder_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            if parent_folder_id:
                cur.execute(
                    "SELECT id FROM folders WHERE lower(name) = lower(%s) AND parent_folder_id = %s AND deleted_at IS NULL",
                    (name, parent_folder_id),
                )
            else:
                cur.execute(
                    "SELECT id FROM folders WHERE lower(name) = lower(%s) AND (parent_folder_id = '' OR parent_folder_id IS NULL) AND deleted_at IS NULL",
                    (name,),
                )
            if cur.fetchone():
                raise ValueError(f"A folder named '{name}' already exists at this level")
    folder = {
        "id": _gen_id("fld"),
        "name": name,
        "description": description,
        "owner": owner,
        "parent_folder_id": parent_folder_id or None,
        "related_entity_id": related_entity_id or "",
        "icon": icon,
        "color": color,
        "sort_order": sort_order,
        "tags": tags or [],
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO folders (id, name, description, owner, parent_folder_id,
                                     related_entity_id, icon, color, sort_order, tags,
                                     created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                folder["id"], folder["name"], folder["description"],
                folder["owner"], folder["parent_folder_id"],
                folder["related_entity_id"], folder["icon"], folder["color"],
                folder["sort_order"], folder["tags"], folder["created_by"],
                folder["created_at"], folder["updated_at"],
            ))
        conn.commit()
    return _folder_row_to_dict(folder)


def get_folder(folder_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM folders WHERE id = %s AND deleted_at IS NULL", (folder_id,))
    return _folder_row(row) if row else None


def get_all_folders(owner: str = "", root_only: bool = False) -> list[dict]:
    """List folders, optionally filtered by owner and/or root-only."""
    if owner and root_only:
        rows = fetch_all(
            "SELECT * FROM folders WHERE owner = %s AND (parent_folder_id = '' OR parent_folder_id IS NULL) AND deleted_at IS NULL ORDER BY sort_order, name",
            (owner,),
        )
    elif owner:
        rows = fetch_all(
            "SELECT * FROM folders WHERE owner = %s AND deleted_at IS NULL ORDER BY sort_order, name",
            (owner,),
        )
    elif root_only:
        rows = fetch_all(
            "SELECT * FROM folders WHERE (parent_folder_id = '' OR parent_folder_id IS NULL) AND deleted_at IS NULL ORDER BY sort_order, name",
        )
    else:
        rows = fetch_all("SELECT * FROM folders WHERE deleted_at IS NULL ORDER BY sort_order, name")
    return [_folder_row(r) for r in rows]


def get_child_folders(parent_folder_id: str) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM folders WHERE parent_folder_id = %s AND deleted_at IS NULL ORDER BY sort_order, name",
        (parent_folder_id,),
    )
    return [_folder_row(r) for r in rows]


def get_folder_by_related_entity(related_entity_id: str) -> dict | None:
    row = fetch_one(
        "SELECT * FROM folders WHERE related_entity_id = %s AND deleted_at IS NULL", (related_entity_id,),
    )
    return _folder_row(row) if row else None


def update_folder(folder_id: str, **kwargs) -> dict | None:
    """Update folder fields. Pass only the fields to change."""
    allowed = {"name", "description", "owner", "parent_folder_id",
               "related_entity_id", "icon", "color", "sort_order", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_folder(folder_id)

    updates["updated_at"] = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [folder_id]

    execute(f"UPDATE folders SET {set_clause} WHERE id = %s", tuple(values))
    return get_folder(folder_id)


def delete_folder(folder_id: str) -> bool:
    """Soft-delete a folder by setting deleted_at. Subfolders are promoted to root."""
    now = datetime.now(timezone.utc)
    # Promote child folders to root before soft-deleting
    execute("UPDATE folders SET parent_folder_id = NULL, updated_at = %s WHERE parent_folder_id = %s AND deleted_at IS NULL", (now, folder_id))
    return execute("UPDATE folders SET deleted_at = %s, updated_at = %s WHERE id = %s AND deleted_at IS NULL", (now, now, folder_id)) > 0


def restore_folder(folder_id: str) -> bool:
    """Restore a soft-deleted folder."""
    now = datetime.now(timezone.utc)
    return execute("UPDATE folders SET deleted_at = NULL, updated_at = %s WHERE id = %s AND deleted_at IS NOT NULL", (now, folder_id)) > 0


def search_folders(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all(
        "SELECT * FROM folders WHERE (name ILIKE %s OR description ILIKE %s) AND deleted_at IS NULL ORDER BY sort_order, name",
        (pattern, pattern),
    )
    return [_folder_row(r) for r in rows]


def get_breadcrumbs(folder_id: str) -> list[dict]:
    """Return the parent chain from root to this folder (inclusive)."""
    chain = []
    current_id = folder_id
    seen = set()
    while current_id and current_id not in seen:
        seen.add(current_id)
        folder = get_folder(current_id)
        if not folder:
            break
        chain.append({"id": folder["id"], "name": folder["name"]})
        current_id = folder["parent_folder_id"]
    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# Folder Items — junction table
# ---------------------------------------------------------------------------

def add_item(folder_id: str, entity_id: str, entity_type: str = "",
             added_by: str = "", position: int = 0) -> dict | None:
    """Add an item to a folder. Returns the item row or None on conflict."""
    if not entity_type:
        entity_type = _entity_type_from_id(entity_id)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO folder_items (folder_id, entity_id, entity_type, position, added_by, added_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (folder_id, entity_id) DO NOTHING
                    RETURNING *
                """, (folder_id, entity_id, entity_type, position, added_by,
                      datetime.now(timezone.utc)))
                row = cur.fetchone()
            conn.commit()
        if row is None:
            # Already exists
            return get_item(folder_id, entity_id)
        return _item_row_raw(row)
    except Exception:
        logger.exception("add_item failed: folder=%s entity=%s", folder_id, entity_id)
        return None


def remove_item(folder_id: str, entity_id: str) -> bool:
    return execute(
        "DELETE FROM folder_items WHERE folder_id = %s AND entity_id = %s",
        (folder_id, entity_id),
    ) > 0


def get_item(folder_id: str, entity_id: str) -> dict | None:
    row = fetch_one(
        "SELECT * FROM folder_items WHERE folder_id = %s AND entity_id = %s",
        (folder_id, entity_id),
    )
    return _item_row(row) if row else None


def get_items(folder_id: str) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM folder_items WHERE folder_id = %s ORDER BY position, added_at",
        (folder_id,),
    )
    return [_item_row(r) for r in rows]


def get_folders_containing(entity_id: str) -> list[dict]:
    """Get all folders that contain a given entity."""
    rows = fetch_all("""
        SELECT f.* FROM folders f
        JOIN folder_items fi ON fi.folder_id = f.id
        WHERE fi.entity_id = %s AND f.deleted_at IS NULL
        ORDER BY f.name
    """, (entity_id,))
    return [_folder_row(r) for r in rows]


def reorder_items(folder_id: str, entity_ids: list[str]) -> None:
    """Reorder items in a folder by setting position based on list order."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for i, eid in enumerate(entity_ids):
                cur.execute(
                    "UPDATE folder_items SET position = %s WHERE folder_id = %s AND entity_id = %s",
                    (i, folder_id, eid),
                )
        conn.commit()


def get_item_count(folder_id: str) -> int:
    row = fetch_one(
        "SELECT COUNT(*) AS cnt FROM folder_items WHERE folder_id = %s",
        (folder_id,),
    )
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Folder Knowledge — facts + content chunks with embeddings
# ---------------------------------------------------------------------------

def save_knowledge_row(
    folder_id: str,
    entity_id: str,
    chunk_type: str,
    text: str,
    embedding: Optional[list[float]] = None,
    tags: list[str] | None = None,
    source_title: str = "",
    content_hash: str = "",
) -> dict:
    """Insert a single knowledge row (fact or content chunk)."""
    row_id = _gen_id("fk")
    emb_str = _vec(embedding) if embedding else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO folder_knowledge
                    (id, folder_id, entity_id, chunk_type, text, tags,
                     embedding, source_title, content_hash, processed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                row_id, folder_id, entity_id, chunk_type, text,
                tags or [], emb_str, source_title, content_hash,
                datetime.now(timezone.utc),
            ))
        conn.commit()
    return {"id": row_id, "folder_id": folder_id, "entity_id": entity_id,
            "chunk_type": chunk_type, "text": text, "tags": tags or [],
            "source_title": source_title, "content_hash": content_hash}


def delete_knowledge_for_entity(entity_id: str, folder_id: str = "") -> int:
    """Delete knowledge rows for an entity, optionally scoped to a folder."""
    if folder_id:
        return execute(
            "DELETE FROM folder_knowledge WHERE entity_id = %s AND folder_id = %s",
            (entity_id, folder_id),
        )
    return execute(
        "DELETE FROM folder_knowledge WHERE entity_id = %s", (entity_id,),
    )


def get_content_hash(entity_id: str) -> str:
    """Get the content_hash from the most recent knowledge row for an entity."""
    row = fetch_one(
        "SELECT content_hash FROM folder_knowledge WHERE entity_id = %s ORDER BY processed_at DESC LIMIT 1",
        (entity_id,),
    )
    return row["content_hash"] if row else ""


def search_knowledge(
    query_embedding: list[float],
    folder_id: str = "",
    chunk_type: str = "",
    max_results: int = 5,
    min_similarity: float = 0.3,
) -> list[dict]:
    """Semantic search over folder knowledge using pgvector cosine distance."""
    from data_layer.db import fetch_all_vector  # raises ivfflat.probes for full recall
    emb_str = _vec(query_embedding)

    params_list: list = []
    if folder_id:
        params_list.append(folder_id)
    if chunk_type:
        params_list.append(chunk_type)

    rows = fetch_all_vector(f"""
        SELECT fk.*, f.name AS folder_name,
               1 - (fk.embedding <=> %s::vector) AS score
        FROM folder_knowledge fk
        JOIN folders f ON f.id = fk.folder_id
        WHERE fk.embedding IS NOT NULL
          AND f.deleted_at IS NULL
          {"AND fk.folder_id = %s" if folder_id else ""}
          {"AND fk.chunk_type = %s" if chunk_type else ""}
          AND 1 - (fk.embedding <=> %s::vector) >= %s
        ORDER BY fk.embedding <=> %s::vector
        LIMIT %s
    """, tuple([emb_str] + params_list + [emb_str, min_similarity, emb_str, max_results]))

    return [_knowledge_row(r) | {"score": float(r["score"]), "folder_name": r["folder_name"]}
            for r in rows]


def get_knowledge_for_entity(entity_id: str) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM folder_knowledge WHERE entity_id = %s ORDER BY chunk_type, processed_at",
        (entity_id,),
    )
    return [_knowledge_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec(embedding: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in embedding) + "]"


def _entity_type_from_id(entity_id: str) -> str:
    if entity_id.startswith("d-"):
        return "document"
    if entity_id.startswith("a-"):
        return "artifact"
    return ""


def _folder_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "owner": row.get("owner") or "",
        "parent_folder_id": row.get("parent_folder_id") or "",
        "related_entity_id": row.get("related_entity_id") or "",
        "icon": row.get("icon") or "folder",
        "color": row.get("color") or "",
        "sort_order": row.get("sort_order", 0),
        "tags": row.get("tags") or [],
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if hasattr(row.get("created_at", ""), "isoformat") else str(row.get("created_at", "")),
        "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at", ""), "isoformat") else str(row.get("updated_at", "")),
    }


def _folder_row_to_dict(folder: dict) -> dict:
    """Convert a dict with datetime objects to serializable form."""
    return {
        **folder,
        "created_at": folder["created_at"].isoformat() if hasattr(folder["created_at"], "isoformat") else str(folder["created_at"]),
        "updated_at": folder["updated_at"].isoformat() if hasattr(folder["updated_at"], "isoformat") else str(folder["updated_at"]),
    }


def _item_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "folder_id": row["folder_id"],
        "entity_id": row["entity_id"],
        "entity_type": row.get("entity_type") or "",
        "position": row.get("position", 0),
        "added_by": row.get("added_by") or "",
        "added_at": row["added_at"].isoformat() if hasattr(row.get("added_at", ""), "isoformat") else str(row.get("added_at", "")),
    }


def _item_row_raw(row) -> dict:
    """Handle raw cursor row (tuple) from RETURNING — fall back to dict-style."""
    if isinstance(row, dict):
        return _item_row(row)
    # psycopg2 without RealDictCursor returns tuples
    # Columns: id, folder_id, entity_id, entity_type, position, added_by, added_at
    return {
        "id": row[0], "folder_id": row[1], "entity_id": row[2],
        "entity_type": row[3] or "", "position": row[4] or 0,
        "added_by": row[5] or "",
        "added_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
    }


def _knowledge_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "folder_id": row["folder_id"],
        "entity_id": row["entity_id"],
        "chunk_type": row.get("chunk_type") or "content",
        "text": row["text"],
        "tags": row.get("tags") or [],
        "source_title": row.get("source_title") or "",
        "content_hash": row.get("content_hash") or "",
        "processed_at": row["processed_at"].isoformat() if hasattr(row.get("processed_at", ""), "isoformat") else str(row.get("processed_at", "")),
    }
