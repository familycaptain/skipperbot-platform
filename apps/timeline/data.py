"""Timeline — data layer.

Schema-scoped CRUD for ``app_timeline.timeline_posts`` (+ photos +
tag index). Post bodies live in the documents app via ``doc_id`` —
the data layer talks to ``app_platform.documents`` for that.

The platform's auto-activity log (``app_platform/activity.py``) does
*not* go through this module — it INSERTs directly via
``scoped_conn`` to avoid a circular import. Anything we add here that
changes the on-disk row shape needs to keep that path working.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app_platform.db import (
    execute_in_schema,
    fetch_all_in_schema,
    fetch_one_in_schema,
    scoped_conn,
)
from app_platform.documents import (
    save_document,
    get_document_content,
    delete_document,
)

logger = logging.getLogger(__name__)

SCHEMA = "app_timeline"


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Posts — CRUD
# ---------------------------------------------------------------------------

def create_post(
    author_id: str,
    body: str,
    title: str = "",
    tags: Optional[list[str]] = None,
    source_app: str = "",
    source_entity_id: str = "",
    source_label: str = "",
    pinned: bool = False,
    visibility: str = "everyone",
) -> dict:
    """Create a timeline post with a linked document for the body."""
    post_id = _new_id("tp")
    doc_id = _new_id("d")
    now = _now_iso()
    clean_tags = _normalize_tags(tags or [])

    save_document({
        "id": doc_id,
        "title": title or "Timeline post",
        "content": body,
        "tags": ["timeline"],
        "word_count": len(body.split()),
        "related_entity_id": post_id,
        "created_by": author_id,
        "created_at": now,
        "updated_at": now,
    })

    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO timeline_posts
                    (id, author_id, title, doc_id, tags, source_app,
                     source_entity_id, source_label, pinned, visibility,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    post_id, author_id, title, doc_id, clean_tags,
                    source_app, source_entity_id, source_label, pinned,
                    visibility, now, now,
                ),
            )
        conn.commit()

    _update_tag_index_add(clean_tags)
    return get_post(post_id)


def get_post(post_id: str) -> Optional[dict]:
    """Get a single post with its document content and photos."""
    row = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM timeline_posts WHERE id = %s", (post_id,),
    )
    if not row:
        return None
    post = _post_row(row)
    post["body"] = get_document_content(post["doc_id"]) if post["doc_id"] else ""
    photo_rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM timeline_photos WHERE post_id = %s ORDER BY sort_order",
        (post_id,),
    )
    post["photos"] = [_photo_row(r) for r in photo_rows]
    return post


def list_posts(
    tag: Optional[str] = None,
    author: Optional[str] = None,
    before: Optional[str] = None,
    after: Optional[str] = None,
    search: Optional[str] = None,
    visibility: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    include_body: bool = True,
) -> dict:
    """Paginated feed of posts, newest first.

    Returns ``{"posts": [...], "total": int, "has_more": bool}``.

    ``visibility`` defaults to "everyone-only" feeds — pass an explicit
    value (``"personal"`` / ``""`` for "no filter") to get the personal
    activity stream or the unfiltered union.
    """
    where_clauses: list[str] = []
    params: list = []

    if tag:
        where_clauses.append("%s = ANY(tags)")
        params.append(tag.lower().strip())
    if author:
        where_clauses.append("author_id = %s")
        params.append(author)
    if before:
        where_clauses.append("created_at < %s")
        params.append(before)
    if after:
        where_clauses.append("created_at > %s")
        params.append(after)
    if visibility:
        where_clauses.append("visibility = %s")
        params.append(visibility)

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    # When searching, join the documents app's schema for content search.
    # Documents now live in app_documents — qualify the JOIN.
    if search:
        pattern = f"%{search}%"
        count_sql = (
            f"SELECT COUNT(*) AS cnt FROM timeline_posts p "
            f"LEFT JOIN app_documents.documents d ON p.doc_id = d.id "
            f"WHERE ({where_sql}) AND (p.title ILIKE %s OR d.content ILIKE %s)"
        )
        count_params = params + [pattern, pattern]

        query_sql = (
            f"SELECT p.* FROM timeline_posts p "
            f"LEFT JOIN app_documents.documents d ON p.doc_id = d.id "
            f"WHERE ({where_sql}) AND (p.title ILIKE %s OR d.content ILIKE %s) "
            f"ORDER BY p.pinned DESC, p.created_at DESC LIMIT %s OFFSET %s"
        )
        query_params = params + [pattern, pattern, limit, offset]
    else:
        count_sql = f"SELECT COUNT(*) AS cnt FROM timeline_posts WHERE {where_sql}"
        count_params = params

        query_sql = (
            f"SELECT * FROM timeline_posts WHERE {where_sql} "
            f"ORDER BY pinned DESC, created_at DESC LIMIT %s OFFSET %s"
        )
        query_params = params + [limit, offset]

    total_row = fetch_one_in_schema(SCHEMA, count_sql, tuple(count_params))
    total = total_row["cnt"] if total_row else 0

    rows = fetch_all_in_schema(SCHEMA, query_sql, tuple(query_params))
    posts: list[dict] = []
    for row in rows:
        post = _post_row(row)
        post["body"] = (
            get_document_content(post["doc_id"]) if include_body and post["doc_id"] else ""
        )
        photo_rows = fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM timeline_photos WHERE post_id = %s ORDER BY sort_order",
            (post["id"],),
        )
        post["photos"] = [_photo_row(r) for r in photo_rows]
        posts.append(post)

    return {
        "posts": posts,
        "total": total,
        "has_more": (offset + limit) < total,
    }


def update_post(
    post_id: str,
    title: Optional[str] = None,
    body: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Optional[dict]:
    """Update post metadata and/or body."""
    existing = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM timeline_posts WHERE id = %s", (post_id,),
    )
    if not existing:
        return None

    old_tags = set(existing.get("tags") or [])
    now = _now_iso()
    sets = ["updated_at = %s"]
    params: list = [now]

    if title is not None:
        sets.append("title = %s")
        params.append(title)
    if tags is not None:
        clean_tags = _normalize_tags(tags)
        sets.append("tags = %s")
        params.append(clean_tags)
        new_tags = set(clean_tags)
    else:
        new_tags = old_tags

    params.append(post_id)
    execute_in_schema(
        SCHEMA,
        f"UPDATE timeline_posts SET {', '.join(sets)} WHERE id = %s",
        tuple(params),
    )

    if body is not None and existing.get("doc_id"):
        from app_platform.documents import update_content
        update_content(existing["doc_id"], body, len(body.split()))

    if tags is not None:
        removed = old_tags - new_tags
        added = new_tags - old_tags
        if removed:
            _update_tag_index_remove(list(removed))
        if added:
            _update_tag_index_add(list(added))

    return get_post(post_id)


def delete_post(post_id: str) -> bool:
    """Delete a post and its linked document (photos cascade via FK)."""
    existing = fetch_one_in_schema(
        SCHEMA, "SELECT * FROM timeline_posts WHERE id = %s", (post_id,),
    )
    if not existing:
        return False

    old_tags = existing.get("tags") or []
    execute_in_schema(SCHEMA, "DELETE FROM timeline_posts WHERE id = %s", (post_id,))
    if existing.get("doc_id"):
        delete_document(existing["doc_id"])
    if old_tags:
        _update_tag_index_remove(old_tags)
    return True


def toggle_pin(post_id: str) -> Optional[dict]:
    """Toggle the pinned status of a post."""
    existing = fetch_one_in_schema(
        SCHEMA, "SELECT pinned FROM timeline_posts WHERE id = %s", (post_id,),
    )
    if not existing:
        return None
    new_pinned = not existing["pinned"]
    execute_in_schema(
        SCHEMA,
        "UPDATE timeline_posts SET pinned = %s, updated_at = %s WHERE id = %s",
        (new_pinned, _now_iso(), post_id),
    )
    return get_post(post_id)


# ---------------------------------------------------------------------------
# Photos — CRUD
# ---------------------------------------------------------------------------

def add_photo(post_id: str, image_id: str, caption: str = "", sort_order: int = 0) -> dict:
    """Attach a photo to a post."""
    photo_id = _new_id("tph")
    now = _now_iso()
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO timeline_photos (id, post_id, image_id, caption, sort_order, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (photo_id, post_id, image_id, caption, sort_order, now),
            )
        conn.commit()
    return {
        "id": photo_id, "post_id": post_id, "image_id": image_id,
        "caption": caption, "sort_order": sort_order, "created_at": now,
    }


def remove_photo(photo_id: str) -> bool:
    """Remove a photo from a post."""
    return execute_in_schema(
        SCHEMA, "DELETE FROM timeline_photos WHERE id = %s", (photo_id,),
    ) > 0


# ---------------------------------------------------------------------------
# Authors
# ---------------------------------------------------------------------------

def list_authors() -> list[dict]:
    """Return distinct authors with post counts, ordered by count desc."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT author_id, COUNT(*) AS post_count FROM timeline_posts "
        "GROUP BY author_id ORDER BY post_count DESC, author_id",
        (),
    )
    return [{"author_id": r["author_id"], "post_count": r["post_count"]} for r in rows]


