# Behaviors app migrations

Numbered SQL files. The platform loader runs each unrun migration
once and tracks application state in `public.app_migrations` (scope
`app_id='behaviors'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_behaviors` schema + the
  `behaviors` table + 3 btree indexes (`scope`, `created_by`,
  `enabled`).
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.behaviors` use private one-shot scripts (see
  `private/data_migrations/behaviors/` in each operator's local
  checkout — outside the public repo).
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
  flag.
