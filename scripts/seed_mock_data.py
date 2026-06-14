#!/usr/bin/env python
"""Seed realistic MOCK data for box-2 / demos (EVOLVE.md §13).

Run inside the platform container:

    docker compose exec agent python scripts/seed_mock_data.py
    docker compose exec agent python scripts/seed_mock_data.py --only lists,auto
    docker compose exec agent python scripts/seed_mock_data.py --members-only

Goal: ~20 records per section across the apps, so a fresh box looks fully lived-in.
Deterministic-ish (hardcoded pools + index variation, no AI at runtime) and resilient:
each app is seeded in its own try/except with a per-app summary, so one app's failure
doesn't abort the rest. Calls the apps' real store functions, so ids/FKs/events are
correct. This is a MOCK family for a throwaway box — not anyone's real household.
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

NOW = datetime.now(timezone.utc)
ADULTS = ["david", "maria"]
KIDS = ["tyler", "katie"]
FAMILY = ADULTS + KIDS

# Standard test-box logins: password = username + "1234" (NON-SECRET throwaway creds
# for disposable test machines). Every HUMAN carries `member`; only the bot user
# `skipper` (init_db) is `bot`. `admin` is the operator/owner.
MEMBERS = [
    ("admin", "Admin", "member,admin,primary"),
    ("david", "David", "member,parent"),
    ("maria", "Maria", "member,parent"),
    ("tyler", "Tyler", "member"),
    ("katie", "Katie", "member"),
]
_counts: dict[str, int] = {}


def _pw(name):
    return name + "1234"


def _bump(k, n=1):
    _counts[k] = _counts.get(k, 0) + n


def _ds(days):
    return (NOW + timedelta(days=days)).date().isoformat()


def _dt(days):
    return (NOW + timedelta(days=days)).isoformat()


def _id(rec):
    return rec.get("id") if isinstance(rec, dict) else rec


def _try(label, fn):
    try:
        fn(); _bump(label)
    except Exception as e:
        print(f"    {label}: {type(e).__name__}: {str(e)[:70]}")


# --------------------------------------------------------------------------- #
def seed_members():
    from data_layer.users import create_user, get_user, update_password, update_role
    for name, display, role in MEMBERS:
        if get_user(name):
            update_password(name, _pw(name)); update_role(name, role); _bump("members_synced")
        else:
            create_user(name, display, password=_pw(name), role=role); _bump("members")


def cleanup_stale():
    """Hide the placeholder kid1/2/3 shipped by the chores seed migration."""
    from app_platform.db import execute_in_schema
    try:
        n = execute_in_schema("app_chores", "UPDATE kids SET active=FALSE WHERE user_id IN ('kid1','kid2','kid3')")
        _bump("stale_kids_hidden", n or 0)
    except Exception as e:
        print(f"    cleanup: {type(e).__name__}: {e}")


def seed_weather():
    from app_platform import settings
    settings.set("default_zip", "78704", scope="platform")   # so weather renders out of the box
    _bump("weather_zip")


def seed_lists():
    from apps.lists import store
    pool = {
        "Groceries": ["Milk", "Eggs", "Sourdough", "Bananas", "Chicken thighs", "Coffee",
                      "Spinach", "Greek yogurt", "Olive oil", "Cheddar", "Apples", "Pasta"],
        "Costco Run": ["Rotisserie chicken", "Paper plates", "Laundry pods", "Trash bags",
                       "Frozen berries", "Paper towels", "Batteries", "Granola bars"],
        "Hardware Store": ["Deck screws", "Wood glue", "Sandpaper", "White paint", "Furnace filter", "Caulk"],
        "Beach Trip Packing": ["Sunscreen", "Beach towels", "Swimsuits", "Cooler", "Chargers", "First-aid kit", "Snacks"],
        "Weekend Projects": ["Fix gate latch", "Mulch beds", "Clean gutters", "Porch bulb", "Touch-up paint"],
        "Birthday Party": ["Balloons", "Cake", "Candles", "Goodie bags", "Plates", "Pizza", "Juice boxes"],
        "Camping Gear": ["Tent", "Sleeping bags", "Lantern", "Bug spray", "Marshmallows", "Firewood"],
        "Back to School": ["Backpacks", "Notebooks", "Pencils", "Lunchboxes", "Sneakers", "Folders"],
        "Pharmacy": ["Allergy meds", "Band-aids", "Toothpaste", "Vitamins", "Sunscreen"],
        "Pet Supplies": ["Dog food", "Treats", "Poop bags", "Flea meds", "Chew toy"],
        "Holiday Shopping": ["Gift for Grandma", "Wrapping paper", "Stocking stuffers", "Cards", "Lights"],
        "Garden": ["Tomato seedlings", "Potting soil", "Mulch", "Fertilizer", "Gloves"],
        "Car Maintenance": ["Wiper blades", "Air filter", "Coolant", "Wax", "Tire gauge"],
        "Date Night Ideas": ["Italian downtown", "Live music", "Mini golf", "New bistro", "Drive-in movie"],
        "Home Repairs": ["Leaky faucet", "Squeaky door", "Loose tile", "Replace smoke detector"],
        "Meal Prep": ["Overnight oats", "Chicken bowls", "Cut veggies", "Boil eggs", "Cook rice"],
    }
    members = FAMILY
    for i, (name, items) in enumerate(pool.items()):
        lst = store.create_list(name, members[i % len(members)]); _bump("lists")
        for text in items:
            store.add_item(lst["id"], text, members[i % len(members)]); _bump("list_items")


def seed_todo():
    from apps.todo.tools import add_todo_item
    items = ["Call the dentist", "Reply to teacher email", "Pay water bill", "Schedule oil change",
             "RSVP to wedding", "Renew library card", "Book flights", "Update resume",
             "Fix bike tire", "Order printer ink", "Return Amazon package", "Clean garage",
             "Water plants", "Walk the dog", "Meal plan for week", "Charge camera battery",
             "Back up photos", "Cancel free trial", "Mail birthday card", "Defrost chicken"]
    for i, text in enumerate(items):
        add_todo_item(FAMILY[i % len(FAMILY)], text); _bump("todo_items")


def seed_auto():
    from apps.auto import tools
    specs = [("david", "Honda", "Odyssey", 2019, "Silver", 68000), ("maria", "Toyota", "RAV4", 2021, "Blue", 31000),
             ("tyler", "Subaru", "Outback", 2015, "Green", 121000), ("david", "Ford", "F-150", 2018, "Black", 89000),
             ("maria", "Tesla", "Model 3", 2022, "White", 24000), ("david", "Jeep", "Wrangler", 2016, "Red", 78000)]
    svc_types = ["Oil Change", "Tire Rotation", "Brake Pads", "State Inspection", "Air Filter",
                 "Coolant Flush", "Battery Replacement", "Wiper Blades"]
    shops = ["QuickLube", "Discount Tire", "Midas", "Local Garage", "Dealership"]
    issues = ["Check-engine light on cold start", "Window slow to roll up", "Brake squeal",
              "AC not cold", "Rattle over bumps", "Tire pressure warning", "Wiper streaking"]
    for vi, (by, mk, md, yr, col, odo) in enumerate(specs):
        vid = tools.create_vehicle(created_by=by, make=mk, model=md, year=yr, color=col,
                                   odometer=odo, license_plate=f"MOCK-{1000 + vi}"); _bump("vehicles")
        for s in range(4):                       # ~24 service records total
            tools.log_service(vid, svc_types[(vi + s) % len(svc_types)], by,
                              date_performed=_ds(-30 * (s + 1)), odometer_at_service=odo - 1500 * (s + 1),
                              cost=round(35 + 60 * s + 12.5, 2), shop_name=shops[(vi + s) % len(shops)])
            _bump("service_records")
        for s in range(2):                       # ~12 issues
            _try("vehicle_issues", lambda v=vid, b=by, t=issues[(vi + s) % len(issues)]:
                 tools.report_vehicle_issue(v, t, b))


def seed_recipes():
    from apps.recipes import tools
    names = ["Weeknight Salsa", "Banana Bread", "Chicken Tikka Masala", "Margherita Pizza",
             "Beef Tacos", "Veggie Stir-Fry", "Spaghetti Carbonara", "Grilled Salmon",
             "Caesar Salad", "Pancakes", "Chili con Carne", "Lemon Chicken", "Pad Thai",
             "Mushroom Risotto", "BBQ Pulled Pork", "Greek Gyros", "Shepherd's Pie",
             "Fish Tacos", "Caprese Salad", "Apple Crisp", "French Toast", "Minestrone Soup"]
    cats = [["dinner"], ["baking"], ["indian"], ["italian"], ["mexican"], ["vegetarian"]]
    for i, title in enumerate(names):
        by = FAMILY[i % len(FAMILY)]
        ings = json.dumps([{"item": x, "quantity": str(q + 1), "unit": u}
                           for q, (x, u) in enumerate([("main ingredient", "lb"), ("onion", "cup"),
                                                       ("garlic", "clove"), ("seasoning", "tbsp")])])
        steps = json.dumps(["Prep ingredients", "Cook per method", "Season to taste", "Serve"])
        tools.create_recipe(title, by, ingredients=ings, steps=steps,
                            categories=json.dumps(cats[i % len(cats)]),
                            prep_time_min=10 + i % 20, cook_time_min=15 + i % 40, servings=2 + i % 6)
        _bump("recipes")


def seed_meals():
    from apps.meals import data as meals
    names = ["Spaghetti Bolognese", "Sheet-pan Chicken", "Taco Tuesday", "Veggie Stir-Fry",
             "Grilled Salmon", "Homemade Pizza", "Chicken Curry", "Beef Stew", "Breakfast for Dinner",
             "Turkey Burgers", "Fried Rice", "Pot Roast", "Quesadillas", "Baked Ziti", "Chicken Caesar Wraps",
             "Shrimp Scampi", "Meatloaf", "Veggie Chili", "Pork Chops", "Soup & Grilled Cheese"]
    efforts = ["easy", "medium", "hard"]
    for i, name in enumerate(names):
        meals.create_meal("meal-" + uuid.uuid4().hex[:8], name, FAMILY[i % len(FAMILY)],
                         effort=efforts[i % 3], tags=[["weeknight"], ["family"], ["quick"]][i % 3],
                         prep_time_min=10 + i % 25, cook_time_min=15 + i % 35)
        _bump("meals")


def seed_reminders():
    from apps.reminders.store import create_reminder
    msgs = ["Dentist appointment", "Renew car registration", "Parent-teacher conference",
            "Change HVAC filter", "Return library books", "Pay credit card", "Call grandma",
            "Pick up dry cleaning", "Vet appointment for the dog", "Submit expense report",
            "Order birthday cake", "Schedule physical", "Water the plants", "Take out recycling",
            "Renew passport", "Book summer camp", "Refill prescription", "Oil change due",
            "Send thank-you notes", "Update car insurance"]
    for i, m in enumerate(msgs):
        create_reminder(FAMILY[i % len(FAMILY)], m, _dt(1 + i)); _bump("reminders")


def seed_schedules():
    from apps.schedules import data as schedules
    rows = [("Trash & recycling", "home"), ("Mow the lawn", "home"), ("Water plants", "home"),
            ("Family game night", "family"), ("Date night", "family"), ("Soccer practice", "kids"),
            ("Piano lessons", "kids"), ("Book club", "personal"), ("Gym", "personal"),
            ("Change air filter", "home"), ("Pay rent", "home"), ("Grocery shopping", "home"),
            ("Car wash", "home"), ("Clean fish tank", "home"), ("Vacuum house", "home"), ("Laundry day", "home")]
    times = ["07:00", "09:00", "18:00", "19:30", "12:00"]
    for i, (title, cat) in enumerate(rows):
        by = FAMILY[i % len(FAMILY)]
        schedules.create_schedule(title, by, category=cat, assigned_to=by,
                                 recurrence_type="weekly", time_of_day=times[i % len(times)], start_date=_ds(0))
        _bump("schedules")


def seed_chores():
    from apps.chores import data as chores
    existing = {k.get("name"): k for k in chores.list_kids(active_only=False)}
    kids = []
    for name, color in [("Tyler", "#3b82f6"), ("Katie", "#ec4899")]:
        kids.append(existing.get(name) or chores.create_kid(name, color=color))
        if name not in existing:
            _bump("chore_kids")
    start = _ds(0)
    zone_chores = {
        "Kitchen": ["Wipe counters", "Load dishwasher", "Sweep floor", "Take out trash"],
        "Bathrooms": ["Clean sink", "Scrub toilet", "Wipe mirror", "Restock TP"],
        "Living Room": ["Vacuum", "Dust shelves", "Tidy toys", "Fluff cushions"],
        "Bedrooms": ["Make beds", "Put away laundry", "Vacuum", "Clear surfaces"],
        "Yard": ["Water plants", "Pull weeds", "Sweep porch", "Feed the dog"],
        "Garage": ["Sweep", "Organize tools", "Take out recycling"],
    }
    for zone, names in zone_chores.items():
        z = chores.create_zone(zone, start, description=f"{zone} weekly cleanup"); _bump("chore_zones")
        for dow, cname in enumerate(names):
            chores.create_chore(_id(z), dow % 7, cname); _bump("chores")


def seed_goals():
    from apps.goals import store
    goals = [("Get fit by summer", "maria"), ("Renovate the kitchen", "david"),
             ("Plan family vacation", "maria"), ("Build emergency fund", "david"),
             ("Learn Spanish", "tyler"), ("Declutter the house", "maria"),
             ("Start a garden", "david"), ("Read 12 books", "katie")]
    proj_names = ["Phase 1: Planning", "Phase 2: Execution", "Wrap-up"]
    task_names = ["Research options", "Set a budget", "Make a timeline", "Do the work", "Review progress"]
    for gname, by in goals:
        g = store.create_goal(gname, by, description=f"Goal: {gname}", target_date=_ds(90)); _bump("goals")
        gid = _id(g)
        for p in range(2):
            pr = store.create_project(gid, proj_names[p], by, due_date=_ds(30 * (p + 1))); _bump("projects")
            pid = _id(pr)
            for t in range(3):                  # ~ 8*2*3 = 48 tasks
                _try("tasks", lambda pi=pid, n=task_names[t % len(task_names)], b=by:
                     store.create_task(pi, n, b, assigned_to=[b], due_date=_ds(7 * (t + 1))))


def seed_bounties():
    from apps.bounties.tools import create_bounty
    rows = [("Mow the lawn", 1500, "Yard"), ("Wash the car", 1000, "Yard"), ("Clean the garage", 2000, "Garage"),
            ("Fold all laundry", 500, "Indoor"), ("Vacuum whole house", 800, "Indoor"), ("Weed the garden", 1200, "Yard"),
            ("Wash all windows", 1500, "Indoor"), ("Organize the pantry", 700, "Kitchen"), ("Rake the leaves", 1000, "Yard"),
            ("Deep-clean a bathroom", 1000, "Indoor"), ("Walk the dog 7 days", 1400, "Pets"), ("Sweep the patio", 400, "Yard"),
            ("Clean out the fridge", 600, "Kitchen"), ("Dust the whole house", 800, "Indoor"), ("Shovel snow", 1500, "Yard"),
            ("Wash the dishes a week", 1200, "Kitchen"), ("Help with groceries", 500, "Errands"), ("Clean baseboards", 700, "Indoor"),
            ("Wash the dog", 800, "Pets"), ("Tidy the playroom", 500, "Indoor")]
    for title, cents, cat in rows:
        create_bounty(title, cents, "david", category=cat, description=f"{title} — earn ${cents/100:.2f}")
        _bump("bounties")


def seed_medical():
    from apps.medical import data as med
    # Every medical record requires a caller-supplied `id` (uuid) + exact field names.
    mid = lambda: uuid.uuid4().hex[:12]
    pats = {}
    for name, notes in [("David", "Adult"), ("Maria", "Adult"),
                        ("Tyler", "Penicillin allergy"), ("Katie", "Asthma")]:
        rec = med.create_member({"id": mid(), "name": name, "notes": notes, "created_by": "admin"})
        if rec:
            pats[name] = rec["id"]; _bump("med_members")
    ids = list(pats.values()) or [mid()]
    docs = ["Dr. Patel", "Dr. Nguyen", "Dr. Garcia", "Dr. Smith"]
    meds = ["Amoxicillin", "Ibuprofen", "Lisinopril", "Albuterol", "Metformin", "Vitamin D",
            "Loratadine", "Omeprazole", "Atorvastatin", "Cetirizine", "Melatonin", "Fluoxetine",
            "Amlodipine", "Levothyroxine", "Sertraline"]
    for i, n in enumerate(meds):
        _try("med_medications", lambda m=ids[i % len(ids)], n=n, i=i:
             med.create_medication({"id": mid(), "member_id": m, "name": n,
                                    "dosage_notes": "1 tablet daily", "prescriber": docs[i % len(docs)],
                                    "pharmacy": "Corner Pharmacy", "start_date": _ds(-30), "created_by": "admin"}))
    appts = ["Annual physical", "Dental cleaning", "Eye exam", "Dermatology", "Pediatric checkup",
             "Flu shot", "Allergy follow-up", "Orthodontist", "Cardiology consult", "Lab work",
             "Therapy session", "Vaccination", "Sports physical", "Skin check", "Wellness visit",
             "Bloodwork", "Vision screening", "Hearing test", "Nutrition consult", "Physical therapy"]
    for i, t in enumerate(appts):
        _try("med_appointments", lambda m=ids[i % len(ids)], t=t, i=i:
             med.create_appointment({"id": mid(), "member_id": m, "title": t,
                                     "appointment_at": _dt(3 + i), "provider": docs[i % len(docs)],
                                     "location": "Family Clinic", "appointment_type": "visit", "created_by": "admin"}))
    events = ["Broke arm (skateboard)", "Strep throat", "Allergy flare", "Routine bloodwork",
              "Stitches on chin", "Ear infection", "Sprained ankle", "Annual checkup",
              "Migraine", "Cold/flu", "Wisdom teeth removed", "Eye exam - new glasses",
              "Tetanus booster", "Sports injury", "Dental filling", "Vision check"]
    for i, t in enumerate(events):
        _try("med_events", lambda m=ids[i % len(ids)], t=t, i=i:
             med.create_event({"id": mid(), "member_id": m, "event_type": "visit", "title": t,
                               "event_date": _ds(-14 * (i + 1)), "provider": docs[i % len(docs)],
                               "summary": t, "created_by": "admin"}))


SEEDERS = {
    "weather": seed_weather, "lists": seed_lists, "todo": seed_todo, "auto": seed_auto,
    "recipes": seed_recipes, "meals": seed_meals, "reminders": seed_reminders,
    "schedules": seed_schedules, "chores": seed_chores, "goals": seed_goals,
    "bounties": seed_bounties, "medical": seed_medical,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed ~20 mock records/section for a box-2/demo install.")
    ap.add_argument("--members-only", action="store_true")
    ap.add_argument("--only", help="comma-separated app subset (e.g. goals,bounties)")
    args = ap.parse_args()

    seed_members()
    cleanup_stale()
    if args.members_only:
        print("members synced."); return 0
    todo = (args.only.split(",") if args.only else list(SEEDERS))
    for app in todo:
        fn = SEEDERS.get(app.strip())
        if not fn:
            continue
        try:
            fn(); print(f"  ✓ {app}")
        except Exception as e:
            print(f"  ✗ {app}: {type(e).__name__}: {e}")
    print("\n=== seeded ===")
    for k, v in sorted(_counts.items()):
        print(f"  {k:18} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
