"""System — FastAPI routes.

Mounted by the platform loader at ``/api/apps/system``. Backs the
SystemApp dashboard.

Endpoints (relative to the prefix above)::

    GET    /metrics    — record counts, DB size, latest job, latest
                          backup, doc-curation cursor, process snapshot
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform as _platform
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count(query: str) -> int | None:
    """Best-effort scalar count. Returns ``None`` on any DB error so a
    missing-table failure on one section doesn't poison the whole
    response.
    """
    from data_layer.db import fetch_one
    try:
        row = fetch_one(query)
        if row is None:
            return 0
        # fetch_one returns a RealDictRow when possible — first value
        # works whether the column is anonymous or named.
        if isinstance(row, dict):
            return list(row.values())[0]
        return row[0]
    except Exception as exc:
        logger.debug("system.metrics count failed for %s: %s", query, exc)
        return None


# The (table_name, label, query) triples make it easy to add a new
# app's table without touching the SQL aggregation logic. The query
# is left at module scope so it stays readable side-by-side with the
# UI columns.
_PACKAGED_COUNTS: list[tuple[str, str]] = [
    ("documents",          "SELECT count(*) FROM app_documents.documents"),
    ("reminders",          "SELECT count(*) FROM app_reminders.reminders"),
    ("reminders_active",   "SELECT count(*) FROM app_reminders.reminders WHERE active = TRUE"),
    ("notifications",      "SELECT count(*) FROM app_notifications.notifications"),
    ("lists",              "SELECT count(*) FROM app_lists.lists"),
    ("list_items",         "SELECT count(*) FROM app_lists.list_items"),
    ("jobs",               "SELECT count(*) FROM app_jobs.jobs"),
    ("jobs_running",       "SELECT count(*) FROM app_jobs.jobs WHERE status = 'running'"),
    ("jobs_queued",        "SELECT count(*) FROM app_jobs.jobs WHERE status = 'queued'"),
    ("backups",            "SELECT count(*) FROM app_backups.backups"),
    ("schedules",          "SELECT count(*) FROM app_schedules.schedules"),
    ("folders",            "SELECT count(*) FROM app_folders.folders"),
    ("behaviors",          "SELECT count(*) FROM app_behaviors.behaviors"),
    ("priority_focus",     "SELECT count(*) FROM app_prioritize.priority_focus"),
    ("timeline_posts",     "SELECT count(*) FROM app_timeline.timeline_posts"),
    ("goals",              "SELECT count(*) FROM app_goals.goals"),
    ("projects",           "SELECT count(*) FROM app_goals.projects"),
    ("tasks",              "SELECT count(*) FROM app_goals.tasks"),
]

# Platform-layer tables (public schema — created by migrations/000_baseline.sql).
_PLATFORM_COUNTS: list[tuple[str, str]] = [
    ("memories",               "SELECT count(*) FROM memories"),
    ("chat_turns",             "SELECT count(*) FROM chat_turns"),
    ("knowledge_sources",      "SELECT count(*) FROM knowledge_sources"),
    ("knowledge_chunks",       "SELECT count(*) FROM knowledge_chunks"),
    ("images",                 "SELECT count(*) FROM images"),
    ("links",                  "SELECT count(*) FROM links"),
    ("artifacts",              "SELECT count(*) FROM artifacts"),
    ("memory_queue_pending",   "SELECT count(*) FROM memory_ingestion_queue WHERE status = 'pending'"),
]


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def api_system_metrics():
    """Record counts, DB size, latest job + backup, doc-curation
    cursor, and a process snapshot.

    Resilient — every section is wrapped in a try/except so one
    missing table degrades that field rather than 500-ing the
    whole call.
    """
    def _fetch():
        from data_layer.db import fetch_one
        from config import TIMEZONE

        tz = ZoneInfo(TIMEZONE)

        # ---- counts -------------------------------------------------
        counts: dict[str, int | None] = {}
        for label, sql in _PACKAGED_COUNTS + _PLATFORM_COUNTS:
            counts[label] = _count(sql)

        # ---- DB size -----------------------------------------------
        db_size = {"size": "?", "size_bytes": 0}
        try:
            row = fetch_one(
                "SELECT pg_size_pretty(pg_database_size(current_database())) AS size, "
                "pg_database_size(current_database()) AS size_bytes"
            )
            if row:
                db_size = {
                    "size": row["size"],
                    "size_bytes": row["size_bytes"],
                }
        except Exception:
            pass

        # ---- latest job (packaged) ---------------------------------
        latest_job = None
        try:
            row = fetch_one(
                "SELECT id, name, job_type, status, last_run_at FROM app_jobs.jobs "
                "ORDER BY last_run_at DESC NULLS LAST LIMIT 1"
            )
            if row:
                latest_job = dict(row)
        except Exception:
            pass

        # ---- latest backup (packaged) ------------------------------
        latest_backup = None
        try:
            row = fetch_one(
                "SELECT id, status, started_at, duration_secs FROM app_backups.backups "
                "ORDER BY started_at DESC LIMIT 1"
            )
            if row:
                latest_backup = dict(row)
        except Exception:
            pass

        # ---- investment metrics (remote trading service) -----------
        latest_investment = None
        try:
            import json as _json_ts
            import urllib.request as _urllib

            ts_url = os.getenv("VITE_TRADING_URL", "")
            ts_key = os.getenv("VITE_TRADING_KEY", "")
            if ts_url:
                req = _urllib.Request(
                    f"{ts_url.rstrip('/')}/api/metrics",
                    headers={"X-API-Key": ts_key},
                )
                with _urllib.urlopen(req, timeout=5) as resp:  # noqa: S310
                    inv = _json_ts.loads(resp.read())
                if inv.get("snapshot_count") is not None:
                    counts["investment_snapshots"] = inv["snapshot_count"]
                latest_investment = inv.get("latest_snapshot")
        except Exception:
            pass

        # ---- document curation cursor (documents app domain) -------
        doc_curation: dict = {
            "total_memories": 0, "cursor_position": 0, "remaining": 0,
            "last_cycle": None, "cursor_id": None,
        }
        try:
            total = fetch_one("SELECT count(*) AS cnt FROM memories")
            doc_curation["total_memories"] = total["cnt"] if total else 0

            cursor_row = fetch_one(
                "SELECT content, updated_at FROM skipper_state "
                "WHERE domain = 'document' AND subject_id = 'last_processed_batch' "
                "ORDER BY updated_at DESC LIMIT 1"
            )
            if cursor_row:
                import json as _json
                cd = _json.loads(cursor_row["content"])
                cursor_id = cd.get("latest_id", "")
                doc_curation["cursor_id"] = cursor_id
                doc_curation["last_cycle"] = {
                    "processed_at": cd.get("processed_at"),
                    "processed_count": cd.get("processed_count"),
                    "offered_count": cd.get("offered_count"),
                    "all_processed": cd.get("all_processed"),
                    "auto_advanced": cd.get("auto_advanced", False),
                }
                if cursor_id:
                    pos = fetch_one(
                        "SELECT count(*) AS pos FROM memories "
                        "WHERE created_at <= (SELECT created_at FROM memories WHERE id = %s)",
                        (cursor_id,),
                    )
                    doc_curation["cursor_position"] = pos["pos"] if pos else 0
                    doc_curation["remaining"] = (
                        doc_curation["total_memories"] - doc_curation["cursor_position"]
                    )
            else:
                doc_curation["remaining"] = doc_curation["total_memories"]
        except Exception:
            pass

        # ---- process snapshot --------------------------------------
        uptime_secs = None
        memory_mb = None
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            memory_mb = round(proc.memory_info().rss / 1048576, 1)
            uptime_secs = round(
                (datetime.now(tz) - datetime.fromtimestamp(proc.create_time(), tz))
                .total_seconds()
            )
        except ImportError:
            pass

        return {
            "counts": counts,
            "database": db_size,
            "latest_job": latest_job,
            "latest_backup": latest_backup,
            "latest_investment": latest_investment,
            "doc_curation": doc_curation,
            "system": {
                "platform": _platform.platform(),
                "python": _platform.python_version(),
                "pid": os.getpid(),
                "memory_mb": memory_mb,
                "uptime_seconds": uptime_secs,
            },
        }

    return await asyncio.to_thread(_fetch)