# ---------------------------------------------------------------------------
# Tag Index
# ---------------------------------------------------------------------------

def list_tags() -> list[dict]:
    """Return all tags with post counts, ordered by usage."""
    rows = fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM timeline_tag_index ORDER BY post_count DESC, tag",
        (),
    )
    return [
        {
            "tag": r["tag"],
            "post_count": r["post_count"],
            "last_used_at": r["last_used_at"].isoformat() if r.get("last_used_at") else "",
        }
        for r in rows
    ]


def _update_tag_index_add(tags: list[str]):
    """Increment tag counts (upsert)."""
    if not tags:
        return
    now = _now_iso()
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            for tag in tags:
                cur.execute(
                    """
                    INSERT INTO timeline_tag_index (tag, post_count, last_used_at)
                    VALUES (%s, 1, %s)
                    ON CONFLICT (tag) DO UPDATE SET
                        post_count = timeline_tag_index.post_count + 1,
                        last_used_at = EXCLUDED.last_used_at
                    """,
                    (tag, now),
                )
        conn.commit()


def _update_tag_index_remove(tags: list[str]):
    """Decrement tag counts; remove if zero."""
    if not tags:
        return
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            for tag in tags:
                cur.execute(
                    """
                    UPDATE timeline_tag_index
                    SET post_count = GREATEST(post_count - 1, 0)
                    WHERE tag = %s
                    """,
                    (tag,),
                )
            cur.execute("DELETE FROM timeline_tag_index WHERE post_count <= 0")
        conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_tags(tags: list[str]) -> list[str]:
    """Lowercase, trim, deduplicate tags."""
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        clean = t.lower().strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _post_row(row: dict) -> dict:
    """Convert a timeline_posts DB row to an API dict."""
    return {
        "id": row["id"],
        "author_id": row.get("author_id") or "",
        "title": row.get("title") or "",
        "doc_id": row.get("doc_id") or "",
        "tags": row.get("tags") or [],
        "source_app": row.get("source_app") or "",
        "source_entity_id": row.get("source_entity_id") or "",
        "source_label": row.get("source_label") or "",
        "pinned": row.get("pinned", False),
        "visibility": row.get("visibility") or "everyone",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _photo_row(row: dict) -> dict:
    """Convert a timeline_photos DB row to an API dict."""
    return {
        "id": row["id"],
        "post_id": row.get("post_id") or "",
        "image_id": row.get("image_id") or "",
        "caption": row.get("caption") or "",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
