# Timeline — App Spec

## Purpose
Family journal / microblog. Three tables:

- `app_timeline.timeline_posts` — one post per row. Body lives in the
  documents app via `doc_id` (NULLable — activity-log posts skip
  the document and store the title only).
- `app_timeline.timeline_photos` — carousel attachments keyed by
  `post_id`. ON DELETE CASCADE from posts.
- `app_timeline.timeline_tag_index` — denormalised `tag → post_count`
  for sidebars and tag clouds.

## Visibility

Every post carries a `visibility` field (defaults to `everyone`).
The auto-activity log writes with `visibility='personal'` so noisy
per-user CRUD events stay out of the shared feed by default.

## Public surface

### Tools (MCP)
- `post_to_timeline(body, author_id, title="", tags="", source_app="", source_entity_id="", source_label="")`
- `list_timeline(tag="", author="", before="", after="", search="", limit="20", offset="0")`
- `get_timeline_post(post_id)`
- `update_timeline_post(post_id, title="", body="", tags="")`
- `delete_timeline_post(post_id)`
- `search_timeline(query, tag="", limit="20")`
- `pin_timeline_post(post_id)`
- `list_timeline_tags()`
- `add_timeline_photos(post_id, image_ids)`

### Platform shim — `app_platform.timeline`
Re-exports the data layer. Cross-app callers (`app_platform/activity.py`
is the headline one) stay on the stable contract.

### REST endpoints (mounted under `/api/apps/timeline` by the loader)
- `GET    /`                              — feed (filters via query string)
- `GET    /tags`                          — tag index
- `GET    /authors`                       — distinct authors + counts
- `GET    /{post_id}`                     — single post
- `POST   /`                              — create post
- `PUT    /{post_id}`                     — edit post (title/body/tags)
- `PATCH  /{post_id}/pin`                 — toggle pin
- `DELETE /{post_id}`                     — delete post + linked doc + photos
- `POST   /{post_id}/photos`              — attach photos `{image_ids: [...]}`
- `DELETE /{post_id}/photos/{photo_id}`   — remove one photo
- `GET    /link-preview?url=...`          — Open Graph scrape for the
  composer's URL-preview cards

## Auto-activity write path
The platform's `app_platform/activity.py` calls `scoped_conn("app_timeline")`
and `INSERT`s directly into `timeline_posts` rather than going through
this app's data layer, intentionally avoiding a circular import. The
schema this app owns is the contract — column adds / drops here must
keep that path working.

## Migrations
- `001_initial.sql` — `app_timeline.timeline_posts` + `timeline_photos`
  (CASCADE) + `timeline_tag_index` + 7 indexes + the `visibility`
  column. Idempotent — older installs already running on
  `app_timeline` from a previous migration loop see a no-op.
- No `002_migrate_from_public.sql` — these tables never lived in
  `public.*` on the public-release codebase (the migration history
  jumped straight into `app_timeline`). Older private-codebase
  installs migrated this data separately.

## What this app does NOT own
- Post bodies — those are documents (the documents app owns CRUD).
- Image binaries — those are managed by the images upload/serve
  routes in agent.py.
