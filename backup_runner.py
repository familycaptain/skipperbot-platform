"""Backup Runner — pg_dump + project zip + RESTORE.md + network copy.

Designed to run as a synchronous job handler via the job dispatcher
(runs in thread pool). Each run creates a backup record in the DB
and produces three artifacts copied to a network drive.
"""

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

from config import logger, BASE_DIR, TIMEZONE

CENTRAL_TZ = ZoneInfo(TIMEZONE)

# Directories
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
STAGING_DIR = os.path.join(BACKUPS_DIR, "staging")

# Folders/patterns to exclude from the project zip
ZIP_EXCLUDES = {
    "backups",
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
}

# Tables to count for the manifest
COUNT_TABLES = [
    "chat_turns", "memories", "users", "goals_entities", "goals_notes",
    "lists", "list_items", "reminders", "documents", "notifications",
    "entity_links", "jobs", "job_logs", "investment_snapshots",
    "knowledge_sources", "knowledge_chunks", "trello_item_history",
    "auto_vehicles", "auto_service_records", "located_items",
    "item_locations", "recipes", "app_config", "backups",
]


def _new_id():
    return f"b-{uuid.uuid4().hex[:8]}"


def _parse_dsn():
    """Parse SKIPPERBOT_DB_DSN into components."""
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


def _get_table_counts() -> dict:
    """Get row counts for key public tables + all app-schema tables."""
    from data_layer.db import fetch_one, fetch_all
    counts = {}
    # Public schema tables
    for table in COUNT_TABLES:
        try:
            row = fetch_one(f"SELECT COUNT(*) as cnt FROM {table}")
            counts[table] = row["cnt"] if row else 0
        except Exception:
            counts[table] = -1
    # App-schema tables (app_* schemas created by the app platform)
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
        pass  # No app schemas yet
    return counts


def _run_pg_dump(staging: str, date_str: str, ctx) -> tuple[str, int]:
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


