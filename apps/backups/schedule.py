"""Wire the nightly backup to the dispatcher when a destination is configured.

Recurring work on this platform needs a ``public.schedules`` row linked to a ``job_type``
(``apps/jobs/dispatcher.py``). The backup handlers have always been registered, so the
dispatcher would happily run them — but nothing ever created the row, so nothing ever asked
it to. Configuring a destination produced an install that looked backed up and was not; the
only thing that ever submitted a backup was the Run Now button.

Backups are configured by the user after install, on purpose — an unconfigured install not
backing up is expected. This module is about what happens *after* they configure one.

``ensure_schedules()`` is idempotent and safe to call on every config change and on boot:
it upserts against stable ids, and reconciles ``active`` with the current config rather than
re-creating anything.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BACKUP_SCHEDULE_ID = "sch-backup-nightly"
CHECK_SCHEDULE_ID = "sch-backup-check-daily"
BACKUP_JOB_TYPE = "backup"
CHECK_JOB_TYPE = "backup_check"

# The verification pass asks "did today's backup happen?", so it has to run after the
# backup itself. Offset rather than a second configurable time: one knob, no way to set
# them in an order that makes the check meaningless.
CHECK_OFFSET_HOURS = 6
DEFAULT_TIME = "02:00"


def _time_of_day_from_cron(cron: str) -> str:
    """Best-effort ``M H * * *`` → ``HH:MM``.

    The config exposes a 5-field cron, but schedules are expressed as a recurrence plus a
    time of day. Every meaningful backup cadence here is "once a day at a time", so a daily
    cron maps exactly; anything more exotic keeps its time and runs daily rather than being
    silently dropped.
    """
    parts = (cron or "").split()
    if len(parts) != 5:
        return DEFAULT_TIME
    minute, hour = parts[0], parts[1]
    try:
        m, h = int(minute), int(hour)
    except ValueError:
        # A step or list expression (*/15, 1,31) has no single time — keep the default and
        # say so, rather than pretending we honoured it.
        logger.info("BACKUPS: cron %r is not a plain daily time; scheduling at %s",
                    cron, DEFAULT_TIME)
        return DEFAULT_TIME
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return DEFAULT_TIME
    if parts[2:] != ["*", "*", "*"]:
        logger.info("BACKUPS: cron %r is not daily; running daily at %02d:%02d", cron, h, m)
    return f"{h:02d}:{m:02d}"


def _shift_hours(time_of_day: str, hours: int) -> str:
    h, m = (int(x) for x in time_of_day.split(":"))
    return f"{(h + hours) % 24:02d}:{m:02d}"


def _flag(cfg: dict, key: str, *, default: bool) -> bool:
    """Read a boolean config key, applying the manifest default when it was never set.

    ``get_config`` returns None for a key nobody has written — the REST layer is what
    coerces to the documented defaults, and this runs below it. Reading None as False got
    the master switch backwards: `enabled` defaults to TRUE in the manifest, so an install
    that had never touched it would have scheduled nothing. Values can also arrive as JSON
    strings through the settings panel, so accept those too.
    """
    v = cfg.get(key)
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def has_destination(cfg: dict) -> bool:
    """Whether the user has actually configured somewhere for a backup to go.

    A path with the toggle off is not a destination, and neither is a toggle on with no
    path — either way the run would have nowhere to write.
    """
    if _flag(cfg, "filesystem_enabled", default=False) and (cfg.get("filesystem_path") or "").strip():
        return True
    if _flag(cfg, "gdrive_enabled", default=False):
        return True
    return False


def _rows_for(_sched, job_type: str) -> list[dict]:
    """Every schedule already pointing at `job_type`, whatever id it carries.

    Looked up by JOB TYPE rather than by our own id. An install that predates this module
    can already have a schedule for the nightly backup — created by hand or by an earlier
    version — under an id we would never guess. Keying only on our id leaves that one in
    place and adds a second, so the backup runs twice a night. That is exactly what
    happened on a live install: two `backup` rows and two `backup_check` rows, all active.
    """
    try:
        rows = _sched.list_schedules(active_only=False, limit=500) or []
    except Exception:
        logger.debug("BACKUPS: could not list schedules", exc_info=True)
        return []
    return [r for r in rows if (r.get("linked_entity_id") or "") == job_type]


def ensure_schedules(cfg: dict | None = None) -> None:
    """Create, adopt or reconcile the backup schedules. Never raises — a config save must
    not fail because scheduling did, and the next call reconciles anyway."""
    try:
        from apps.schedules import data as _sched
        if cfg is None:
            from app_platform.backups import get_config
            cfg = get_config()

        # Active only when the master switch is on AND there is somewhere to write. The
        # rows exist either way, so turning a destination on flips them live with no
        # further setup — which is the whole point of this module.
        active = _flag(cfg, "enabled", default=True) and has_destination(cfg)
        backup_time = _time_of_day_from_cron(cfg.get("cron") or "")
        check_time = _shift_hours(backup_time, CHECK_OFFSET_HOURS)

        for sched_id, job_type, title, time_of_day, description in (
            (BACKUP_SCHEDULE_ID, BACKUP_JOB_TYPE, "Nightly Backup", backup_time,
             "Dumps the database and copies it to every configured destination. Time and "
             "destinations are set in Settings → Backups. Handler: "
             "apps/backups/runner.py:run_backup."),
            (CHECK_SCHEDULE_ID, CHECK_JOB_TYPE, "Daily Backup Check", check_time,
             "Verifies that today's backup ran and notifies if it did not. Runs "
             f"{CHECK_OFFSET_HOURS}h after the backup. Handler: "
             "apps/backups/runner.py:run_backup_check."),
        ):
            found = _rows_for(_sched, job_type)
            ours = next((r for r in found if r.get("id") == sched_id), None)
            # Prefer our own row; otherwise ADOPT what is already there rather than adding
            # another. Oldest first, so the choice is stable across boots.
            target = ours or (sorted(found, key=lambda r: str(r.get("created_at") or ""))[0]
                              if found else None)
            target_id = (target or {}).get("id") or sched_id
            if target and target_id != sched_id:
                logger.info("BACKUPS: adopting existing %s schedule %s rather than creating "
                            "a second one", job_type, target_id)

            # Reset the countdown only on (re)activation or a time change, so a plain
            # reconcile does not drift the fire time and re-enabling lands on the next
            # FUTURE occurrence rather than firing immediately.
            reset = active and (
                target is None
                or not target.get("active")
                or str(target.get("time_of_day") or "")[:5] != time_of_day
            )
            next_due = _sched.compute_next_due("daily", {"every": 1}, time_of_day) if reset else None

            _sched.upsert_schedule(
                target_id,
                title=title,
                description=description,
                category="general",
                created_by="system",
                recurrence_type="daily",
                recurrence_rule={"every": 1},
                time_of_day=time_of_day,
                linked_entity_id=job_type,
                linked_entity_type="job",
                next_due=next_due,
                active=active,
                reminder_mins=0,
                notify_channel="none",
            )

            # Anything else pointing at the same job type would run it a second time the
            # same night. Deactivated rather than deleted: reversible, visible in the app,
            # and it never destroys a row somebody made deliberately.
            for row in found:
                rid = row.get("id")
                if rid and rid != target_id and row.get("active"):
                    try:
                        _sched.upsert_schedule(rid, title=row.get("title") or f"{job_type} (duplicate)",
                                               active=False)
                        logger.warning("BACKUPS: deactivated duplicate %s schedule %s — it is "
                                       "scheduled once, on %s", job_type, rid, target_id)
                    except Exception:
                        logger.warning("BACKUPS: could not deactivate duplicate schedule %s",
                                       rid, exc_info=True)

        logger.info("BACKUPS: schedules reconciled — active=%s, backup at %s, check at %s",
                    active, backup_time, check_time)
    except Exception:
        logger.warning("BACKUPS: could not reconcile backup schedules", exc_info=True)


async def seed_schedules() -> None:
    """Post-all-apps-loaded one-shot seeder, registered via ``hooks.register_hooks``.

    Runs after ``load_all_apps`` so ``app_schedules`` exists — backups loads before
    schedules alphabetically, so at import time its tables may not be there yet. This is
    what gives an install that was configured BEFORE this fix its missing rows, without
    anyone having to re-save the settings.
    """
    import asyncio
    await asyncio.to_thread(ensure_schedules)
