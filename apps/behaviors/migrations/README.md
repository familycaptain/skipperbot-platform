# Behaviors app migrations

Numbered SQL files. The platform loader runs each unrun migration
once and tracks application state in `public.app_migrations` (scope
`app_id='behaviors'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_behaviors` schema + the
  `behaviors` table + 3 btree indexes (`scope`, `created_by`,
  `enabled`).
- `002_migrate_from_public.sql` — one-shot data move from legacy
  `public.behaviors`. Idempotent (`ON CONFLICT (id) DO NOTHING`).
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_behaviors, public` so unqualified
  names refer to this app's schema, but `public.*` (users, entity
  types) is still readable.
- Single-table app, no within-app FKs. No cross-schema FKs allowed
  per the per-app schema isolation rule.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`.
- Every migration body is wrapped in `BEGIN; ... COMMIT;`.
- Migrations never delete user data without an explicit destructive
  flag — `002_migrate_from_public.sql` does NOT drop the source
  table.
