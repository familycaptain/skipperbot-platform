"""DEPRECATED — Moved to apps/timeline/tools.py (app package).
This file is no longer imported. Safe to delete.
"""
# --- Original docstring ---
# Timeline Tools — Family journal and microblog: create posts, browse the feed,
# search, manage tags, and attach photos.

import json
import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import logger
from data_layer import timeline as _dl


# ---------------------------------------------------------------------------
# Post to Timeline
# ---------------------------------------------------------------------------

def post_to_timeline(
    body: str,
    author_id: str = "",
    title: str = "",
    tags: str = "",
    source_app: str = "",
    source_entity_id: str = "",
    source_label: str = "",
) -> str:
    """Create a new Timeline post (family journal / microblog entry).

    Args:
        body: The post content (markdown supported).
        author_id: Who is posting (e.g. "alice", "carol"). Required.
        title: Optional headline for the post.
        tags: Comma-separated tags (e.g. "vacation, family, bob").
        source_app: If auto-posted from another app (e.g. "auto", "recipes").
        source_entity_id: ID of the originating record if auto-posted.
        source_label: Human-readable description of the source.

    Returns:
        Confirmation with post ID and details.

    Ack: Posting to timeline...
    """
    try:
        if not body or not body.strip():
            return "Error: body is required."
        if not author_id or not author_id.strip():
            return "Error: author_id is required — who is posting?"

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        post = _dl.create_post(
            author_id=author_id.strip().lower(),
            body=body.strip(),
            title=title.strip() if title else "",
            tags=tag_list,
            source_app=source_app.strip() if source_app else "",
            source_entity_id=source_entity_id.strip() if source_entity_id else "",
            source_label=source_label.strip() if source_label else "",
        )

        tag_str = ", ".join(post.get("tags", [])) if post.get("tags") else "none"
        return (
            f"✅ Posted to Timeline: **{post['id']}**\n"
            f"Author: {post['author_id']}\n"
            f"Title: {post.get('title') or '(none)'}\n"
            f"Tags: {tag_str}\n"
            f"Created: {post['created_at'][:16]}"
        )
    except Exception as e:
        logger.error("TIMELINE: post_to_timeline failed: %s", e)
        return f"Error creating timeline post: {e}"


# ---------------------------------------------------------------------------
# List / Browse Feed
# ---------------------------------------------------------------------------

def list_timeline(
    tag: str = "",
    author: str = "",
    before: str = "",
    after: str = "",
    search: str = "",
    limit: str = "20",
    offset: str = "0",
) -> str:
    """Browse the Timeline feed — paginated, newest first.

    Args:
        tag: Filter to posts with this tag.
        author: Filter to posts by this author.
        before: Show posts before this ISO datetime.
        after: Show posts after this ISO datetime.
        search: Full-text search across titles and post bodies.
        limit: Max posts to return (default 20).
        offset: Pagination offset (default 0).

    Returns:
        Formatted list of timeline posts.

    Ack: Loading timeline...
    """
    try:
        lim = int(limit) if limit else 20
        off = int(offset) if offset else 0
        result = _dl.list_posts(
            tag=tag.strip().lower() if tag else None,
            author=author.strip().lower() if author else None,
            before=before.strip() if before else None,
            after=after.strip() if after else None,
            search=search.strip() if search else None,
            limit=min(lim, 50),
            offset=off,
            include_body=True,
        )

        posts = result["posts"]
        total = result["total"]
        has_more = result["has_more"]

        if not posts:
            return "No timeline posts found."

        lines = [f"**Timeline** — {total} total post{'s' if total != 1 else ''}\n"]
        for p in posts:
            pin = "📌 " if p.get("pinned") else ""
            src = f" (via {p['source_app']})" if p.get("source_app") else ""
            tag_str = " · ".join(f"#{t}" for t in (p.get("tags") or []))
            title_str = f"**{p['title']}** — " if p.get("title") else ""
            body_preview = (p.get("body") or "")[:150]
            if len(p.get("body", "")) > 150:
                body_preview += "…"
            photo_count = len(p.get("photos", []))
            photo_str = f" 📷×{photo_count}" if photo_count else ""

            lines.append(
                f"{pin}{p['id']} · {p['author_id']}{src} · {p['created_at'][:10]}\n"
                f"  {title_str}{body_preview}\n"
                f"  {tag_str}{photo_str}"
            )

        if has_more:
            lines.append(f"\n— Showing {len(posts)} of {total}. Use offset={off + lim} for more.")

        return "\n\n".join(lines)
    except Exception as e:
        logger.error("TIMELINE: list_timeline failed: %s", e)
        return f"Error listing timeline: {e}"


