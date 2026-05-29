# Timeline app migrations

Numbered SQL files. The platform loader runs each unrun migration once
and tracks application state in `public.app_migrations` (scope
`app_id='timeline'`).

- `001_initial.sql` — creates the `app_timeline` schema + three
  tables (`timeline_posts`, `timeline_photos`, `timeline_tag_index`)
  + indexes. Idempotent — older installs already on `app_timeline`
  (from a pre-public migration loop) see a no-op.
- No `002_migrate_from_public.sql` — these tables never lived in
  `public.*` on the public-release codebase, so there is nothing to
  copy from. Older private-codebase installs migrated this data
  through a separate path.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_timeline, public` so unqualified
  names refer to this app's schema.
- Within-app FKs are fine — `timeline_photos.post_id REFERENCES
  timeline_posts(id) ON DELETE CASCADE`. No cross-schema FKs.
- The platform's auto-activity log (`app_platform/activity.py`)
  writes directly into `app_timeline.timeline_posts` via
  `scoped_conn` to avoid a circular import on this app. Column
  adds / renames here must keep that path working.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ADD CONSTRAINT` wrapped in DO blocks
  catching `duplicate_object` / `invalid_table_definition` /
  `duplicate_table`.
- Every migration body is wrapped in `BEGIN; ... COMMIT;`.
