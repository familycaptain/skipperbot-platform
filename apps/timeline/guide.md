> **DEPRECATED** — Moved to `apps/timeline/guide.md` (app package).
> This file is no longer loaded. Safe to delete.

# Timeline Guide

## Overview
Family journal and microblog — post updates, share photos, tag events, and browse back through time.

## Available Tools
- `post_to_timeline(body, author_id, title?, tags?, ...)` — create a new post
- `list_timeline(tag?, author?, before?, after?, search?, limit?, offset?)` — paginated feed
- `search_timeline(query, tag?, limit?)` — full-text search across titles and bodies
- `get_timeline_post(post_id)` — single post with full content and photos
- `update_timeline_post(post_id, title?, body?, tags?)` — edit a post
- `delete_timeline_post(post_id)` — remove a post and its document
- `pin_timeline_post(post_id)` — toggle pin (pinned posts stick to top)
- `list_timeline_tags()` — tag index with counts
- `add_timeline_photos(post_id, image_ids)` — attach photos to a post

## Important Rules

1. **author_id is required** — always pass the current user's name (e.g. "alice", "carol").
2. **Tags are comma-separated** — e.g. "vacation, family, bob". They are auto-lowercased.
3. **Post bodies support markdown** — the body is stored as a document in the document system.
4. **Pinned posts** appear at the top of the feed. Toggle with pin_timeline_post.
5. **Cross-app posts** — when auto-posting from another app, set source_app, source_entity_id, and source_label so the post links back to the source.

## Natural Language Patterns

| User says | Action |
|-----------|--------|
| "post that we went to the zoo" | post_to_timeline(body="We went to the zoo today!", author_id=user, tags="family, zoo") |
| "what's on the timeline?" | list_timeline() |
| "show me posts tagged vacation" | list_timeline(tag="vacation") |
| "search timeline for pasta" | search_timeline(query="pasta") |
| "pin that post" | pin_timeline_post(post_id) |
| "show me all timeline tags" | list_timeline_tags() |
| "delete that timeline post" | delete_timeline_post(post_id) |
| "edit that post" | update_timeline_post(post_id, body="...") |
