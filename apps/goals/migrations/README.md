# Goals app migrations

Numbered SQL or Python files. The platform loader runs each unrun
migration once and tracks application state in `public.app_migrations`
(scope `app_id='goals'`).

Files run in lexical filename order. `001_initial.sql` first.

- `001_initial.sql` — creates the `app_goals` schema + goals/projects/tasks tables. **Sub-chunk 3b.**
- `002_migrate_from_public.py` — one-shot data move from legacy `public.goals/projects/tasks`. **Sub-chunk 3d.**
- `003+` — additive schema changes as the app evolves.

## Rules (per `specs/APP_PACKAGES.md`)

- SQL runs with `search_path = app_goals, public` so unqualified table
  names refer to this app's schema, but `public.*` (memories, links,
  users, notifications) is still readable.
- No cross-schema foreign keys. References to other apps' tables must
  go through the platform service layer.
- Migrations are idempotent — `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, etc.
- Migrations never delete user data without an explicit destructive flag.
