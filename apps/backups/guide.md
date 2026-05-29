# Backups — Tool Guide

> Backups is a system-facing app — there are no chat tools. Users
> interact with it through the UI ("Backups" launcher tile) or by
> letting the daily cron run.

## What this app owns

- The `app_backups.backups` audit table — one row per backup attempt
  (`running` / `completed` / `failed` / `skipped`).
- The backup runner that produces three artifacts per run:
  - `skipperbot_db_<date>.dump` — `pg_dump -F c` of the full DB.
  - `skipperbot_files_<date>.zip` — project tree (no `node_modules`,
    `.git`, `__pycache__`, `.venv`, `venv`, or existing `backups/`).
  - `RESTORE.md` — step-by-step recovery instructions including
    expected table counts.
- Pruning — older runs are deleted from each enabled destination and
  from the audit table at the end of every successful backup, keeping
  the most recent `retention` runs.

## Destinations

Two destinations are independently configurable from the manifest's
`config:` schema (cog wheel on the Backups launcher tile, or the
central Settings app):

| Setting                       | Purpose                                                          |
|-------------------------------|------------------------------------------------------------------|
| `filesystem_enabled` / `_path`| Copy artifacts to a local or mounted path.                       |
| `gdrive_enabled` / `_key_file` / `_impersonate_email` | Upload to a shared "Backups/<date>" Drive folder via a service account with domain-wide delegation. |

Each destination is opt-in. The platform must boot cleanly with **no
destinations enabled** — the runner still produces a DB audit row
and the dump/zip in staging, then deletes the staging dir; nothing
is persisted off-machine.

## Master switch

`enabled` gates scheduled cron runs only. On-demand backups (from
the "Run backup now" button in the UI) always execute so the user
can force a one-off artifact regardless of the daily-cron toggle.

## When the daily check fires

Every morning the `backup_check` job sweeps the audit table for the
day's `completed` row. If none is found — or the most-recent record
is `failed` — Alice gets a notification through
`app_platform.notifications`. A `skipped` row (master switch off) is
silent.
