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
    from config import TIMEZONE
    return ZoneInfo(TIMEZONE)


def _tz_name() -> str:
    from config import TIMEZONE
    return TIMEZONE


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
    """Parse SKIPPERBOT_DB_DSN into components for pg_dump."""
    dsn = os.getenv("SKIPPERBOT_DB_DSN", "")
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

| File | Size |
|------|------|
| `skipperbot_db.dump` | {dump_size / 1048576:.1f} MB |
| `skipperbot_files.zip` | {zip_size / 1048576:.1f} MB |
| `RESTORE.md` | this file |

## Prerequisites

- **PostgreSQL 18.x** with **pgvector 0.8.x** extension
- **Python 3.14+**
- Access to the `.env` file (included in `skipperbot_files.zip`)

## Step 1: Restore the Database

```powershell
# Create the database (if needed)
$env:PGPASSWORD='<password>'
createdb -h localhost -U {dsn['user']} {dsn['dbname']}
psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Restore from backup (clean restore into existing DB)
$env:PGPASSWORD='<password>'
pg_restore -h localhost -U {dsn['user']} -d {dsn['dbname']} --clean --if-exists --no-owner --no-privileges skipperbot_db.dump
```

## Step 2: Restore Project Files

```powershell
Expand-Archive -Path skipperbot_files.zip -DestinationPath C:\\Users\\Alice\\repos\\skipperbot -Force
```

## Step 3: Verify `.env`

The `.env` file is included in the zip. Ensure it is in the project root directory with correct API keys.

## Step 4: Verify Restore

```powershell
$env:PGPASSWORD='<password>'
psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "SELECT count(*) FROM chat_turns;"
psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "SELECT count(*) FROM memories;"
psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

# Verify app schemas were restored
psql -h localhost -U {dsn['user']} -d {dsn['dbname']} -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'app\\_%';"
```

### Expected Table Counts

{counts_lines}

## Step 5: Start the Agent

```powershell
cd C:\\Users\\Alice\\repos\\skipperbot
python agent.py
```

## Notes

- The pgvector extension must be installed on the target PostgreSQL instance before restoring.
- Backups use `pg_dump -F c` custom format (compressed, supports selective restore).
- To restore only specific tables, use `pg_restore -l <dumpfile>` to list contents.
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

        # 9. Complete record
        duration = time.time() - start
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
