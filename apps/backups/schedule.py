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


def has_destination(cfg: dict) -> bool:
    """Whether the user has actually configured somewhere for a backup to go.

    A path with the toggle off is not a destination, and neither is a toggle on with no
    path — either way the run would have nowhere to write.
    """
    if cfg.get("filesystem_enabled") and (cfg.get("filesystem_path") or "").strip():
        return True
    if cfg.get("gdrive_enabled"):
        return True
    return False


def ensure_schedules(cfg: dict | None = None) -> None:
    """Create or reconcile the backup schedules. Never raises — a config save must not
    fail because scheduling did, and the next call reconciles anyway."""
    try:
        from apps.schedules import data as _sched
        if cfg is None:
            from app_platform.backups import get_config
            cfg = get_config()

        # Active only when the master switch is on AND there is somewhere to write. The
        # rows exist either way, so turning a destination on flips them live with no
        # further setup — which is the whole point of this module.
        active = bool(cfg.get("enabled")) and has_destination(cfg)
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
            existing = None
            try:
                existing = _sched.get_schedule(sched_id)
            except Exception:
                # Missing table / early boot — treat as "not yet created". Never fatal.
                logger.debug("BACKUPS: get_schedule(%s) failed — treating as new", sched_id,
                             exc_info=True)

            # Reset the countdown only on (re)activation or a time change, so a plain
            # reconcile does not drift the fire time and re-enabling lands on the next
            # FUTURE occurrence rather than firing immediately.
            reset = active and (
                existing is None
                or not existing.get("active")
                or existing.get("time_of_day") != time_of_day
            )
            next_due = _sched.compute_next_due("daily", {"every": 1}, time_of_day) if reset else None

            _sched.upsert_schedule(
                sched_id,
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
