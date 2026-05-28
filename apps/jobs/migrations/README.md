# Jobs app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='jobs'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_jobs` schema + `jobs` and
  `job_logs` tables + 4 indexes. **Sub-chunk 9b.** Squashed from four
  legacy migrations:
  - **001** — the original `jobs` table with a restrictive
    `job_type` CHECK
  - **009** — relaxed the `job_type` CHECK + added 9 columns
    (`progress_pct`, `schedule_expr`, `started_at`, `completed_at`,
    `claimed_by`, `max_retries`, `retry_count`, `parent_job_id`,
    `error`) + 3 indexes
  - **010** — created the `job_logs` table + 2 indexes
  - **063** — dropped the `schedule` column (recurrence is driven
    by the Schedules app)
- `002_migrate_from_public.sql` — one-shot data move from legacy
  `public.jobs` and `public.job_logs`. **Sub-chunk 9d.**
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_jobs, public` so unqualified
  table names refer to this app's schema, but `public.*` (users) is
  still readable.
- Within-app FKs are fine — `job_logs.job_id` is intentionally NOT
  a foreign key (the legacy schema didn't have one either; this
  lets us migrate logs even if some source jobs were dropped by
  hand).
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`,
  `ADD COLUMN IF NOT EXISTS`, `ALTER TABLE ADD CONSTRAINT` wrapped
  in `DO` blocks catching `duplicate_object` /
  `invalid_table_definition` / `duplicate_table`.
- Every migration body is wrapped in an explicit `BEGIN; ... COMMIT;`
  block so `SET LOCAL search_path` actually scopes to the migration.
- Migrations never delete user data without an explicit destructive flag.
