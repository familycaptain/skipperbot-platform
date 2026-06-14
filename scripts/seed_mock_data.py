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
import sys
import uuid
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


def seed_chores():
    from apps.chores import store
    kids = []
    for name, color in [("Tyler", "#3b82f6"), ("Katie", "#ec4899")]:
        kids.append(store.create_kid(name, color=color))
        _bump("chore_kids")
    # zones + chores are best-effort (rotation semantics vary); wrap each
    for zone_name in ["Kitchen", "Bathroom", "Living Room"]:
        try:
            z = store.create_zone(zone_name, rotation_start=(kids[0].get("id") if kids else ""),
                                  description=f"{zone_name} cleanup")
            _bump("chore_zones")
            zid = z.get("id") if isinstance(z, dict) else z
            for dow, cname in [(0, "Wipe surfaces"), (3, "Sweep / vacuum"), (6, "Take out trash")]:
                store.create_chore(zid, dow, cname)
                _bump("chores")
        except Exception as e:
            print(f"    chores zone '{zone_name}': skipped ({type(e).__name__})")


def seed_meals():
    from apps.meals import store
    for name, by in [("Spaghetti Bolognese", "maria"), ("Sheet-pan chicken & veggies", "david"),
                     ("Taco Tuesday", "maria"), ("Veggie stir-fry", "tyler"),
                     ("Grilled salmon & rice", "david")]:
        try:
            store.create_meal("meal-" + uuid.uuid4().hex[:8], name, by)
            _bump("meals")
        except Exception as e:
            print(f"    meal '{name}': skipped ({type(e).__name__})")


SEEDERS = {"members": seed_members, "lists": seed_lists, "auto": seed_auto,
           "chores": seed_chores, "meals": seed_meals}


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
