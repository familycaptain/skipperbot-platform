# Backups

Protects your Skipper data — full database + project-files backups, on a
schedule, with optional off-site copies.

## Overview

Backups makes a complete snapshot of Skipper (a database dump, a zip of the
project files, and a `RESTORE.md` with recovery steps) and copies it to whatever
destinations you've enabled. It runs automatically on a daily schedule, and you
can also run one on demand. It keeps the most recent N runs and prunes older
ones. This is an operator/admin app — there's nothing to enter day to day.

## Setup & destinations

Configure in **Settings → Backups** (or the cog on the Backups tile). Two
destinations, each independently on/off:

- **Filesystem** — copy backups to a local or mounted path (great for a NAS/USB drive).
- **Google Drive** — upload to a Drive folder via a service account (needs
  credentials; see `docs/03-extended-functionality.md`).

Skipper boots fine with **neither** enabled (it still records the run); enable at
least one to actually keep copies off the machine. A master **enabled** toggle
gates the scheduled runs; the "Run backup now" button always works regardless.

## Screens

- **Backup history** — one row per run (running / completed / failed / skipped)
  with timestamps, so you can see whether last night's backup succeeded.
- **Run backup now** — force a one-off backup immediately.
- **Settings (cog)** — the destination toggles and paths/credentials above.

## Example workflows

**Check last night's backup**
- *In the app:* look at the history list (top row = most recent).
- *Through chat:* "did last night's backup run?"

**Run one right now**
- *In the app:* click **Run backup now**.
- *Through chat:* "run a backup now".

**Send backups to a drive / Google Drive**
- *In the app:* Settings → Backups → enable Filesystem (set the path) and/or
  Google Drive (add credentials).

## Tips

- If a daily backup fails (or none ran), the admin gets a notification.
- Each backup includes a `RESTORE.md` so future-you knows exactly how to recover.

## Your data

This app *is* your data protection. It records a **backup audit log** (one row
per run) **and surfaces it to Skipper's memory**, so you can ask "when did the
last backup succeed?" The backup artifacts themselves go to your chosen
destinations; credentials stay encrypted in Settings.
