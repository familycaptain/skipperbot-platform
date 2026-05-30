"""Seed the chores_morning schedule (9:00 AM daily).

Creates a row in public.schedules (NOT public.jobs — jobs.schedule_expr is
deprecated). The schedule_job_trigger picks it up when next_due passes and
submits a new chores_morning job for the handler in apps/chores/handlers.py.

Run once with:  python apps/chores/migrations/003_seed_morning_schedule.py
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../..")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../..", ".env"))

from apps.schedules.data import create_schedule, list_schedules


def run():
    existing = list_schedules(active_only=False)
    already = any(
        s.get("linked_entity_type") == "job" and s.get("linked_entity_id") == "chores_morning"
        for s in existing
    )
    if already:
        print("Chores morning schedule already exists — skipping")
        return

    sch = create_schedule(
        title="Daily Chores Morning Push (9:00 AM)",
        created_by="system",
        category="general",
        assigned_to="user",
        description=(
            "Sends each kid a Discord DM at 9 AM listing their household chores "
            "for the day. Handler: apps/chores/handlers.py:handle_chores_morning."
        ),
        recurrence_type="daily",
        recurrence_rule={"every": 1},
        time_of_day="09:00",
        linked_entity_id="chores_morning",
        linked_entity_type="job",
        reminder_mins=0,
        notify_channel="none",
    )
    print(f"Created chores_morning schedule: {sch['id']} (next_due: {sch.get('next_due')})")


if __name__ == "__main__":
    run()
