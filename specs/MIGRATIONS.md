# Skipperbot — Migrations

How the platform builds its database and how each app builds its own. There are
two layers, and they never mix: a **single platform baseline** for the shared
`public` schema, and **per-app migrations** that each live inside an isolated
`app_<id>` schema.

This spec is the operational companion to
[`APP_PACKAGES.md` → *Migration Strategy: Forward-Only per Schema*](APP_PACKAGES.md#migration-strategy-forward-only-per-schema).
Read that section for the "why"; this one covers the "what runs, in what order,
and what happens when it breaks."

---

## The two layers

| Layer | Lives in | Schema | Tracked in | Run by |
|-------|----------|--------|-----------|--------|
| Platform baseline | `migrations/000_baseline.sql` | `public` | `public.platform_migrations` | `scripts/init_db.py` |
| Per-app | `apps/<id>/migrations/*.sql` | `app_<id>` | `public.app_migrations` | `app_platform/migrator.py` (at boot, and via `init_db.py`) |

Everything lives in **one Postgres database**. The platform's infrastructure
tables stay in `public`; each app's tables live in its own `app_<id>` schema
(e.g. `app_goals.goals`, `app_lists.lists`). The two layers are deployed by
different code paths and tracked in different tables.

---

## Layer 1 — the platform baseline

`migrations/000_baseline.sql` is the **single** baseline for the shared `public`
schema. It replaces the long series of historical numbered migrations from
pre-public development with one idempotent file, generated from a
`pg_dump --schema-only` of a known-good database (with app-owned tables filtered
out).

It contains **only platform-infrastructure** tables — never app-owned data.
App tables (goals, lists, schedules, reminders, …) are created by each app's own
migrations when the app loads. The baseline seeds:

- the platform-owned tables in `public`: `app_registry`, `app_migrations`,
  `app_events` / `app_event_deliveries`, `app_config`, `entity_types`,
  `thinking_domains` / `thinking_log`, `skipper_state`, `users`,
  `service_tokens`, `memories`, `links`, `knowledge_*`, `jobs`, `notifications`,
  and friends;
- a set of platform-owned `entity_type` rows (the generic single-letter
  prefixes for artifacts, chat logs, images, jobs, memories, …);
- the platform-level `thinking_domains` rows;
- the default `scope='platform'` `app_config` values (timezone, model names,
  nag windows, `onboarding_complete=false`, …).

Every statement in the baseline is idempotent — `CREATE TABLE IF NOT EXISTS`,
indexes with `IF NOT EXISTS`, and `ADD CONSTRAINT` wrapped in `DO $$ … $$` blocks
that swallow `duplicate_object` / `duplicate_table`. Re-running it against an
already-baselined database is a no-op.

### Two tables the baseline creates that the migrator then uses

```
public.app_registry            -- one row per installed app (status, version, manifest)
  app_id   TEXT PRIMARY KEY
  status   TEXT   -- 'active' | 'disabled' | 'error' | 'uninstalled'
  ...

public.app_migrations          -- one row per applied per-app migration file
  app_id      TEXT   -- FK → app_registry(app_id) ON DELETE CASCADE
  filename    TEXT
  applied_at  TIMESTAMPTZ
  checksum    TEXT
  PRIMARY KEY (app_id, filename)
```

`app_migrations.app_id` has a foreign key onto `app_registry(app_id)`, so an app
must be registered in `app_registry` **before** its first migration runs. The
loader and `init_db.py` both honour this ordering.

### pgvector is a prerequisite, not part of the baseline

The baseline uses `public.vector(1536)` columns and `ivfflat` indexes, so the
`vector` extension must already exist in the target database. The baseline does
**not** run `CREATE EXTENSION vector` because installing an extension is a
superuser action and the app's DB role (e.g. `skipperbot_user`) usually can't.
Provisioning the extension is the job of `scripts/bootstrap_db.py` (superuser
path) and is documented in `docs/01-base-platform-setup.md`.

---

## Layer 2 — per-app migrations

Each app that owns data ships a `migrations/` directory:

```
apps/<id>/migrations/
  README.md          # describes the files (per-app convention)
  001_initial.sql    # creates app_<id> schema + the app's tables
  002_*.sql          # additive changes / seeds as the app evolves
  003_*.sql
  ...
```

Files run in **lexical filename order** (`001_…` before `002_…`). The convention
is a zero-padded numeric prefix; `001_initial.sql` is always first and creates
the schema and the app's core tables.

### How the migrator runs them

`app_platform/migrator.py` is the per-app schema migrator. For one app it:

1. **Ensures the schema** — `CREATE SCHEMA IF NOT EXISTS app_<id>`
   (`ensure_schema`).
2. **Reads the applied set** — `SELECT filename FROM app_migrations WHERE
   app_id = %s` (`get_applied_migrations`).
3. **Collects pending files** — every `*.sql` in the directory, sorted, that
   isn't already in the applied set.
4. **Applies each file in order.** Before executing, it sets
   `SET search_path TO app_<id>, public`, so the migration SQL can use
   unqualified table names (which resolve into the app's schema) while still
   reading `public.*` tables. After the file succeeds it records the run with
   `INSERT INTO app_migrations (app_id, filename, checksum) … ON CONFLICT DO
   NOTHING`, storing the file's SHA-256.

The SQL file itself is executed in **autocommit** mode so that the file's own
`BEGIN; … COMMIT;` block owns atomicity. Every `001_initial.sql` ships such a
block (belt-and-suspenders for the run-by-hand case), and running it under
psycopg2's implicit transaction would otherwise nest two transactions and emit
spurious warnings. Recording the `app_migrations` row happens in a separate
follow-up transaction. Because all DDL is idempotent (see below), a crash
between "file applied" and "row inserted" is safe: the next run re-applies the
file as a no-op and inserts the row.

### What a migration file looks like

Every app migration is **idempotent** and wraps its body in an explicit
transaction so the `search_path` change actually scopes to it:

```sql
-- apps/<id>/migrations/001_initial.sql
BEGIN;

CREATE SCHEMA IF NOT EXISTS app_<id>;
SET LOCAL search_path TO app_<id>, public;

CREATE TABLE IF NOT EXISTS things (
    id    text NOT NULL,
    name  text NOT NULL,
    ...
);

DO $$ BEGIN
    ALTER TABLE things ADD CONSTRAINT things_pkey PRIMARY KEY (id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_table_definition THEN NULL;
    WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_things_name ON things (name);

COMMIT;
```

The `CREATE SCHEMA` + `SET LOCAL search_path` + `BEGIN/COMMIT` at the top are
defensive: the migrator already sets the schema and the search path, but
including them means the same file also applies cleanly when run by hand:

```
psql -d skipperbot -f apps/<id>/migrations/001_initial.sql
```

Idempotency rules every app follows:

- `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`.
- `ALTER TABLE … ADD CONSTRAINT` wrapped in `DO` blocks catching
  `duplicate_object` / `invalid_table_definition` / `duplicate_table`.
- Seed inserts use `ON CONFLICT … DO NOTHING` (or `DO UPDATE` for re-runnable
  config).
- Migrations never delete user data without an explicit destructive flag.

### Forbidden: cross-schema foreign keys

An app's tables may **only** reference each other. They must never create a
foreign key pointing into another schema (another app or `public`), and the
platform must never create an FK pointing into an app schema. Cross-entity
references are stored as plain `text` IDs and validated at the application
layer, or expressed through the platform `links` table — not as DB constraints.
(Example from the shipped apps: Todo's `backlog_list_id` references a list by
string only, never by FK.)

This keeps each schema fully independent and makes `DROP SCHEMA app_<id>
RESTRICT` safe. The migrator enforces it: after running an app's migrations,
`validate_no_cross_schema_fks(app_id)` queries `information_schema` for any FK
crossing the schema boundary **in either direction** and the loader **raises**
(failing the app's load) if it finds one.

### `.sql` vs `.py` files in `migrations/`

The migrator runs **`.sql` files only** — `run_app_migrations` globs
`f.suffix == ".sql"`. A handful of apps also keep numbered `.py` files in their
`migrations/` directory (e.g. `003_seed_*.py`). These are **not** part of the
tracked, auto-applied migration chain:

- They are standalone, hand-run seed/backfill scripts (they import
  `data_layer.db.get_conn`, do their work, and commit).
- They are **not** recorded in `public.app_migrations` and the migrator never
  picks them up.
- They are idempotent (typically `ON CONFLICT DO UPDATE`) so an operator can
  run them safely once after the schema migrations land.

If a change must be part of the automatic, tracked chain, write it as `.sql`.

---

## Migration ordering at boot

App discovery (`app_platform/manifest.discover_apps`) walks `apps/` in sorted
directory order, and `load_all_apps` loads each app through the same lifecycle:
register in `app_registry` → ensure schema → run migrations → validate FKs →
register entity types → load tools/routes/handlers.

The platform distinguishes **required (core)** apps from optional ones:

- **Required (core) apps** ship inside the platform repo and set `core: true`
  in their manifest. The loader holds an explicit `REQUIRED_APPS` list (Goals,
  Lists, Todo, Schedules, Reminders, Notifications, Documents, Folders, Jobs,
  System, Issues, …) and, **after** loading everything, calls
  `require_apps(*REQUIRED_APPS)`. If any required app is missing or loaded with
  `status='error'`, boot **aborts loudly** with the exact app(s) to fix rather
  than degrading silently.
- **Optional apps** load in the same pass; if one fails it is marked
  `error` and skipped, and the platform keeps running.

> Note on ordering: discovery is alphabetical by directory name, not topologically
> sorted by core-ness. Apps don't depend on each other's schemas (cross-schema FKs
> are forbidden), so load order between apps doesn't matter for correctness — the
> only hard guarantee is that the **set** of required apps must all be present and
> `active` by the end of the load, which `require_apps(...)` enforces.

---

## Failed-migration handling

A migration runs inside the app file's own transaction. On failure the migrator
rolls back, logs `MIGRATOR: <app> — FAILED <file>: <err>`, and raises
`RuntimeError`. The loader catches that during `_load_app` and:

- marks the app `status='error'` in `app_registry` (with the error message);
- does **not** load the app's tools, routes, handlers, or thinking domain.

The app can be fixed and retried — re-running re-applies only the still-pending
files (anything already in `app_migrations` is skipped). If the failed app is a
**required (core)** app, `require_apps(...)` then aborts the whole boot, because
the platform refuses to run in a partially-broken core state. If it's optional,
the rest of the platform runs normally and the broken app simply stays `error`.

`scripts/init_db.py` follows the same contract for first-run/CI initialization:
a failed app migration exits non-zero (exit code 3) so the failure is visible.

---

## Uninstall and purge

Removing an app's folder does **not** drop its schema. Schema removal is always
an explicit, separate action — data safety is the default.

`app_platform/migrator.drop_app_schema(app_id, purge=...)`:

- `purge=False` (default) — only cleans the app's rows out of
  `public.app_migrations`. The `app_<id>` schema and all its data are left in
  place.
- `purge=True` — runs `DROP SCHEMA IF EXISTS app_<id> RESTRICT`, then clears the
  app's `app_migrations` rows.

The drop uses **`RESTRICT`, not `CASCADE`**: Postgres refuses the drop if
anything outside the schema still depends on it. Because cross-schema FKs are
forbidden, a clean app has no such external dependencies and the drop succeeds;
if the drop is refused, that's a signal that an illegal cross-schema dependency
exists and must be resolved first. Core apps cannot be uninstalled at all —
`uninstall_app` rejects any `app_id` in `REQUIRED_APPS`.

---

## First-run / bootstrap order

A fresh install builds the database in this order:

1. **`scripts/bootstrap_db.py`** (superuser, run once on a new server) — creates
   the app role and database, and installs the `vector` extension. Exits
   non-zero if pgvector isn't available on the server.
2. **`scripts/init_db.py`** (the app role; idempotent, safe to re-run, also run
   by the Docker/systemd entrypoints every start):
   1. loads the DSN from `.env` and connects;
   2. verifies the `vector` extension is present (warns if a non-superuser role
      can't install it);
   3. runs `migrations/000_baseline.sql` **exactly once**, tracked by a row in
      `public.platform_migrations` (platform-scoped — distinct from the
      app-scoped `public.app_migrations` that the baseline itself creates);
   4. walks `apps/<id>/migrations/` for every bundled app and applies each
      unrun `.sql` file **through the same `app_platform.migrator` code path the
      agent uses at boot** — registering each app in `app_registry` first (to
      satisfy the `app_migrations` FK), ensuring its schema, then running its
      pending migrations;
   5. seeds the `skipper` bot user.

After that, the running agent's loader re-runs the per-app migrator on every
boot, so any new migration files added by an app upgrade are picked up
automatically.

---

## Fresh installs vs. legacy cutover (operator note)

In the **public repo**, a fresh install is exactly the two layers above:
`000_baseline.sql` builds `public`, and each app's `001_initial.sql` builds its
`app_<id>` schema. There is nothing else to run — the apps start empty and seed
their own data.

Operators upgrading from an old pre-packaging deployment (where app data lived
in the `public` schema, e.g. `public.goals`, `public.lists`) need a one-time
copy of that legacy data into the new `app_<id>` schemas. Those one-shot cutover
scripts are **not shipped in the public repo** — they live in each operator's
local `private/data_migrations/<app>/` area (gitignored), as the per-app
`apps/<id>/migrations/README.md` files note. They are an operator concern, not
part of the standard install path, and a clean public install never touches
them.

---

The platform never seeds app-specific data. Each app seeds its own, through its
own migrations.
