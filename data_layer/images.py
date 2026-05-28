"""Images — Postgres CRUD
=========================
Data layer for the top-level image entity.
Images are stored on disk; metadata lives in Postgres.
"""

import logging
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning

logger = logging.getLogger(__name__)


def save_image(image: dict):
    """Insert a new image record."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO images (id, title, filename, mime_type, size_bytes,
                                    storage_path, uploaded_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    filename = EXCLUDED.filename
            """, (
                image["id"],
                image.get("title", ""),
                image.get("filename", ""),
                image.get("mime_type", "image/jpeg"),
                image.get("size_bytes", 0),
                image.get("storage_path", ""),
                image.get("uploaded_by", ""),
                image.get("created_at", _now()),
            ))
        conn.commit()


def get_image(image_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM images WHERE id = %s", (image_id,))
    return _row(row) if row else None


def get_all_images() -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM images ORDER BY created_at DESC"
    )]


def get_latest_chart_for_ticker(ticker: str) -> dict | None:
    """Return the most recently created chart image for a ticker (title ILIKE '{ticker} Chart%')."""
    row = fetch_one(
        "SELECT * FROM images WHERE title ILIKE %s ORDER BY created_at DESC LIMIT 1",
        (f"{ticker.upper()} Chart%",),
    )
    return _row(row) if row else None


def update_image_title(image_id: str, title: str) -> bool:
    return execute(
        "UPDATE images SET title = %s WHERE id = %s",
        (title, image_id),
    ) > 0


def delete_image(image_id: str) -> bool:
    return execute("DELETE FROM images WHERE id = %s", (image_id,)) > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "filename": row.get("filename") or "",
        "mime_type": row.get("mime_type") or "",
        "size_bytes": row.get("size_bytes", 0),
        "storage_path": row.get("storage_path") or "",
        "uploaded_by": row.get("uploaded_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
