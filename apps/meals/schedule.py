"""Meals — nightly dinner-check schedule reconciliation.

The dinner check runs off ONE ``meals_dinner_check`` schedule row (owned by the
schedules app). Its time is an operator setting (``dinner_inquiry_time``, an
enum in the Meals settings). This module keeps that single row in sync with the
setting:

  * ``reconcile_dinner_schedule()`` — the idempotent, race-safe convergence
    point. Reads the setting, whitelists it against the enum (``Off`` or any
    unrecognized value ⇒ the schedule is set inactive — fail-closed), and
    upserts exactly ONE row with a STABLE id (``sch-meals-dinner-check``) so
    two concurrent callers converge on one row instead of racing a
    list-then-create into duplicates.

  * ``seed_dinner_schedule()`` — the post-all-apps-loaded one-shot seeder,
    registered as a lifecycle background task (started AFTER ``load_all_apps``,
    so ``app_schedules`` exists — meals loads before schedules alphabetically,
    so this must NOT run at import time).

The row fires **exactly once per day** at the chosen ``time_of_day``
(``recurrence_type='daily'``, ``recurrence_rule={'every': 1}``) — the enum is
the single daily time, NOT an interval. On (re)activation or a time change we
reset ``next_due`` from *now* (to the next FUTURE occurrence) so re-enabling
after ``Off`` does not fire immediately; an otherwise-idempotent reconcile
leaves ``next_due`` untouched.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Stable primary-key id for the single dinner-check schedule row (upsert target).
SCHEDULE_ID = "sch-meals-dinner-check"
# The job_type the schedule triggers (matches manifest.yaml job_types + the
# handler in handlers.py). Stored in the schedule's linked_entity_id.
JOB_TYPE = "meals_dinner_check"

DEFAULT_TIME = "21:00"
OFF = "Off"

# Whitelist of valid daily times — MUST match the manifest `choices` (minus Off).
# Anything not in here (incl. Off, empty, or a tampered value) disables the
# check: fail-closed.
VALID_TIMES = {
    "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00",
}


def _read_setting() -> str:
    """Read the operator's dinner_inquiry_time setting (app:meals scope)."""
    from app_platform import settings as _settings
    return _settings.get("dinner_inquiry_time", scope="app:meals", default=DEFAULT_TIME)


def reconcile_dinner_schedule() -> dict | None:
    """Converge the single meals_dinner_check schedule row to the setting.

    Idempotent and race-safe (stable-id upsert). Fail-closed: an unrecognized
    or ``Off`` setting disables the row; any error is logged and swallowed —
    this NEVER raises (so it can run at boot and from an event handler without
    taking anything down).
    """
    try:
        raw = _read_setting()
        value = str(raw).strip() if raw is not None else DEFAULT_TIME

        # Whitelist against the enum. Off / unknown / tampered ⇒ inactive.
        active = value in VALID_TIMES
        if not active and value != OFF:
            logger.warning(
                "MEALS: dinner_inquiry_time=%r not a recognized time — disabling "
                "the nightly dinner check (fail-closed).", raw,
            )
        time_of_day = value if active else DEFAULT_TIME

        from apps.schedules import data as _sched

        existing = None
        try:
            existing = _sched.get_schedule(SCHEDULE_ID)
        except Exception:
            # Missing table / early boot — treat as "not yet created". Never fatal.
            logger.debug("MEALS: get_schedule(%s) failed — treating as new", SCHEDULE_ID,
                         exc_info=True)
            existing = None

        # Reset next_due from now ONLY on (re)activation or a time change, so a
        # plain idempotent reconcile doesn't drift the fire time and re-enabling
        # after Off lands on the next FUTURE occurrence (not an immediate fire).
        reset = active and (
            existing is None
            or not existing.get("active")
            or existing.get("time_of_day") != time_of_day
        )
        # next_due=None means "leave the existing countdown alone" on update.
        next_due = _sched.compute_next_due("daily", {"every": 1}, time_of_day) if reset else None

        _sched.upsert_schedule(
            SCHEDULE_ID,
            title="Nightly Dinner Check",
            description=(
                "Checks whether tonight's dinner was logged; if not, asks the "
                "household what they had so it can log it and update the meal "
                "library. Time is set in Settings → Meals (dinner_inquiry_time). "
                "Handler: apps/meals/handlers.py:handle_dinner_check."
            ),
            category="general",
            created_by="system",
            recurrence_type="daily",
            recurrence_rule={"every": 1},
            time_of_day=time_of_day,
            linked_entity_id=JOB_TYPE,
            linked_entity_type="job",
            next_due=next_due,
            active=active,
            reminder_mins=0,
            notify_channel="none",
        )

        _cleanup_legacy_job()

        logger.info(
            "MEALS: reconciled dinner schedule (active=%s, time_of_day=%s, reset_next_due=%s)",
            active, time_of_day, reset,
        )
        try:
            return _sched.get_schedule(SCHEDULE_ID)
        except Exception:
            return None
    except Exception as exc:  # fail-closed: never let reconcile take down its caller
        logger.error("MEALS: reconcile_dinner_schedule failed (swallowed, no raise): %s",
                     exc, exc_info=True)
        return None


def _cleanup_legacy_job() -> None:
    """One-time cleanup of the dead ``app_jobs.jobs`` 'j-meals-dinner-check' row.

    Seeded by the removed migration ``003_seed_dinner_schedule.py`` (a cron-on-
    job seam that never actually ran and referenced a removed column). Best-
    effort — a missing row / table is a no-op.
    """
    try:
        from app_platform.db import execute_in_schema
        execute_in_schema("app_jobs", "DELETE FROM jobs WHERE id = %s",
                          ("j-meals-dinner-check",))
    except Exception:
        logger.debug("MEALS: legacy job cleanup skipped", exc_info=True)


async def seed_dinner_schedule() -> None:
    """Post-all-apps-loaded one-shot seeder (registered via hooks.register_hooks
    as a lifecycle background task, which the platform starts AFTER
    ``load_all_apps`` — guaranteeing ``app_schedules`` exists). Runs the blocking
    reconcile off the event loop.
    """
    import asyncio
    await asyncio.to_thread(reconcile_dinner_schedule)
