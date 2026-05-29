# Prioritize app migrations

Numbered SQL files. The platform loader runs each unrun migration
once and tracks application state in `public.app_migrations` (scope
`app_id='prioritize'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_prioritize` schema +
  the `priority_focus` table + 4 indexes (PK on `id`, UNIQUE on
  `(user_id, slot_number)`, UNIQUE on `(user_id, source_id)`,
  btree on `user_id`).
- `002_migrate_from_public.sql` — one-shot data move from legacy
  `public.priority_focus`. Idempotent (`ON CONFLICT (id) DO NOTHING`).
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_prioritize, public` so unqualified
  names refer to this app's schema, but `public.*` (users, entity
  types) is still readable.
- No within-app FKs (single-table app). No cross-schema FKs allowed.
- Cross-schema reads (reminders, schedules, todo) are NOT done in SQL —
  they go through the platform shims at the Python layer.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, and DO blocks for ADD CONSTRAINT.
- Every migration body is wrapped in `BEGIN; ... COMMIT;`.
- Migrations never delete user data without an explicit destructive
  flag — `002` does NOT drop the source table.
