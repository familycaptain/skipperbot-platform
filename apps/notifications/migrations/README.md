# Notifications app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='notifications'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_notifications` schema + `notifications` table + indexes. **Sub-chunk 6b.**
- `002_migrate_from_public.sql` — one-shot data move from legacy `public.notifications`. **Sub-chunk 6d.**
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_notifications, public` so unqualified
  table names refer to this app's schema, but `public.*` (users,
  mobile_devices) is still readable.
- No cross-schema foreign keys.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ALTER TABLE ADD CONSTRAINT` wrapped in `DO` blocks catching `duplicate_object` / `invalid_table_definition` / `duplicate_table`.
- Every migration body is wrapped in an explicit `BEGIN; ... COMMIT;`
  block so `SET LOCAL search_path` actually scopes to the migration.
- Migrations never delete user data without an explicit destructive flag.
