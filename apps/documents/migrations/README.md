# Documents app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='documents'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_documents` schema + `documents`
  table + 2 indexes (GIN on tags + ivfflat on embedding).
  **Sub-chunk 10b.** Squashed from legacy migrations 001 (initial
  schema) and 061 (added `embedding vector(1536)` column + the
  ivfflat semantic-search index).
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.documents` use private one-shot scripts (see
  `private/data_migrations/documents/` in each operator's local
  checkout — outside the public repo).
- `003+` — additive schema changes as the app evolves.

## pgvector requirement

The `embedding` column uses the `vector(1536)` type from pgvector.
The migration assumes the `vector` extension has already been
created in the database (Docker installs do this automatically via
`deploy/docker-initdb/01-create-extensions.sql`; native installs
need to `CREATE EXTENSION vector` once as a superuser).

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_documents, public` so unqualified
  table names refer to this app's schema, but `public.*` (users) is
  still readable.
- `parent_doc_id` references another `documents.id` value as a
  plain `TEXT` — no FK. Document threading is enforced at the
  application layer.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ALTER TABLE ADD CONSTRAINT` wrapped
  in `DO` blocks catching `duplicate_object` /
  `invalid_table_definition` / `duplicate_table`.
- Every migration body is wrapped in an explicit `BEGIN; ... COMMIT;`
  block so `SET LOCAL search_path` actually scopes to the migration.
- Migrations never delete user data without an explicit destructive flag.
