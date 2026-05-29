"""Timeline — FastAPI routes.

Mounted by the platform loader at ``/api/apps/timeline``. Backs the
TimelineApp UI directly.

Endpoints (relative to the prefix above)::

    GET    /                                — paginated feed
    GET    /tags                            — tag index
    GET    /authors                         — distinct authors + counts
    GET    /link-preview?url=...            — Open Graph scrape
    GET    /{post_id}                       — single post
    POST   /                                — create post
    PUT    /{post_id}                       — edit post (title/body/tags)
    PATCH  /{post_id}/pin                   — toggle pin
    DELETE /{post_id}                       — delete post + linked doc
    POST   /{post_id}/photos                — attach photos
    DELETE /{post_id}/photos/{photo_id}     — remove one photo
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import apps.timeline.data as _dl

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PostCreateRequest(BaseModel):
    title: str = ""
    body: str = ""
    tags: list[str] = []
    author_id: str = ""
    source_app: str = ""
    source_entity_id: str = ""
    source_label: str = ""
    visibility: str = "everyone"


class PostUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[list[str]] = None


class PhotosAddRequest(BaseModel):
    image_ids: list[str]


# ---------------------------------------------------------------------------
# Feed + indexes
# ---------------------------------------------------------------------------

@router.get("")
@router.get("/")
async def api_list_posts(
    tag: str = "",
    author: str = "",
    before: str = "",
    after: str = "",
    search: str = "",
    visibility: str = "",
    limit: int = 20,
    offset: int = 0,
    include_body: bool = True,
):
    """Paginated timeline feed, newest first.

    Filters are all optional. ``visibility`` defaults to "no filter"
    (returns both everyone-feed and personal posts) — UIs that want
    just the shared feed should pass ``visibility=everyone``.
    """
    def _do():
        return _dl.list_posts(
            tag=tag.strip().lower() or None,
            author=author.strip().lower() or None,
            before=before.strip() or None,
            after=after.strip() or None,
            search=search.strip() or None,
            visibility=visibility.strip() or None,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
            include_body=include_body,
        )
    return await asyncio.to_thread(_do)


@router.get("/tags")
async def api_list_tags():
    return {"tags": await asyncio.to_thread(_dl.list_tags)}


@router.get("/authors")
async def api_list_authors():
    return {"authors": await asyncio.to_thread(_dl.list_authors)}


# ---------------------------------------------------------------------------
# Link preview (Open Graph scrape)
# ---------------------------------------------------------------------------

_OG_RE = re.compile(
    r'<meta[^>]+property=["\']og:(?P<key>title|description|image)["\'][^>]+content=["\'](?P<val>[^"\']+)["\']',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(?P<val>.*?)</title>", re.IGNORECASE | re.DOTALL)


@router.get("/link-preview")
async def api_link_preview(url: str):
    """Best-effort Open Graph scrape used by the post composer's URL
    preview cards. Returns ``{title, description, image}`` (any of
    which may be empty).

    Network errors return an empty dict rather than a 5xx so the JSX
    composer can just skip the preview.
    """
    if not url or not url.strip():
        return {}

    def _scrape() -> dict:
        try:
            parsed = urllib.parse.urlparse(url.strip())
            if parsed.scheme not in ("http", "https"):
                return {}
            req = urllib.request.Request(
                url.strip(),
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Skipperbot-Timeline/1.0)",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — UI-driven HTTP
                ctype = (resp.headers.get("content-type") or "").lower()
                if "text/html" not in ctype:
                    return {}
                # Read at most 256 KB to avoid pulling huge pages
                body = resp.read(262_144).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug("link-preview fetch failed for %s: %s", url, exc)
            return {}

        result = {"title": "", "description": "", "image": ""}
        for m in _OG_RE.finditer(body):
            key = m.group("key").lower()
            val = html.unescape(m.group("val").strip())
            if key in result and not result[key]:
                result[key] = val
        if not result["title"]:
            tm = _TITLE_RE.search(body)
            if tm:
                result["title"] = html.unescape(tm.group("val").strip())[:200]
        return result

    return await asyncio.to_thread(_scrape)


# ---------------------------------------------------------------------------
# Single post CRUD
# ---------------------------------------------------------------------------

@router.get("/{post_id}")
async def api_get_post(post_id: str):
    post = await asyncio.to_thread(_dl.get_post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("")
@router.post("/")
async def api_create_post(req: PostCreateRequest):
    if not (req.body or "").strip():
        raise HTTPException(status_code=400, detail="body is required")
    if not (req.author_id or "").strip():
        raise HTTPException(status_code=400, detail="author_id is required")

    def _do():
        return _dl.create_post(
            author_id=req.author_id.strip().lower(),
            body=req.body.strip(),
            title=(req.title or "").strip(),
            tags=req.tags or [],
            source_app=(req.source_app or "").strip(),
            source_entity_id=(req.source_entity_id or "").strip(),
            source_label=(req.source_label or "").strip(),
            visibility=(req.visibility or "everyone").strip() or "everyone",
        )
    return await asyncio.to_thread(_do)


@router.put("/{post_id}")
async def api_update_post(post_id: str, req: PostUpdateRequest):
    def _do():
        return _dl.update_post(
            post_id,
            title=req.title,
            body=req.body,
            tags=req.tags,
        )
    updated = await asyncio.to_thread(_do)
    if not updated:
        raise HTTPException(status_code=404, detail="Post not found")
    return updated


@router.patch("/{post_id}/pin")
async def api_toggle_pin(post_id: str):
    updated = await asyncio.to_thread(_dl.toggle_pin, post_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Post not found")
    return updated


@router.delete("/{post_id}")
async def api_delete_post(post_id: str):
    ok = await asyncio.to_thread(_dl.delete_post, post_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"ok": True, "message": f"Post {post_id} deleted"}


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

@router.post("/{post_id}/photos")
async def api_add_photos(post_id: str, req: PhotosAddRequest):
    def _do():
        post = _dl.get_post(post_id)
        if not post:
            return None
        existing = len(post.get("photos", []))
        added: list[dict] = []
        for i, img_id in enumerate(req.image_ids):
            img_id = (img_id or "").strip()
            if not img_id:
                continue
            added.append(_dl.add_photo(post_id, img_id, sort_order=existing + i))
        return added
    result = await asyncio.to_thread(_do)
    if result is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"added": result, "count": len(result)}


@router.delete("/{post_id}/photos/{photo_id}")
async def api_remove_photo(post_id: str, photo_id: str):
    # post_id is part of the URL for symmetry but the photo_id is enough
    # to identify the row (PK on its own).
    ok = await asyncio.to_thread(_dl.remove_photo, photo_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"ok": True}