# ---------------------------------------------------------------------------
# Get Single Post
# ---------------------------------------------------------------------------

def get_timeline_post(post_id: str) -> str:
    """Get a single Timeline post with full content and photos.

    Args:
        post_id: The post ID (tp-*).

    Returns:
        Full post details.

    Ack: Loading post...
    """
    try:
        if not post_id or not post_id.strip():
            return "Error: post_id is required."

        post = _dl.get_post(post_id.strip())
        if not post:
            return f"Post {post_id} not found."

        tag_str = ", ".join(f"#{t}" for t in (post.get("tags") or [])) or "none"
        photo_count = len(post.get("photos", []))
        pin = "📌 Pinned\n" if post.get("pinned") else ""
        src = ""
        if post.get("source_app"):
            src = f"Source: {post['source_app']} — {post.get('source_label', '')}\n"

        return (
            f"**{post['id']}** — {post.get('title') or '(untitled)'}\n"
            f"{pin}"
            f"Author: {post['author_id']}\n"
            f"Tags: {tag_str}\n"
            f"{src}"
            f"Photos: {photo_count}\n"
            f"Created: {post['created_at'][:16]} · Updated: {post['updated_at'][:16]}\n\n"
            f"{post.get('body', '')}"
        )
    except Exception as e:
        logger.error("TIMELINE: get_timeline_post failed: %s", e)
        return f"Error getting post: {e}"


# ---------------------------------------------------------------------------
# Update Post
# ---------------------------------------------------------------------------

def update_timeline_post(
    post_id: str,
    title: str = "",
    body: str = "",
    tags: str = "",
) -> str:
    """Edit a Timeline post's title, body, or tags.

    Args:
        post_id: The post ID (tp-*).
        title: New title (pass empty to keep current; pass " " to clear).
        body: New body content (pass empty to keep current).
        tags: New comma-separated tags (pass empty to keep current).

    Returns:
        Updated post confirmation.

    Ack: Updating post...
    """
    try:
        if not post_id or not post_id.strip():
            return "Error: post_id is required."

        kwargs = {}
        if title:
            kwargs["title"] = title.strip() if title.strip() else ""
        if body:
            kwargs["body"] = body.strip()
        if tags:
            kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        if not kwargs:
            return "Nothing to update — provide title, body, or tags."

        updated = _dl.update_post(post_id.strip(), **kwargs)
        if not updated:
            return f"Post {post_id} not found."

        tag_str = ", ".join(f"#{t}" for t in (updated.get("tags") or []))
        return (
            f"✅ Updated {updated['id']}\n"
            f"Title: {updated.get('title') or '(none)'}\n"
            f"Tags: {tag_str or 'none'}"
        )
    except Exception as e:
        logger.error("TIMELINE: update_timeline_post failed: %s", e)
        return f"Error updating post: {e}"


# ---------------------------------------------------------------------------
# Delete Post
# ---------------------------------------------------------------------------

def delete_timeline_post(post_id: str) -> str:
    """Delete a Timeline post and its linked document.

    Args:
        post_id: The post ID (tp-*).

    Returns:
        Confirmation or error.

    Ack: Deleting post...
    """
    try:
        if not post_id or not post_id.strip():
            return "Error: post_id is required."

        ok = _dl.delete_post(post_id.strip())
        if ok:
            return f"✅ Deleted post {post_id} and its document."
        return f"Post {post_id} not found."
    except Exception as e:
        logger.error("TIMELINE: delete_timeline_post failed: %s", e)
        return f"Error deleting post: {e}"


# ---------------------------------------------------------------------------
# Search Timeline
# ---------------------------------------------------------------------------

