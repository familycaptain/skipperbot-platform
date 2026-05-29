"""Backups — event + job-handler registrations.

Registers two job handlers with the platform jobs dispatcher:

- ``backup`` — produces a full backup (pg_dump + project zip +
  RESTORE.md) and copies it to every enabled destination.
- ``backup_check`` — daily verification job that notifies Alice if
  today's run is missing or failed.

Both handlers live in ``apps/backups/runner.py``. The runner reads
its master switch + per-destination toggles from
``app_platform.config`` (scope ``app:backups``), so the platform
boots cleanly even when nothing is configured.
"""

from __future__ import annotations

from app_platform.jobs import register_handler
from apps.backups.runner import run_backup, run_backup_check


register_handler(
    "backup", run_backup,
    max_concurrent=1, cancel_on_shutdown=True,
)
register_handler(
    "backup_check", run_backup_check,
    max_concurrent=1, cancel_on_shutdown=True,
)
