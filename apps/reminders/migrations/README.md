# Reminders app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='reminders'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_reminders` schema + `reminders`
  table + 3 indexes. **Sub-chunk 7b.** Includes the columns added by
  the legacy migrations 018 (`sort_order`) and 024 (`schedule_id`) —
  the packaged app is squashed.
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.reminders` use private one-shot scripts (see
  `private/data_migrations/reminders/` in each operator's local
  checkout — outside the public repo).
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_reminders, public` so unqualified
  table names refer to this app's schema, but `public.*` (users) is
  still readable.
- No cross-schema foreign keys. `schedule_id` references
  `app_schedules.schedules.id` by string only.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ALTER TABLE ADD CONSTRAINT` wrapped in
  `DO` blocks catching `duplicate_object` / `invalid_table_definition`
  / `duplicate_table`.
- Every migration body is wrapped in an explicit `BEGIN; ... COMMIT;`
  block so `SET LOCAL search_path` actually scopes to the migration.
- Migrations never delete user data without an explicit destructive flag.
