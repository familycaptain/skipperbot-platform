# Schedules app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='schedules'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_schedules` schema + `schedules`
  and `schedule_completions` tables + 7 indexes. **Sub-chunk 8b.**
  Squashed from legacy migrations 023 (the original schema) and 065
  (which widened the `recurrence_type` CHECK to include `'rrule'` —
  already present in the squashed initial).
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.schedules` + `public.schedule_completions` use
  private one-shot scripts (see `private/data_migrations/schedules/`
  in each operator's local checkout — outside the public repo).
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_schedules, public` so unqualified
  table names refer to this app's schema, but `public.*` (users,
  links) is still readable.
- Within-app foreign keys are fine — `schedule_completions.schedule_id`
  REFERENCES `schedules(id) ON DELETE CASCADE`. Cross-schema FKs are
  forbidden; Reminders' `schedule_id` references `schedules.id` by
  value only.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ALTER TABLE ADD CONSTRAINT` wrapped in
  `DO` blocks catching `duplicate_object` / `invalid_table_definition`
  / `duplicate_table`.
- Every migration body is wrapped in an explicit `BEGIN; ... COMMIT;`
  block so `SET LOCAL search_path` actually scopes to the migration.
- Migrations never delete user data without an explicit destructive flag.
