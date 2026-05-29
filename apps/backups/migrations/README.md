# Backups app migrations

Numbered SQL files. The platform loader runs each unrun migration
once and tracks application state in `public.app_migrations` (scope
`app_id='backups'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_backups` schema + the
  `backups` audit table + PK index. Single-table app, no FKs.
- `002_migrate_from_public.sql` — one-shot data move from legacy
  `public.backups`. Idempotent (`ON CONFLICT (id) DO NOTHING`).
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_backups, public` so unqualified
  names refer to this app's schema, but `public.*` (users,
  entity_types, `app_config`) is still readable.
- No within-app FKs and no cross-schema FKs allowed.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ADD CONSTRAINT` wrapped in `DO`
  blocks catching `duplicate_object` / `invalid_table_definition` /
  `duplicate_table`.
- Every migration body is wrapped in `BEGIN; ... COMMIT;`.
- Migrations never delete user data without an explicit destructive
  flag — `002` does NOT drop the source table.
