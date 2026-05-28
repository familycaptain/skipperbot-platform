"""Artifacts — Postgres CRUD
============================
Drop-in replacement for artifact_store.py's flat-file persistence.
Text content stored in TEXT column, binary files in BYTEA.
"""

import logging
from datetime import datetime, timezone

import psycopg2

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)


def save_artifact(meta: dict, content: str = "", file_data: bytes | None = None):
    """Insert or update an artifact with optional text content or binary data."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO artifacts (id, name, mime_type, size_bytes, content,
                                       file_data, related_entity_id, tags,
                                       created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    mime_type = EXCLUDED.mime_type,
                    size_bytes = EXCLUDED.size_bytes,
                    content = EXCLUDED.content,
                    file_data = EXCLUDED.file_data,
                    related_entity_id = EXCLUDED.related_entity_id,
                    tags = EXCLUDED.tags
            """, (
                meta["id"], meta.get("name", ""), meta.get("mime_type", ""),
                meta.get("size_bytes", 0), content,
                psycopg2.Binary(file_data) if file_data else None,
                meta.get("related_entity_id", ""), meta.get("tags", []),
                meta.get("created_by", ""),
                meta.get("created_at", datetime.now(timezone.utc).isoformat()),
            ))
        conn.commit()


def get_artifact(artifact_id: str) -> dict | None:
    """Get artifact metadata (without file_data to avoid large reads)."""
    row = fetch_one(
        "SELECT id, name, mime_type, size_bytes, content, related_entity_id, tags, created_by, created_at "
        "FROM artifacts WHERE id = %s",
        (artifact_id,),
    )
    return _row(row) if row else None


def get_artifact_content(artifact_id: str) -> str:
    """Get text content of an artifact."""
    row = fetch_one("SELECT content FROM artifacts WHERE id = %s", (artifact_id,))
    return row["content"] if row else ""


def get_artifact_file_data(artifact_id: str) -> bytes | None:
    """Get binary file data of an artifact."""
    row = fetch_one("SELECT file_data FROM artifacts WHERE id = %s", (artifact_id,))
    if row and row["file_data"]:
        return bytes(row["file_data"])
    return None


def get_all_artifacts() -> list[dict]:
    rows = fetch_all(
        "SELECT id, name, mime_type, size_bytes, related_entity_id, tags, created_by, created_at "
        "FROM artifacts ORDER BY created_at DESC"
    )
    return [_row(r) for r in rows]


def delete_artifact(artifact_id: str) -> bool:
    return execute("DELETE FROM artifacts WHERE id = %s", (artifact_id,)) > 0


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "mime_type": row.get("mime_type") or "",
        "size_bytes": row.get("size_bytes", 0),
        "content": row.get("content") or "",
        "related_entity_id": row.get("related_entity_id") or "",
        "tags": row.get("tags") or [],
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
