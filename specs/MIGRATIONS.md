# Skipperbot — Migrations

> **Placeholder.** Full content lands in Chunk 2+.

## Scope

Migration strategy across the platform and apps:

- `migrations/000_baseline.sql` — single baseline for platform infrastructure tables.
- Per-app migrations under `apps/<id>/migrations/`. The migrator runs them
  with `search_path = app_<id>, public` so app SQL can use unqualified
  table names and read platform tables.
- The `public.app_migrations(app_id, filename, applied_at)` tracking table.
- Forbidden patterns: no cross-schema foreign keys.
- `001_initial.sql` per app to set up its schema.
- `00X_migrate_from_public.py` per app for the legacy-data move during cutover.
- Migration ordering: required apps load first (declared via `core: true`),
  then optional apps in arbitrary order.
- How the loader handles a failed migration: log + `app_registry.status = 'error'`,
  the app is skipped, the platform keeps running unless the failed app is `core: true`.
- The schema-uninstall rule: removing an app folder does NOT drop its
  schema. `DROP SCHEMA app_<id> CASCADE` is the explicit purge.
- Migration testing: every `00X_migrate_from_public.py` must pass against a
  `pg_dump`-restored throwaway copy before running against real data.

The platform never seeds app-specific data. Each app seeds its own.
