# Folders app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='folders'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_folders` schema + all three
  tables (`folders`, `folder_items`, `folder_knowledge`) + 10
  indexes. **Sub-chunk 11b.** Squashed from legacy migrations 048
  (initial schema + GIN/ivfflat indexes) and 058 (soft-delete column
  + partial index).
- `002_migrate_from_public.sql` — one-shot data move from legacy
  `public.folders` / `folder_items` / `folder_knowledge`.
  **Sub-chunk 11d.** Handles older installs that pre-date the
  soft-delete column.
- `003+` — additive schema changes as the app evolves.

## pgvector requirement

The `folder_knowledge.embedding` column uses `vector(1536)` from
pgvector. Same setup as the Documents app: ensured automatically on
Docker installs via
`deploy/docker-initdb/01-create-extensions.sql`; native installs
need to `CREATE EXTENSION vector` once as a superuser.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_folders, public` so unqualified
  table names refer to this app's schema, but `public.*` (users,
  entity_types) is still readable.
- Within-app FKs are fine — `folders.parent_folder_id` is a
  self-FK with `ON DELETE SET NULL`; `folder_items.folder_id` and
  `folder_knowledge.folder_id` both `REFERENCES folders(id) ON DELETE
  CASCADE`.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ALTER TABLE ADD CONSTRAINT` wrapped
  in `DO` blocks catching `duplicate_object` /
  `invalid_table_definition` / `duplicate_table`.
- Every migration body is wrapped in an explicit `BEGIN; ... COMMIT;`
  block.
- Migrations never delete user data without an explicit destructive flag.
