# Backups — App Spec

## Purpose
Database + project-files backup runner with **independently
toggleable destinations**. The platform must boot cleanly when
neither destination is enabled — the runner still writes an audit
row and produces staging artifacts, but nothing is persisted
off-machine.

## Data model
`app_backups.backups` — single table, no FKs.

| Column          | Type        | Notes                                            |
|-----------------|-------------|--------------------------------------------------|
| `id`            | text PK     | `b-XXXXXXXX`                                     |
| `job_id`        | text        | nullable — the submitting job ID                 |
| `started_at`    | timestamptz | now() default                                    |
| `completed_at`  | timestamptz | nullable                                         |
| `status`        | text        | `running` / `completed` / `failed` / `skipped`   |
| `pg_dump_size`  | bigint      | nullable                                         |
| `zip_size`      | bigint      | nullable                                         |
| `network_path`  | text        | nullable — the filesystem destination path       |
| `files_created` | jsonb       | `[]` default — list of artifact destinations     |
| `table_counts`  | jsonb       | `{}` default — row counts captured for manifest  |
| `duration_secs` | real        | nullable                                         |
| `error`         | text        | empty string default                             |
| `created_by`    | text        | `system` default                                 |

One btree PK index. No FKs (single-table app, schema-isolated).

## Configuration
All toggles live in `scope='app:backups'` (manifest schema):

| Key                          | Default     | Purpose                                            |
|------------------------------|-------------|----------------------------------------------------|
| `enabled`                    | `true`      | Master switch for the cron. On-demand ignores it. |
| `cron`                       | `0 2 * * *` | 5-field cron in platform timezone.                 |
| `retention`                  | `5`         | Keep N recent runs per destination + in DB.        |
| `filesystem_enabled`         | `false`     | Toggle the filesystem destination.                 |
| `filesystem_path`            | `""`        | Absolute path to copy into.                        |
| `gdrive_enabled`             | `false`     | Toggle the Google Drive destination.               |
| `gdrive_key_file`            | `""`        | Service account JSON key path.                     |
| `gdrive_impersonate_email`   | `""`        | Workspace email to impersonate.                    |

On first boot the loader seeds defaults via `app_platform.config`.
The runner reads exclusively from `app_platform.config.get(...)`;
the legacy `BACKUP_*` env vars have been retired.

## Public surface

### Platform shim — `app_platform.backups`
Stable cross-app contract.

- `create_backup(...)`, `complete_backup(...)`, `skip_backup(...)`,
  `fail_backup(...)`, `get_backup(...)`, `list_backups(...)`,
  `delete_backup(...)`, `prune_old_records(...)`
- `run_backup(job, ctx)` — the backup job handler (sync, runs in
  thread pool).
- `run_backup_check(job, ctx)` — the daily verification handler.

### REST endpoints
Live in `agent.py` under `/api/apps/backups/*` so the existing
`BackupsApp.jsx` keeps working without a URL migration. The config
endpoints (`GET /config`, `PATCH /enabled`) read/write the
``app_platform.config`` store instead of the legacy `.env` rewrite.

### Job handlers (registered in `apps/backups/handlers.py`)
- `backup` — runs the full backup pipeline.
- `backup_check` — verifies the daily run.

## Cross-app reads
- Notifications go through `app_platform.notifications.create_notification`.
- Job submission stays on `app_platform.jobs.submit_job`.
- DB record helpers expose `app_platform.backups.*` for everyone else
  (system app's "Run backup now" UI, the runner's progress hooks).

## Destination dispatch

The runner asks `app_platform.config` for each destination:

1. **filesystem** — if `filesystem_enabled` and `filesystem_path` is a
   real directory, copy + verify size + prune older dated folders.
2. **gdrive** — if `gdrive_enabled` and both key file and impersonate
   email are set, build the Drive client and upload to
   `Backups/<date>/` (creating the date folder if needed) + prune
   older date folders.

If a destination is enabled but misconfigured (e.g.
`gdrive_enabled=true` but no key file), the runner logs a warning,
records a `files_created` entry tagged with the failure, and keeps
going — one bad destination must not poison the whole run.

If **no destinations are enabled**, the runner still writes the
audit row + creates staging artifacts. It logs a warning that this
was a dry-run-ish state and returns `completed` with an empty
`files_created` list.

## Migrations
- `001_initial.sql` — `app_backups.backups` + PK index.
- No `002` migration — fresh installs use only
  `001_initial.sql`. Pre-packaging installs that need to copy data
  out of `public.backups` use private one-shot scripts (see
  `private/data_migrations/backups/` in each operator's local
  checkout — outside the public repo).

## What this app does NOT own
- The cron registration itself — the platform's schedules/jobs
  layer provides the dispatcher. This app declares the schedule
  cadence via `config.cron`.
- The notification channel — `app_platform.notifications`
  resolves the channel.
