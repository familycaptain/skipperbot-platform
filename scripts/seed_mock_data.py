#!/usr/bin/env python
"""Seed realistic MOCK data for box-2 / demos (EVOLVE.md §13).

Run inside the platform container (so the app stores + DB are importable):

    docker compose exec agent python scripts/seed_mock_data.py
    docker compose exec agent python scripts/seed_mock_data.py --members-only

Deterministic (hardcoded data — no AI at runtime), and resilient: each app is
seeded in its own try/except so one app's failure doesn't abort the rest, and it
prints a per-app summary. It calls the apps' real store functions, so entity ids,
FKs, and events are generated correctly. This is a MOCK family for a throwaway box —
not anyone's real household.

v1 covers: members, lists, auto (vehicles + service + issues), chores, meals. More
apps get added as the schema/APIs are confirmed against a live DB.
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# a mock family (NOT a real household)
MEMBERS = [
    ("david", "David", "member"),
    ("maria", "Maria", "member"),
    ("tyler", "Tyler", "member"),
    ("katie", "Katie", "member"),
]
_counts: dict[str, int] = {}


def _bump(app: str, n: int = 1):
    _counts[app] = _counts.get(app, 0) + n


def seed_members():
    from data_layer.users import create_user, get_user
    for name, display, role in MEMBERS:
        if not get_user(name):
            create_user(name, display, role=role)
            _bump("members")


def seed_lists():
    from apps.lists import store
    data = {
        ("Groceries", "maria"): ["Milk", "Eggs", "Sourdough bread", "Bananas", "Chicken thighs",
                                  "Coffee", "Paper towels", "Spinach", "Greek yogurt", "Olive oil"],
        ("Hardware Store", "david"): ["3in deck screws", "Wood glue", "120-grit sandpaper",
                                      "Exterior paint - white", "Furnace filter 16x25", "Caulk"],
        ("Beach Trip - Packing", "maria"): ["Sunscreen", "Beach towels", "Swimsuits", "Cooler",
                                            "Phone chargers", "First-aid kit", "Snacks"],
        ("Weekend Projects", "david"): ["Fix gate latch", "Mulch front beds", "Clean gutters",
                                        "Replace porch bulb"],
        ("Costco Run", "maria"): ["Rotisserie chicken", "Paper plates", "Laundry pods",
                                  "Frozen berries", "Trash bags"],
    }
    for (name, by), items in data.items():
        lst = store.create_list(name, by)
        _bump("lists")
        for text in items:
            store.add_item(lst["id"], text, by)
            _bump("list_items")


def seed_auto():
    from apps.auto import tools
    vehicles = [
        dict(created_by="david", make="Honda", model="Odyssey", year=2019, color="Silver",
             odometer=68000, license_plate="ABC-1234"),
        dict(created_by="maria", make="Toyota", model="RAV4", year=2021, color="Blue",
             odometer=31000, license_plate="XYZ-7788"),
        dict(created_by="tyler", make="Subaru", model="Outback", year=2015, color="Green",
             odometer=121000, license_plate="OLD-2015"),
    ]
    svc = [("Oil Change", "2026-01-12", 64000, 72.50, "QuickLube"),
           ("Tire Rotation", "2026-02-20", 65200, 35.00, "Discount Tire"),
           ("Brake Pads (front)", "2026-04-03", 66800, 285.00, "Midas"),
           ("State Inspection", "2026-05-10", 67500, 25.00, "Local Garage")]
    for v in vehicles:
        vid = tools.create_vehicle(**v)
        _bump("vehicles")
        for stype, date, odo, cost, shop in svc:
            tools.log_service(vid, stype, v["created_by"], date_performed=date,
                              odometer_at_service=odo, cost=cost, shop_name=shop)
            _bump("service_records")
    # a couple of open issues on the first vehicle
    vid0 = tools.create_vehicle(created_by="david", make="Ford", model="F-150", year=2018,
                                color="Black", odometer=89000, license_plate="TRK-0418")
    _bump("vehicles")
    for title, sev in [("Check-engine light flickers on cold starts", "minor"),
                       ("Passenger window slow to roll up", "minor"),
                       ("Brake squeal when stopping", "moderate")]:
        try:
            tools.report_vehicle_issue(vid0, title, "david", severity=sev)
            _bump("vehicle_issues")
        except Exception:
            tools.report_vehicle_issue(vid0, title, "david")
            _bump("vehicle_issues")


def _id(rec):
    return rec.get("id") if isinstance(rec, dict) else rec


def seed_chores():
    from apps.chores import data as chores
    kids = []
    for name, color in [("Tyler", "#3b82f6"), ("Katie", "#ec4899")]:
        kids.append(chores.create_kid(name, color=color))
        _bump("chore_kids")
    start = _id(kids[0]) if kids else ""
    for zone_name in ["Kitchen", "Bathrooms", "Living Room"]:
        z = chores.create_zone(zone_name, start, description=f"{zone_name} weekly cleanup")
        _bump("chore_zones")
        for dow, cname in [(0, "Wipe down surfaces"), (3, "Sweep & vacuum"), (6, "Take out trash")]:
            chores.create_chore(_id(z), dow, cname)
            _bump("chores")


def seed_meals():
    from apps.meals import data as meals
    rows = [("Spaghetti Bolognese", "maria", "medium", ["pasta", "italian"], 15, 40),
            ("Sheet-pan chicken & veggies", "david", "easy", ["chicken", "weeknight"], 10, 35),
            ("Taco Tuesday", "maria", "easy", ["mexican", "kids"], 20, 20),
            ("Veggie stir-fry", "tyler", "easy", ["vegetarian", "quick"], 15, 12),
            ("Grilled salmon & rice", "david", "medium", ["fish", "healthy"], 10, 20),
            ("Homemade pizza night", "maria", "medium", ["italian", "weekend"], 30, 15)]
    for name, by, effort, tags, prep, cook in rows:
        meals.create_meal("meal-" + uuid.uuid4().hex[:8], name, by, effort=effort,
                          tags=tags, prep_time_min=prep, cook_time_min=cook)
        _bump("meals")


def seed_recipes():
    from apps.recipes import tools as recipes
    rows = [
        ("Weeknight Salsa", "maria", [("tomatoes", "4", "whole"), ("onion", "1/2", "cup"),
         ("cilantro", "1/4", "cup"), ("lime", "1", "whole")],
         ["Dice everything", "Combine", "Salt to taste, chill"], ["sauces"], 10, 0, 6),
        ("Banana Bread", "david", [("ripe bananas", "3", "whole"), ("flour", "2", "cups"),
         ("sugar", "3/4", "cup"), ("butter", "1/2", "cup")],
         ["Mash bananas", "Mix wet + dry", "Bake 60 min at 350F"], ["baking"], 15, 60, 8),
        ("Chicken Tikka Masala", "maria", [("chicken", "1.5", "lb"), ("yogurt", "1", "cup"),
         ("tomato sauce", "2", "cups"), ("garam masala", "2", "tbsp")],
         ["Marinate chicken", "Sear", "Simmer in sauce 25 min"], ["indian", "dinner"], 30, 40, 4),
    ]
    for title, by, ings, steps, cats, prep, cook, serv in rows:
        recipes.create_recipe(
            title, by,
            ingredients=json.dumps([{"item": i, "quantity": q, "unit": u} for i, q, u in ings]),
            steps=json.dumps(steps), categories=json.dumps(cats),
            prep_time_min=prep, cook_time_min=cook, servings=serv)
        _bump("recipes")


def seed_reminders():
    from apps.reminders.store import create_reminder
    now = datetime.now(timezone.utc)
    rows = [("maria", "Dentist appointment for Katie", 2),
            ("david", "Renew car registration", 9),
            ("maria", "Parent-teacher conference", 5),
            ("david", "Change HVAC filter", 14),
            ("tyler", "Return library books", 3)]
    for user, msg, days in rows:
        create_reminder(user, msg, (now + timedelta(days=days)).isoformat())
        _bump("reminders")


def seed_schedules():
    from apps.schedules import data as schedules
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [("Trash & recycling", "david", "home", "weekly", "07:00"),
            ("Mow the lawn", "tyler", "home", "weekly", "09:00"),
            ("Water the plants", "katie", "home", "weekly", "18:00"),
            ("Family game night", "maria", "family", "weekly", "19:00")]
    for title, by, cat, rec, tod in rows:
        schedules.create_schedule(title, by, category=cat, assigned_to=by,
                                  recurrence_type=rec, time_of_day=tod, start_date=today)
        _bump("schedules")


SEEDERS = {"members": seed_members, "lists": seed_lists, "auto": seed_auto,
           "chores": seed_chores, "meals": seed_meals, "recipes": seed_recipes,
           "reminders": seed_reminders, "schedules": seed_schedules}


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed mock data for a box-2/demo install.")
    ap.add_argument("--members-only", action="store_true")
    ap.add_argument("--only", help="comma-separated app subset (e.g. lists,auto)")
    args = ap.parse_args()

    seed_members()
    if args.members_only:
        print(f"members: {_counts.get('members', 0)} created"); return 0
    todo = (args.only.split(",") if args.only else [k for k in SEEDERS if k != "members"])
    for app in todo:
        fn = SEEDERS.get(app.strip())
        if not fn:
            continue
        try:
            fn()
            print(f"  ✓ {app}")
        except Exception as e:
            print(f"  ✗ {app}: {type(e).__name__}: {e}")
    print("\n=== seeded ===")
    for k, v in sorted(_counts.items()):
        print(f"  {k:16} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
