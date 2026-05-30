"""Seed the chores_evening schedule (8:00 PM daily).

Creates a row in public.schedules that fires the chores_evening job each
night at 8:00 PM local time. The handler in apps/chores/handlers.py DMs any kid
who still has unchecked chores from today and asks them to either reply
to check them off or go finish them.

Run once with:  python apps/chores/migrations/006_seed_evening_schedule.py
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../..")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../..", ".env"))

from apps.schedules.data import create_schedule, list_schedules


def run():
    existing = list_schedules(active_only=False)
    already = any(
        s.get("linked_entity_type") == "job" and s.get("linked_entity_id") == "chores_evening"
        for s in existing
    )
    if already:
        print("Chores evening schedule already exists — skipping")
        return

    sch = create_schedule(
        title="Daily Chores Evening Nudge (8:00 PM)",
        created_by="system",
        category="general",
        assigned_to="user",
        description=(
            "Sends a Discord DM at 8 PM to each kid who still has unchecked "
            "chores from today. Asks them to reply (\"did it\") to check off "
            "or to go finish before bed. "
            "Handler: apps/chores/handlers.py:handle_chores_evening."
        ),
        recurrence_type="daily",
        recurrence_rule={"every": 1},
        time_of_day="20:00",
        linked_entity_id="chores_evening",
        linked_entity_type="job",
        reminder_mins=0,
        notify_channel="none",
    )
    print(f"Created chores_evening schedule: {sch['id']} (next_due: {sch.get('next_due')})")


if __name__ == "__main__":
    run()
