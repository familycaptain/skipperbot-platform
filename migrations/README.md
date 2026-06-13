# Platform (public-schema) migrations

These are migrations for the **platform** itself — the shared `public` schema
(users, memory, scheduling, chat logs, service tokens, etc.). They are distinct
from **per-app** migrations, which live in `apps/<id>/migrations/` and are
tracked in `public.app_migrations`.

## How they run

`scripts/init_db.py` (invoked by the Docker/systemd entrypoint on **every**
start, and by the onboarding wizard) applies every `*.sql` file here in
alphabetical order, skipping any already recorded in
`public.platform_migrations`. So:

- `000_baseline.sql` is just the first file. Existing installs already have it
  recorded and skip it.
- New files (`001_*.sql`, `002_*.sql`, …) are applied automatically on the next
  start/upgrade — this is how a platform schema change reaches existing
  installations.

## Authoring rules

1. **Number monotonically**: `001_short_description.sql`, `002_…`. Order is
   lexicographic, so zero-pad.
2. **No `BEGIN`/`COMMIT` inside the file.** The runner wraps each file in a
   single transaction, so the whole file is atomic. (This differs from per-app
   `001_initial.sql` files, which ship their own transaction for the run-by-hand
   case.)
3. **Make DDL idempotent**: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD
   COLUMN IF NOT EXISTS`, `ADD CONSTRAINT` inside a `DO` block that catches
   `duplicate_object`. The runner records the file only after the SQL succeeds,
   so a crash between the two re-applies the file as a no-op next start.
4. **Public schema only.** App-owned tables belong in that app's
   `migrations/`, not here.

## Note on new tables

Several platform tables are created lazily at first use via an
`ensure_schema()` / `CREATE TABLE IF NOT EXISTS` helper rather than a migration
file. That's fine for purely additive new tables. Use a migration file here when
you need to **alter** an existing platform table, change constraints/indexes, or
backfill data — those cannot be expressed as create-if-not-exists.
