"""Backups — runner.

Two job handlers:

- ``run_backup(job, ctx)`` — produces ``pg_dump``, project zip, and
  ``RESTORE.md`` in a staging directory, then dispatches to each
  *enabled* destination. The whole-app master switch + each
  per-destination toggle are read from ``app_platform.config``
  (scope ``app:backups``). Synchronous — runs in the job
  dispatcher's thread pool.
- ``run_backup_check(job, ctx)`` — sweeps the audit table for
  today's run and notifies Alice if it's missing or failed.

If the master switch is off, scheduled jobs short-circuit
``skipped``; on-demand jobs (``config.on_demand=True``) ignore the
switch so the UI can force a one-off run.

If neither destination is enabled, the runner still writes an audit
row and produces staging artifacts, then deletes the staging
directory — useful for testing the dump path without a destination
in place. The returned summary makes it explicit.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app_platform import config as platform_config
from apps.backups.data import (
    create_backup,
    complete_backup,
    fail_backup,
    skip_backup,
    prune_old_records,
    list_today,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

def _base_dir() -> str:
    """The project root (one level above this app's package)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _staging_dir() -> str:
    return os.path.join(_base_dir(), "backups", "staging")


def _timezone() -> ZoneInfo:
    from app_platform.time import get_timezone
    return get_timezone()


def _tz_name() -> str:
    from app_platform.time import get_timezone
    return get_timezone().key


ZIP_EXCLUDES = {
    "backups",
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
}

# Tables to count for the manifest (best-effort — unknown tables are
# silently skipped).
COUNT_TABLES = [
    "chat_turns", "memories", "users", "goals_entities", "goals_notes",
    "lists", "list_items", "reminders", "documents", "notifications",
    "entity_links", "jobs", "job_logs", "investment_snapshots",
    "knowledge_sources", "knowledge_chunks", "trello_item_history",
    "auto_vehicles", "auto_service_records", "located_items",
    "item_locations", "recipes", "app_config", "backups",
]


def _new_id() -> str:
    return f"b-{uuid.uuid4().hex[:8]}"


def _parse_dsn() -> dict:
    """Parse the effective DSN into components for pg_dump.

    Uses the same resolver as the rest of the platform, so it works whether
    the operator set a full SKIPPERBOT_DB_DSN or just POSTGRES_PASSWORD.
    """
    from data_layer.dsn import resolve_dsn
    dsn = resolve_dsn()
    parts = {}
    for token in dsn.split():
        if "=" in token:
            k, v = token.split("=", 1)
            parts[k.strip()] = v.strip()
    return {
        "host": parts.get("host", "localhost"),
        "user": parts.get("user", "postgres"),
        "password": parts.get("password", ""),
        "dbname": parts.get("dbname", "skipperbot"),
        "port": parts.get("port", "5432"),
    }


def _cfg(key: str, default=None):
    return platform_config.get(key, default, scope="app:backups")


# ---------------------------------------------------------------------------
# Per-stage helpers
# ---------------------------------------------------------------------------

def _get_table_counts() -> dict:
    """Get row counts for key public tables + all app-schema tables."""
    from data_layer.db import fetch_one, fetch_all
    counts = {}
    for table in COUNT_TABLES:
        try:
            row = fetch_one(f"SELECT COUNT(*) as cnt FROM {table}")
            counts[table] = row["cnt"] if row else 0
        except Exception:
            counts[table] = -1
    try:
        app_tables = fetch_all(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema LIKE 'app\\_%' AND table_type = 'BASE TABLE' "
            "ORDER BY table_schema, table_name"
        )
        for row in app_tables:
            qualified = f"{row['table_schema']}.{row['table_name']}"
            try:
                r = fetch_one(f"SELECT COUNT(*) as cnt FROM {qualified}")
                counts[qualified] = r["cnt"] if r else 0
            except Exception:
                counts[qualified] = -1
    except Exception:
        pass
    return counts


def _run_pg_dump(staging: str, date_str: str) -> tuple[str, int]:
    """Run pg_dump and return (filepath, size_bytes)."""
    dsn = _parse_dsn()
    dump_file = os.path.join(staging, f"skipperbot_db_{date_str}.dump")

    env = os.environ.copy()
    env["PGPASSWORD"] = dsn["password"]

    cmd = [
        "pg_dump",
        "-h", dsn["host"],
        "-p", dsn["port"],
        "-U", dsn["user"],
        "-d", dsn["dbname"],
        "-F", "c",
        "-f", dump_file,
    ]

    logger.info("BACKUP: Running pg_dump → %s", dump_file)
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed (rc={result.returncode}): {result.stderr[:500]}")

    size = os.path.getsize(dump_file)
    logger.info("BACKUP: pg_dump complete — %.1f MB", size / 1048576)
    return dump_file, size


def _create_project_zip(staging: str, date_str: str) -> tuple[str, int]:
    """Zip the project folder, excluding certain dirs."""
    zip_file = os.path.join(staging, f"skipperbot_files_{date_str}.zip")
    base = Path(_base_dir())

    logger.info("BACKUP: Creating project zip → %s", zip_file)
    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ZIP_EXCLUDES]
            for f in files:
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, base)
                try:
                    zf.write(full, arcname)
                except (PermissionError, OSError) as e:
                    logger.warning("BACKUP: Skipping file %s: %s", arcname, e)

    size = os.path.getsize(zip_file)
    logger.info("BACKUP: Project zip complete — %.1f MB", size / 1048576)
    return zip_file, size