def search_timeline(
    query: str,
    tag: str = "",
    limit: str = "20",
) -> str:
    """Full-text search across Timeline post titles and bodies.

    Args:
        query: Search text.
        tag: Optional tag filter to narrow results.
        limit: Max results (default 20).

    Returns:
        Matching posts.

    Ack: Searching timeline...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."

        result = _dl.list_posts(
            search=query.strip(),
            tag=tag.strip().lower() if tag else None,
            limit=min(int(limit) if limit else 20, 50),
        )
        posts = result["posts"]
        if not posts:
            return f"No posts found matching '{query}'."

        lines = [f"**Search results for '{query}'** — {result['total']} match{'es' if result['total'] != 1 else ''}\n"]
        for p in posts:
            tag_str = " · ".join(f"#{t}" for t in (p.get("tags") or []))
            body_preview = (p.get("body") or "")[:120]
            if len(p.get("body", "")) > 120:
                body_preview += "…"
            lines.append(
                f"{p['id']} · {p['author_id']} · {p['created_at'][:10]}\n"
                f"  {p.get('title') or '(untitled)'}: {body_preview}\n"
                f"  {tag_str}"
            )
        return "\n\n".join(lines)
    except Exception as e:
        logger.error("TIMELINE: search_timeline failed: %s", e)
        return f"Error searching timeline: {e}"


# ---------------------------------------------------------------------------
# Pin / Unpin
# ---------------------------------------------------------------------------

def pin_timeline_post(post_id: str) -> str:
    """Toggle pin status on a Timeline post (pinned posts stick to top of feed).

    Args:
        post_id: The post ID (tp-*).

    Returns:
        Updated pin status.

    Ack: Toggling pin...
    """
    try:
        if not post_id or not post_id.strip():
            return "Error: post_id is required."

        updated = _dl.toggle_pin(post_id.strip())
        if not updated:
            return f"Post {post_id} not found."

        status = "📌 Pinned" if updated["pinned"] else "Unpinned"
        return f"✅ {status}: {updated['id']} — {updated.get('title') or '(untitled)'}"
    except Exception as e:
        logger.error("TIMELINE: pin_timeline_post failed: %s", e)
        return f"Error toggling pin: {e}"


# ---------------------------------------------------------------------------
# Tag Index
# ---------------------------------------------------------------------------

def list_timeline_tags() -> str:
    """List all Timeline tags with post counts.

    Returns:
        Tag index with counts.

    Ack: Loading tags...
    """
    try:
        tags = _dl.list_tags()
        if not tags:
            return "No tags found — post some entries first!"

        lines = [f"**Timeline Tags** — {len(tags)} tags\n"]
        for t in tags:
            lines.append(f"  #{t['tag']} ({t['post_count']})")
        return "\n".join(lines)
    except Exception as e:
        logger.error("TIMELINE: list_timeline_tags failed: %s", e)
        return f"Error listing tags: {e}"


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

def add_timeline_photos(
    post_id: str,
    image_ids: str,
) -> str:
    """Attach photos to a Timeline post for the carousel.

    Args:
        post_id: The post ID (tp-*).
        image_ids: Comma-separated image IDs to attach.

    Returns:
        Confirmation with photo count.

    Ack: Adding photos...
    """
    try:
        if not post_id or not post_id.strip():
            return "Error: post_id is required."
        if not image_ids or not image_ids.strip():
            return "Error: image_ids is required."

        post = _dl.get_post(post_id.strip())
        if not post:
            return f"Post {post_id} not found."

        ids = [i.strip() for i in image_ids.split(",") if i.strip()]
        existing_count = len(post.get("photos", []))

        added = []
        for i, img_id in enumerate(ids):
            photo = _dl.add_photo(
                post_id=post_id.strip(),
                image_id=img_id,
                sort_order=existing_count + i,
            )
            added.append(photo["id"])

        return f"✅ Added {len(added)} photo(s) to {post_id}: {', '.join(added)}"
    except Exception as e:
        logger.error("TIMELINE: add_timeline_photos failed: %s", e)
        return f"Error adding photos: {e}"