def _create_project_zip(staging: str, date_str: str, ctx) -> tuple[str, int]:
    """Zip the project folder, excluding certain dirs."""
    zip_file = os.path.join(staging, f"skipperbot_files_{date_str}.zip")
    base = Path(BASE_DIR)

    logger.info("BACKUP: Creating project zip → %s", zip_file)
    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(base):
            # Prune excluded directories in-place
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

    counts_lines = "\n".join(
        f"  - `{t}`: {c}" for t, c in sorted(table_counts.items()) if c >= 0
    )

    content = f"""# SkipperBot Backup — Restore Instructions

**Backup date:** {date_str}
**Source machine:** {hostname}
**Generated:** {datetime.now(CENTRAL_TZ).strftime('%Y-%m-%d %H:%M %Z')}

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
# Unzip project files to the desired location
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


def _copy_to_network(
    staging: str,
    date_str: str,
    dump_file: str,
    zip_file: str,
    restore_file: str,
) -> tuple[str, list[str]]:
    """Copy backup artifacts to the network drive. Returns (network_folder, files_list)."""
    network_base = os.getenv("BACKUP_NETWORK_PATH", "").strip()
    if not network_base:
        logger.warning("BACKUP: BACKUP_NETWORK_PATH not set — skipping network copy")
        return "", [dump_file, zip_file, restore_file]

    network_folder = os.path.join(network_base, date_str)
    os.makedirs(network_folder, exist_ok=True)

    files_created = []
    for src, dest_name in [
        (dump_file, "skipperbot_db.dump"),
        (zip_file, "skipperbot_files.zip"),
        (restore_file, "RESTORE.md"),
    ]:
        dest = os.path.join(network_folder, dest_name)
        shutil.copy2(src, dest)
        # Verify copy
        src_size = os.path.getsize(src)
        dest_size = os.path.getsize(dest)
        if src_size != dest_size:
            raise RuntimeError(
                f"Network copy verification failed for {dest_name}: "
                f"src={src_size} dest={dest_size}"
            )
        files_created.append(dest)
        logger.info("BACKUP: Copied %s → %s (%d bytes)", dest_name, dest, dest_size)

    return network_folder, files_created


def _prune_network_backups(keep: int = 5) -> int:
    """Remove old backup folders from the network drive beyond retention."""
    network_base = os.getenv("BACKUP_NETWORK_PATH", "").strip()
    if not network_base or not os.path.isdir(network_base):
        return 0

    # List dated folders (YYYY-MM-DD pattern)
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    folders = sorted(
        [d for d in os.listdir(network_base) if date_pattern.match(d) and
         os.path.isdir(os.path.join(network_base, d))],
        reverse=True,
    )

    if len(folders) <= keep:
        return 0

    removed = 0
    for folder_name in folders[keep:]:
        folder_path = os.path.join(network_base, folder_name)
        try:
            shutil.rmtree(folder_path)
            logger.info("BACKUP: Pruned old backup %s", folder_name)
            removed += 1
        except Exception as e:
            logger.error("BACKUP: Failed to prune %s: %s", folder_name, e)

    return removed


def run_backup(job: dict, ctx) -> str:
    """Main backup handler — called by the job dispatcher.

    Synchronous — runs in thread pool.
    """
    from dotenv import load_dotenv
    from data_layer.backups import (
        create_backup, complete_backup, fail_backup, skip_backup,
        prune_old_records,
    )

    # Re-read .env so changes take effect without restarting the agent
    load_dotenv(override=True)

    backup_id = _new_id()
    job_id = job.get("id", "")
    is_on_demand = job.get("config", {}).get("on_demand", False)
    start = time.time()
    date_str = datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d")

    # Create DB record
    create_backup(backup_id, job_id=job_id, created_by=job.get("created_by", "system"))

    # Check enabled flag (on-demand backups ignore it)
    if not is_on_demand:
        enabled = os.getenv("BACKUP_ENABLED", "true").strip().lower()
        if enabled != "true":
            skip_backup(backup_id)
            logger.info("BACKUP: Skipped — BACKUP_ENABLED=%s", enabled)
            return "Backups disabled, skipping"

    staging = STAGING_DIR
    try:
        # Clean and create staging
        if os.path.exists(staging):
            shutil.rmtree(staging)
        os.makedirs(staging, exist_ok=True)

        # 1. pg_dump
        ctx.update_progress(5, "Running pg_dump...")
        dump_file, dump_size = _run_pg_dump(staging, date_str, ctx)
        ctx.update_progress(25, f"pg_dump complete ({dump_size / 1048576:.1f} MB)")

        # 2. Project zip
        ctx.update_progress(30, "Creating project archive...")
        zip_file, zip_size = _create_project_zip(staging, date_str, ctx)
        ctx.update_progress(55, f"Archive complete ({zip_size / 1048576:.1f} MB)")

        # 3. Table counts
        ctx.update_progress(60, "Collecting table counts...")
        table_counts = _get_table_counts()

        # 4. RESTORE.md
        ctx.update_progress(65, "Generating restore instructions...")
        restore_file = _generate_restore_md(
            staging, date_str, dump_size, zip_size, table_counts,
        )

        # 5. Copy to network
        ctx.update_progress(70, "Copying to network drive...")
        network_folder, files_created = _copy_to_network(
            staging, date_str, dump_file, zip_file, restore_file,
        )
        if network_folder:
            ctx.update_progress(80, f"Copied to {network_folder}")
        else:
            ctx.update_progress(80, "Network copy skipped (no path configured)")

        # 6. Upload to Google Drive
        ctx.update_progress(82, "Uploading to Google Drive...")
        from gdrive_backup import upload_backup_to_gdrive
        gdrive_result = upload_backup_to_gdrive(
            date_str, dump_file, zip_file, restore_file,
        )
        gdrive_status = gdrive_result.get("status", "error")
        if gdrive_status == "ok":
            ctx.update_progress(90, "Google Drive upload complete")
        elif gdrive_status == "skipped":
            ctx.update_progress(90, "Google Drive upload skipped (not configured)")
        else:
            ctx.update_progress(90, f"Google Drive upload failed: {gdrive_result.get('reason', '')[:100]}")

        # 7. Prune old backups
        retention = int(os.getenv("BACKUP_RETENTION", "5"))
        ctx.update_progress(92, "Pruning old backups...")
        pruned_net = _prune_network_backups(keep=retention)
        pruned_db = prune_old_records(keep=retention)
        if pruned_net or pruned_db:
            logger.info("BACKUP: Pruned %d network + %d DB records", pruned_net, pruned_db)

        # 8. Complete record
        duration = time.time() - start
        complete_backup(
            backup_id,
            pg_dump_size=dump_size,
            zip_size=zip_size,
            network_path=network_folder,
            files_created=files_created,
            table_counts=table_counts,
            duration_secs=round(duration, 1),
        )
        ctx.update_progress(100, "Backup complete")

        summary = (
            f"Backup complete: {dump_size / 1048576:.1f} MB dump + "
            f"{zip_size / 1048576:.1f} MB zip"
        )
        if network_folder:
            summary += f" → {network_folder}"
        if gdrive_status == "ok":
            gdrive_files = gdrive_result.get("files", [])
            summary += f" + Google Drive ({len(gdrive_files)} files)"
            for gf in gdrive_files:
                logger.info("BACKUP: Google Drive: %s (%.1f MB)", gf["name"], gf["size"] / 1048576)
        summary += f" ({duration:.0f}s)"
        logger.info("BACKUP: %s", summary)
        return summary

    except Exception as e:
        duration = time.time() - start
        error_str = str(e)[:2000]
        fail_backup(backup_id, error=error_str)
        logger.error("BACKUP: Failed after %.0fs — %s", duration, error_str)
        raise

    finally:
        # Always clean staging
        if os.path.exists(staging):
            try:
                shutil.rmtree(staging)
            except Exception as e:
                logger.warning("BACKUP: Failed to clean staging: %s", e)