def _generate_restore_md(
    staging: str,
    date_str: str,
    dump_size: int,
    zip_size: int,
    table_counts: dict,
) -> str:
    """Generate RESTORE.md with recovery instructions."""
    dsn = _parse_dsn()
    hostname = socket.gethostname()
    restore_file = os.path.join(staging, "RESTORE.md")
    tz = _timezone()

    counts_lines = "\n".join(
        f"  - `{t}`: {c}" for t, c in sorted(table_counts.items()) if c >= 0
    )

    content = f"""# SkipperBot Backup — Restore Instructions

**Backup date:** {date_str}
**Source machine:** {hostname}
**Generated:** {datetime.now(tz).strftime('%Y-%m-%d %H:%M %Z')}

## Files in This Backup

| File | Size | Contents |
|------|------|----------|
| `skipperbot_db.dump` | {dump_size / 1048576:.1f} MB | PostgreSQL dump (`pg_dump -F c`) |
| `skipperbot_files.zip` | {zip_size / 1048576:.1f} MB | Project files: `.env`, `uploads/`, `tmp/`, code |
| `RESTORE.md` | this file | these instructions |

## Choose your restore path — the two models are DIFFERENT

Restore the way the instance runs:

- **A. Docker** (the default/recommended install). Data lives in Docker **named
  volumes** (`skipper-db`, `skipper-uploads`), NOT in the project folder. The DB
  and uploaded files must be restored *into the running stack* — unzipping the
  archive over the repo will NOT work for them, because the `skipper-uploads`
  volume shadows the repo's `uploads/` folder.
- **B. Native** (PostgreSQL/Python/Node installed directly on the host). Data
  lives in the project folder, so a plain unzip puts files in place.

Commands note **Windows** vs **macOS/Linux** where they differ. The database
password is `POSTGRES_PASSWORD` in the `.env` (inside `skipperbot_files.zip`).

---

## A. Docker restore (recommended)

**Prerequisites:** Docker Engine + Docker Compose. PostgreSQL 18 + pgvector,
Python, and Node are bundled in the images — you do not install them.

### A1 — Get the code and your `.env`
```
git clone <your-repo-url> skipperbot-platform
cd skipperbot-platform
```
Extract just `.env` from the archive into the project root:
- macOS/Linux: `unzip -j skipperbot_files.zip .env -d .`
- Windows (PowerShell): `Expand-Archive skipperbot_files.zip _z; Move-Item _z\\.env .; Remove-Item -Recurse _z`

### A2 — Bring up the stack (creates the volumes + database)
```
skipper            # choose D (Docker); let it come up once
```

### A3 — Restore the database into the `db` container (OS-agnostic)
```
docker compose cp skipperbot_db.dump db:/tmp/skipperbot_db.dump
docker compose exec db pg_restore -U {dsn['user']} -d {dsn['dbname']} --clean --if-exists --no-owner --no-privileges /tmp/skipperbot_db.dump
```
(The in-container local socket connection is trusted, so no password is needed.)

### A4 — Restore uploaded files INTO the uploads volume (not onto the repo)
Uploads live in the `skipper-uploads` named volume, which **shadows** the repo's
`uploads/` folder — so they must be copied into the running container:
- macOS/Linux:
  ```
  mkdir -p _restore && unzip -q skipperbot_files.zip 'uploads/*' -d _restore
  docker compose cp _restore/uploads/. agent:/app/uploads/
  ```
- Windows (PowerShell):
  ```
  Expand-Archive skipperbot_files.zip _restore -Force
  docker compose cp _restore/uploads/. agent:/app/uploads/
  ```

### A5 — (Optional) Restore `tmp/` debug files
`tmp/` is bind-mounted (part of the repo), so it extracts into the project root —
no `docker cp` needed:
- macOS/Linux: `unzip -qo skipperbot_files.zip 'tmp/*' -d .`
- Windows (PowerShell): `Expand-Archive skipperbot_files.zip _restore -Force; Move-Item _restore\\tmp .`

### A6 — Restart, then verify
```
skipper restart
```
Delete the temporary `_restore/` folder, then run the **Verify** section below.

---

## B. Native restore

**Prerequisites:** PostgreSQL **18.x** + **pgvector 0.8.x**, Python **3.12**,
Node **24+** (the launcher installs the project's own Python/Node deps for you).

### B1 — Code and files
```
git clone <your-repo-url> skipperbot-platform
cd skipperbot-platform
```
Native reads files straight from the project folder, so unzip the **whole**
archive over the repo (`.env`, `uploads/`, `tmp/` all land in place):
- macOS/Linux: `unzip -o skipperbot_files.zip -d .`
- Windows (PowerShell): `Expand-Archive skipperbot_files.zip -DestinationPath . -Force`

### B2 — Create the database, extension, and restore
Set the password first:
- macOS/Linux: `export PGPASSWORD='<POSTGRES_PASSWORD from .env>'`
- Windows (PowerShell): `$env:PGPASSWORD='<POSTGRES_PASSWORD from .env>'`
```
createdb -h localhost -U {dsn['user']} {dsn['dbname']}
psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "CREATE EXTENSION IF NOT EXISTS vector;"
pg_restore -h localhost -U {dsn['user']} -d {dsn['dbname']} --clean --if-exists --no-owner --no-privileges skipperbot_db.dump
```

### B3 — Start
```
skipper            # choose N (Native) — installs deps on first run
```

---

## Verify (either path)

Run these against the restored DB. **Docker:** prefix each with
`docker compose exec db `. **Native:** `psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "..."`.

```
SELECT count(*) FROM chat_turns;
SELECT count(*) FROM memories;
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'app\\_%';
```

### Expected table counts (at backup time)

{counts_lines}

Then confirm uploaded images render in the UI. (Docker: check the volume is
populated — `docker compose exec agent du -sh /app/uploads`.)

## Notes

- **WARNING — never `docker compose down -v`.** The `-v` flag deletes the named
  volumes, which on this stack means **your uploads AND your entire database**.
  Use `docker compose down` (no `-v`), `skipper stop`, or `skipper restart`; a
  plain `down`/`up` keeps the volumes.
- Compose **prefixes volume names with the project**, so the uploads volume is
  `skipperbot-platform_skipper-uploads` (not `skipper-uploads`) when you
  `docker volume inspect`/`ls` it.
- **Docker keeps data in named volumes** (`skipper-db`, `skipper-uploads`), NOT in
  the repo — that is why the DB and uploads are restored *into the stack*
  (`pg_restore` / `docker compose cp`), not by unzipping over the project folder.
  `tmp/` is the exception: it is bind-mounted, so it extracts normally.
- `skipperbot_files.zip` contains your **`.env`, which holds secrets** — keep the
  backup location private.
- Backups use `pg_dump -F c` (compressed custom format). `pg_restore -l <dump>`
  lists contents for a selective restore.
- pgvector must be available before restoring (Docker: bundled; Native: install
  PostgreSQL 18 + the `pgvector` extension first).
"""

    with open(restore_file, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("BACKUP: RESTORE.md generated")
    return restore_file


# ---------------------------------------------------------------------------
# Destination dispatchers (each independently configurable)
# ---------------------------------------------------------------------------

def _copy_to_filesystem(
    date_str: str,
    dump_file: str,
    zip_file: str,
    restore_file: str,
) -> dict:
    """Copy artifacts to the filesystem destination if enabled.

    Returns one of::

        {"status": "skipped", "reason": "..."}
        {"status": "ok", "path": "...", "files": [...]}
        {"status": "error", "reason": "..."}
    """
    if not _cfg("filesystem_enabled", False):
        return {"status": "skipped", "reason": "filesystem destination disabled"}

    base = (_cfg("filesystem_path", "") or "").strip()
    if not base:
        return {"status": "skipped", "reason": "filesystem_path empty"}

    try:
        os.makedirs(base, exist_ok=True)
    except Exception as e:
        return {"status": "error", "reason": f"could not create {base}: {e}"}

    folder = os.path.join(base, date_str)
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        return {"status": "error", "reason": f"could not create {folder}: {e}"}

    try:
        files_created = []
        for src, dest_name in [
            (dump_file, "skipperbot_db.dump"),
            (zip_file, "skipperbot_files.zip"),
            (restore_file, "RESTORE.md"),
        ]:
            dest = os.path.join(folder, dest_name)
            shutil.copy2(src, dest)
            src_size = os.path.getsize(src)
            dest_size = os.path.getsize(dest)
            if src_size != dest_size:
                raise RuntimeError(
                    f"verification failed for {dest_name}: src={src_size} dest={dest_size}"
                )
            files_created.append(dest)
            logger.info("BACKUP: filesystem copied %s (%d bytes)", dest_name, dest_size)
        return {"status": "ok", "path": folder, "files": files_created}
    except Exception as e:
        logger.error("BACKUP: filesystem destination failed: %s", e)
        return {"status": "error", "reason": str(e)[:500]}


def _prune_filesystem(retention: int) -> int:
    """Remove old dated folders from the filesystem destination beyond retention."""
    if not _cfg("filesystem_enabled", False):
        return 0
    base = (_cfg("filesystem_path", "") or "").strip()
    if not base or not os.path.isdir(base):
        return 0

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    folders = sorted(
        [d for d in os.listdir(base) if date_pattern.match(d) and
         os.path.isdir(os.path.join(base, d))],
        reverse=True,
    )

    if len(folders) <= retention:
        return 0

    removed = 0
    for folder_name in folders[retention:]:
        folder_path = os.path.join(base, folder_name)
        try:
            shutil.rmtree(folder_path)
            logger.info("BACKUP: filesystem pruned %s", folder_name)
            removed += 1
        except Exception as e:
            logger.error("BACKUP: filesystem prune failed for %s: %s", folder_name, e)
    return removed


# ---------------------------------------------------------------------------
# Top-level job handlers
# ---------------------------------------------------------------------------

def _backup_status(fs_result: dict, gdrive_result: dict) -> tuple[str, str]:
    """Decide a run's recorded status from the per-destination results (ev-86).

    Returns ``(status, reason)`` where status is one of
    ``'completed'`` / ``'failed'`` / ``'skipped'``:
      (i)   >=1 destination 'ok'          -> 'completed' (Success)
      (ii)  else >=1 destination 'error'  -> 'failed' (a configured destination
            that failed is NOT a Success; reason names the failing destination(s))
      (iii) else (all 'skipped'/none on)  -> 'skipped' with the no-destination reason
    So no run that stored nothing off-machine ever reads as Success — for EVERY
    caller (UI button, cron, scripted POST, cross-app).
    """
    dests = [("filesystem", fs_result), ("Google Drive", gdrive_result)]
    if any(r.get("status") == "ok" for _, r in dests):
        return ("completed", "")
    errors = [(name, r) for name, r in dests if r.get("status") == "error"]
    if errors:
        reason = "; ".join(f"{name}: {r.get('reason', '')[:200]}" for name, r in errors)
        return ("failed", f"Backup produced artifacts but no destination stored them — {reason}")
    return (
        "skipped",
        "No backup destination configured — nothing was copied off-machine. "
        "Configure a destination in Settings → Backups.",
    )


def run_backup(job: dict, ctx) -> str:
    """Main backup handler — called by the job dispatcher.

    Synchronous — runs in thread pool.
    """
    backup_id = _new_id()
    job_id = job.get("id", "")
    is_on_demand = job.get("config", {}).get("on_demand", False)
    start = time.time()
    date_str = datetime.now(_timezone()).strftime("%Y-%m-%d")

    create_backup(backup_id, job_id=job_id, created_by=job.get("created_by", "system"))

    # Master switch (on-demand bypasses it)
    if not is_on_demand and not _cfg("enabled", True):
        skip_backup(backup_id, reason="Backups disabled in app:backups config")
        logger.info("BACKUP: Skipped — enabled=false")
        return "Backups disabled, skipping"

    staging = _staging_dir()
    try:
        if os.path.exists(staging):
            shutil.rmtree(staging)
        os.makedirs(staging, exist_ok=True)

        # 1. pg_dump
        ctx.update_progress(5, "Running pg_dump...")
        dump_file, dump_size = _run_pg_dump(staging, date_str)
        ctx.update_progress(25, f"pg_dump complete ({dump_size / 1048576:.1f} MB)")

        # 2. Project zip
        ctx.update_progress(30, "Creating project archive...")
        zip_file, zip_size = _create_project_zip(staging, date_str)
        ctx.update_progress(55, f"Archive complete ({zip_size / 1048576:.1f} MB)")

        # 3. Table counts
        ctx.update_progress(60, "Collecting table counts...")
        table_counts = _get_table_counts()

        # 4. RESTORE.md
        ctx.update_progress(65, "Generating restore instructions...")
        restore_file = _generate_restore_md(
            staging, date_str, dump_size, zip_size, table_counts,
        )

        retention = int(_cfg("retention", 5) or 5)

        # 5. Filesystem destination (optional)
        ctx.update_progress(70, "Copying to filesystem destination...")
        fs_result = _copy_to_filesystem(date_str, dump_file, zip_file, restore_file)
        if fs_result["status"] == "ok":
            ctx.update_progress(78, f"Filesystem: {fs_result['path']}")
        elif fs_result["status"] == "skipped":
            ctx.update_progress(78, "Filesystem destination skipped")
        else:
            ctx.update_progress(78, f"Filesystem failed: {fs_result.get('reason','')[:80]}")

        # 6. Google Drive destination (optional)
        ctx.update_progress(82, "Uploading to Google Drive destination...")
        from apps.backups.gdrive import upload_to_gdrive
        gdrive_result = upload_to_gdrive(
            date_str, dump_file, zip_file, restore_file, retention=retention,
        )
        if gdrive_result["status"] == "ok":
            ctx.update_progress(90, "Google Drive upload complete")
        elif gdrive_result["status"] == "skipped":
            ctx.update_progress(90, "Google Drive destination skipped")
        else:
            ctx.update_progress(90, f"Google Drive failed: {gdrive_result.get('reason','')[:80]}")

        # 7. Prune
        ctx.update_progress(92, "Pruning old backups...")
        pruned_fs = _prune_filesystem(retention)
        pruned_db = prune_old_records(keep=retention)
        if pruned_fs or pruned_db:
            logger.info("BACKUP: Pruned %d filesystem + %d DB records", pruned_fs, pruned_db)

        # 8. Aggregate files_created from each destination so the audit
        # row records exactly where artifacts ended up.
        files_created: list = []
        if fs_result["status"] == "ok":
            files_created.extend(fs_result.get("files", []))
        if gdrive_result["status"] == "ok":
            for f in gdrive_result.get("files", []):
                files_created.append(f"gdrive:{f['name']}")

        # 9. Record status as an explicit function of the DESTINATION results, so a
        # run that persisted nothing off-machine NEVER reads as Success (ev-86).
        duration = time.time() - start
        status, reason = _backup_status(fs_result, gdrive_result)
        if status == "completed":
            network_path = fs_result.get("path", "") if fs_result["status"] == "ok" else ""
            complete_backup(
                backup_id,
                pg_dump_size=dump_size,
                zip_size=zip_size,
                network_path=network_path,
                files_created=files_created,
                table_counts=table_counts,
                duration_secs=round(duration, 1),
            )
        elif status == "failed":
            fail_backup(backup_id, error=reason)
        else:
            skip_backup(backup_id, reason=reason)
        ctx.update_progress(100, "Backup complete")

        summary = (
            f"Backup complete: {dump_size / 1048576:.1f} MB dump + "
            f"{zip_size / 1048576:.1f} MB zip"
        )
        dest_bits = []
        if fs_result["status"] == "ok":
            dest_bits.append(f"filesystem→{fs_result['path']}")
        elif fs_result["status"] == "error":
            dest_bits.append(f"filesystem-FAIL({fs_result.get('reason','')[:40]})")
        if gdrive_result["status"] == "ok":
            dest_bits.append(f"gdrive×{len(gdrive_result.get('files', []))}")
        elif gdrive_result["status"] == "error":
            dest_bits.append(f"gdrive-FAIL({gdrive_result.get('reason','')[:40]})")
        if not dest_bits:
            dest_bits.append("no destinations enabled — artifacts produced in staging only")
        summary += " → " + ", ".join(dest_bits) + f" ({duration:.0f}s)"
        logger.info("BACKUP: %s", summary)
        return summary

    except Exception as e:
        duration = time.time() - start
        error_str = str(e)[:2000]
        fail_backup(backup_id, error=error_str)
        logger.error("BACKUP: Failed after %.0fs — %s", duration, error_str)
        raise

    finally:
        if os.path.exists(staging):
            try:
                shutil.rmtree(staging)
            except Exception as e:
                logger.warning("BACKUP: Failed to clean staging: %s", e)


def run_backup_check(job: dict, ctx) -> str:
    """Daily verification — notify Alice if today's backup is missing or failed."""
    from app_platform.notifications import create_notification

    ctx.update_progress(20, "Querying today's backup records...")
    rows = list_today(_tz_name())
    ctx.update_progress(60, f"Found {len(rows)} backup record(s) for today")

    if not rows:
        create_notification(
            recipient="alice",
            message="Backup did not run today. No backup record found (expected at 2:00 AM CT).",
            source_type="backup_check",
            source_id="",
            channel="both",
            delivered=False,
        )
        logger.warning("BACKUP_CHECK: No backup record found for today — notification sent")
        return "No backup found for today — notification sent"

    completed = [r for r in rows if r["status"] == "completed"]
    if completed:
        ctx.update_progress(100, "Backup completed successfully")
        logger.info("BACKUP_CHECK: Today's backup OK (%s)", completed[0]["id"])
        return f"Backup OK: {completed[0]['id']}"

    latest = rows[0]
    status = latest["status"]
    error = (latest.get("error") or "").strip()

    if status == "failed":
        msg = "Backup failed today."
        if error:
            msg += f" Error: {error[:300]}"
        create_notification(
            recipient="alice",
            message=msg,
            source_type="backup_check",
            source_id=latest["id"],
            channel="both",
            delivered=False,
        )
        logger.warning("BACKUP_CHECK: Backup failed — notification sent (%s)", latest["id"])
        return "Backup failed — notification sent"

    if status == "skipped":
        logger.info("BACKUP_CHECK: Backup was skipped (disabled) — no notification")
        return "Backup skipped (disabled) — no notification sent"

    if status == "running":
        logger.info("BACKUP_CHECK: Backup still running at check time (%s) — no notification", latest["id"])
        return f"Backup still running ({latest['id']}) — no action taken"

    return f"Backup status: {status}"
