# Setting Up Backups

This guide walks you through turning on Skipper's backups and sending them
somewhere safe — a local drive or **Google Drive**.

> **Optional, but recommended.** Skipper boots and runs fine with **no
> backups configured** — it just records that a run happened and keeps nothing
> off the machine. Enable at least one *destination* below to actually keep
> copies of your data. Budget about 5 minutes for a filesystem destination, or
> ~15 minutes for Google Drive.

## What a backup contains

Each run produces three files (in a dated folder per run):

| File | What it is |
|------|------------|
| `skipperbot_db.dump` | A full PostgreSQL dump of your database (`pg_dump -F c`). |
| `skipperbot_files.zip` | Your project files — **including `.env`, which holds your secrets** — plus `uploads/`. |
| `RESTORE.md` | Step-by-step recovery instructions, generated fresh each run with the expected table counts. |

Because the archive contains your `.env`, **treat every backup as secret** —
keep whatever destination you choose private. To recover from a backup later,
follow the `RESTORE.md` included alongside it (it's always current with that
dump); you don't need this page for restores.

## Quick start

Everything is configured in **Settings → Backups** (or click the cog on the
**Backups** tile on your home screen). There's nothing to put in `.env`.

1. Open **Settings → Backups**.
2. Leave **Run scheduled backups** on (it runs nightly by default).
3. Enable a destination — **Filesystem** and/or **Google Drive** (below).
4. Click **Run backup now** in the Backups app to make one immediately.
5. Check **Backup history** — the top row should read **completed**.

That's it. The rest of this page covers the schedule and each destination in
detail.

## The basics: schedule, retention, master switch

In **Settings → Backups**:

- **Run scheduled backups** (`enabled`) — the master switch for the nightly
  run. Turning it off stops the *scheduled* backup; the **Run backup now**
  button still works regardless, so you can always force a one-off.
- **Backup schedule** (`cron`) — a standard 5-field cron expression in your
  platform timezone. Default `0 2 * * *` (2:00 AM nightly).
- **Retain last N backups** (`retention`) — how many recent runs to keep on
  each destination (older ones are pruned automatically). Default `5`.

If a nightly backup fails — or none ran — the admin gets a notification, so you
don't have to babysit it.

## Destination A — Filesystem

Copy each backup to a local folder, a mounted network share (NAS/SMB), or an
external drive.

1. In **Settings → Backups**, enable **Copy to a filesystem path**
   (`filesystem_enabled`).
2. Set **Filesystem path** (`filesystem_path`) to an absolute path Skipper can
   write to:
   - **Linux:** `/mnt/backups`
   - **macOS:** `/Volumes/Backups`
   - **Windows:** `Z:\backups`
3. Save. The path is created if it doesn't exist.

**Verify:** click **Run backup now**, then look in that folder — you should see
a dated subfolder (e.g. `2026-06-15/`) containing the three files above.

## Destination B — Google Drive

Upload each backup into a `Backups/<date>` folder on Google Drive. This uses a
**service account** with **domain-wide delegation** that acts *as* one of your
users, so the files land in that user's Drive and count against their quota.

> **You need Google Workspace.** Domain-wide delegation is a Workspace-only
> feature — a personal **@gmail.com** account *cannot* use this destination.
> If you're on consumer Gmail, use the **Filesystem** destination instead (point
> it at a folder that syncs to Drive via the Google Drive desktop app).

### B1 — Create a service account and key

1. In the [Google Cloud console](https://console.cloud.google.com/), pick (or
   create) a project and **enable the Google Drive API**.
2. Create a **service account**. You don't need to grant it any project roles.
3. Create a **JSON key** for it and download the file. **This file is a live
   credential** — treat it like a password.

### B2 — Grant it domain-wide delegation

1. Note the service account's **Client ID** (a long number on its details page).
2. In the **Google Workspace Admin** console → **Security → Access and data
   control → API controls → Domain-wide delegation**, add the Client ID with the
   OAuth scope `https://www.googleapis.com/auth/drive`.

This lets the service account impersonate a chosen user in your Workspace.

### B3 — Create and share the `Backups` folder

1. Sign in as the user the backups should live under (the one you'll
   *impersonate*) and create a folder named **exactly `Backups`** in their Drive.
   The name match is case-sensitive — `backups` or `Backup` won't be found.
2. (If you created it as someone else, share that folder with the impersonated
   user so it's in their Drive.) Keep the folder private — it holds your
   secrets.

### B4 — Enter the credentials in Settings

1. In **Settings → Backups**, enable **Upload to Google Drive**
   (`gdrive_enabled`).
2. Paste the entire contents of the downloaded JSON key into **Google Drive
   service-account JSON** (`gdrive_service_account_json`). This field is a
   **secret** — Skipper stores it **encrypted**; it never goes in `.env` or git.
3. Set **Workspace email to impersonate** (`gdrive_impersonate_email`) to the
   user whose Drive owns the `Backups` folder from B3.
4. Save, then **delete the downloaded JSON key file** from your computer — it
   now lives (encrypted) in Skipper.

### B5 — Verify

Click **Run backup now**, then open the impersonated user's Drive. You should
see `Backups/<today's date>/` with the three files in it.

### Troubleshooting

Google Drive uploads **fail quietly** (the rest of the backup still runs and the
history row can still say completed) — so check the Drive folder and the app
logs if files don't appear:

- **Nothing uploaded / "skipped":** the toggle is off, or the JSON / impersonate
  email field is empty. Re-check **Settings → Backups**.
- **"`Backups` folder not found":** the folder doesn't exist in the *impersonated
  user's* Drive, or the name isn't exactly `Backups` (case-sensitive).
- **Auth / permission errors:** domain-wide delegation isn't set up for the
  Client ID + the `drive` scope, or you're using a personal Gmail account (not
  supported).

## See also

- The `RESTORE.md` inside any backup — how to recover from it.
- [Extended functionality](03-extended-functionality.md) — other optional
  integrations.
