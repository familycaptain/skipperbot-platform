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
# The operator logs in as `admin`. The platform is heavily per-user (To-Do,
# Reminders, "My Goals", Prioritize backlog all show only the logged-in user's
# items), so admin MUST own some of everything or every personal view reads empty.
EVERYONE = ["admin"] + FAMILY

# Standard test-box logins: password = username + "1234" (NON-SECRET throwaway creds
# for disposable test machines). Every HUMAN carries `member`; only the bot user
# `skipper` (init_db) is `bot`. `admin` is the operator/owner.
MEMBERS = [
    ("admin", "Admin", "member,admin,primary"),
    ("david", "David", "member,parent,admin"),   # a parent who's also a household admin
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
        add_todo_item(EVERYONE[i % len(EVERYONE)], text); _bump("todo_items")


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
        create_reminder(EVERYONE[i % len(EVERYONE)], m, _dt(1 + i)); _bump("reminders")


def seed_schedules():
    from apps.schedules import data as schedules
    rows = [("Trash & recycling", "home"), ("Mow the lawn", "home"), ("Water plants", "home"),
            ("Family game night", "family"), ("Date night", "family"), ("Soccer practice", "kids"),
            ("Piano lessons", "kids"), ("Book club", "personal"), ("Gym", "personal"),
            ("Change air filter", "home"), ("Pay rent", "home"), ("Grocery shopping", "home"),
            ("Car wash", "home"), ("Clean fish tank", "home"), ("Vacuum house", "home"), ("Laundry day", "home")]
    times = ["07:00", "09:00", "18:00", "19:30", "12:00"]
    for i, (title, cat) in enumerate(rows):
        by = EVERYONE[i % len(EVERYONE)]
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
    kid_ids = [k["id"] for k in kids]   # rotation pool: each zone's chores rotate among these
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
        chores.set_zone_members(_id(z), kid_ids)   # WITHOUT members a zone yields no assignments
        for dow in range(7):   # every day covered, so the "Today" view is never empty
            chores.create_chore(_id(z), dow, names[dow % len(names)]); _bump("chores")


def seed_goals():
    from apps.goals import store
    goals = [("Get fit by summer", "maria"), ("Renovate the kitchen", "david"),
             ("Plan family vacation", "maria"), ("Build emergency fund", "david"),
             ("Learn Spanish", "tyler"), ("Declutter the house", "maria"),
             ("Start a garden", "david"), ("Read 12 books", "katie"),
             ("Plan home maintenance", "admin"), ("Organize the finances", "admin")]
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


# --------------------------------------------------------------------------- #
# Fill-the-empty-tabs seeders (run additively via --only; they reuse existing
# members/vehicles rather than recreating them, so they won't duplicate base data).
# --------------------------------------------------------------------------- #
def _ids(schema, table):
    from app_platform.db import fetch_all_in_schema
    try:
        return [r["id"] for r in fetch_all_in_schema(schema, f"SELECT id FROM {table}")]
    except Exception as e:
        print(f"    (could not read {schema}.{table}: {type(e).__name__})")
        return []


def seed_home():
    from apps.home import data as home
    hid = lambda p: f"{p}-{uuid.uuid4().hex[:8]}"
    tasks = [("HVAC filter change", "HVAC", 90), ("Gutter cleaning", "Exterior", 180),
             ("Smoke detector test", "Safety", 30), ("Water heater flush", "Plumbing", 365),
             ("Dryer vent cleaning", "Safety", 180), ("Refrigerator coils", "Appliances", 180),
             ("Septic inspection", "Plumbing", 365), ("Lawn fertilizing", "Yard", 60),
             ("Pressure-wash deck", "Exterior", 365), ("Replace AC filter", "HVAC", 60),
             ("Chimney sweep", "Safety", 365), ("Test sump pump", "Plumbing", 90),
             ("Garage door service", "Garage", 365), ("Reseal grout", "Bathroom", 365),
             ("Clean range hood", "Kitchen", 90), ("Inspect roof", "Exterior", 365),
             ("Drain water softener", "Plumbing", 180), ("Touch up exterior paint", "Exterior", 365),
             ("Service generator", "Safety", 180), ("Flush dishwasher", "Kitchen", 90)]
    for i, (name, cat, iv) in enumerate(tasks):
        _try("home_tasks", lambda n=name, c=cat, iv=iv, i=i: home.create_task({
            "id": hid("hmt"), "name": n, "category": c, "task_type": "recurring",
            "interval_days": iv, "next_due_at": _ds(iv - (i % 30)), "created_by": "admin"}))
    issues = [("Water stain on ceiling", "Upstairs bedroom", "moderate"),
              ("Squeaky front door", "Entryway", "minor"), ("Cracked driveway", "Driveway", "minor"),
              ("Leaky faucet", "Kitchen", "moderate"), ("Loose deck board", "Deck", "moderate"),
              ("Flickering hallway light", "Hallway", "minor"), ("Slow shower drain", "Bathroom", "moderate"),
              ("Peeling garage paint", "Garage", "minor"), ("Window won't latch", "Living room", "minor"),
              ("Running toilet", "Half bath", "moderate"), ("Gutter sagging", "Exterior", "major"),
              ("AC not cooling well", "Whole house", "major"), ("Noisy garage door", "Garage", "minor"),
              ("Crack in stairwell wall", "Stairwell", "moderate"), ("Wobbly ceiling fan", "Bedroom", "minor"),
              ("Fence post leaning", "Backyard", "moderate"), ("Doorbell not working", "Entryway", "minor"),
              ("Low water pressure", "Master bath", "moderate"), ("Dead outlet", "Office", "major"),
              ("Damaged mailbox", "Curb", "minor")]
    for i, (title, loc, sev) in enumerate(issues):
        _try("home_issues", lambda t=title, l=loc, s=sev, i=i: home.create_issue({
            "id": hid("hi"), "title": t, "location": l, "severity": s,
            "date_noticed": _ds(-(i + 1) * 3), "created_by": "admin"}))


def seed_medical_extra():
    from apps.medical import data as med
    mid = lambda p: f"{p}-{uuid.uuid4().hex[:8]}"
    members = _ids("app_medical", "medical_members") or [None]
    treats = ["Physical therapy", "Allergy shots", "Inhaler routine", "Stretching regimen",
              "Wound dressing", "Eye drops", "Vitamin regimen", "Nebulizer treatment",
              "Compression therapy", "Heat therapy", "Massage therapy", "Breathing exercises"]
    for i, n in enumerate(treats):
        _try("med_treatments", lambda m=members[i % len(members)], n=n, i=i: med.create_treatment({
            "id": mid("mtr"), "member_id": m, "name": n, "interval_days": 7,
            "next_due_at": _ds(2 + i), "created_by": "admin"}))
    tests = [("Total Cholesterol", "mg/dL", None, 200), ("Glucose", "mg/dL", 70, 100),
             ("Hemoglobin A1C", "%", None, 5.7), ("Vitamin D", "ng/mL", 30, 100),
             ("TSH", "mIU/L", 0.4, 4.0), ("Iron", "ug/dL", 60, 170),
             ("HDL", "mg/dL", 40, None), ("Triglycerides", "mg/dL", None, 150)]
    test_ids = []
    for name, unit, lo, hi in tests:
        tid = mid("mlt")
        _try("med_lab_tests", lambda t=tid, n=name, u=unit, lo=lo, hi=hi: med.create_lab_test({
            "id": t, "name": n, "unit": u, "normal_min": lo, "normal_max": hi}))
        test_ids.append((tid, hi or 100))
    for i in range(20):
        tid, hi = test_ids[i % len(test_ids)]
        _try("med_lab_results", lambda m=members[i % len(members)], t=tid, v=round(hi * 0.8 + (i % 5) * 2, 1), i=i:
             med.create_lab_result({"id": mid("mlr"), "member_id": m, "lab_test_id": t,
                                    "result_date": _ds(-30 * (i % 6)), "value": v, "created_by": "admin"}))
    equips = [("Blood Pressure Monitor", "Omron"), ("Glucose Meter", "Accu-Chek"),
              ("CPAP Machine", "ResMed"), ("Nebulizer", "Philips"), ("Pulse Oximeter", "Zacurate"),
              ("Wheelchair", "Drive"), ("Hearing Aid", "Phonak"), ("Digital Thermometer", "Braun")]
    for i, (name, brand) in enumerate(equips):
        eid = mid("meq")
        _try("med_equipment", lambda e=eid, m=members[i % len(members)], n=name, b=brand:
             med.create_equipment({"id": e, "member_id": m, "name": n, "brand": b, "created_by": "admin"}))
        _try("med_equip_tasks", lambda e=eid, n=name: med.create_equip_task({
            "id": mid("meqt"), "equipment_id": e, "name": f"Calibrate {n}",
            "interval_days": 365, "next_due_at": _ds(180), "created_by": "admin"}))


def seed_auto_extra():
    from apps.auto import data as auto
    aid = lambda p: f"{p}-{uuid.uuid4().hex[:8]}"
    vids = _ids("app_auto", "vehicles")
    cond = ["good", "fair", "worn"]
    for i, v in enumerate(vids):
        for k in range(2):
            _try("auto_conditions", lambda v=v, k=k, i=i: auto.save_condition({
                "id": aid("vcon"), "vehicle_id": v, "date_recorded": _ds(-90 * k),
                "brakes": cond[(i + k) % 3], "tires": cond[(i + k + 1) % 3], "oil_life_pct": 80 - 20 * k,
                "battery": "good", "mileage_at_report": 60000 + 5000 * i + 1000 * k, "created_by": "admin"}, by="admin"))
        for k in range(2):
            _try("auto_valuations", lambda v=v, k=k, i=i: auto.save_valuation({
                "id": aid("vval"), "vehicle_id": v, "date_recorded": _ds(-180 * k),
                "private_party_value": round(20000 - 1500 * i - 1000 * k, 2),
                "trade_in_value": round(18000 - 1500 * i - 1000 * k, 2),
                "condition": "good", "source": "kbb", "created_by": "admin"}, by="admin"))


def seed_bounties_extra():
    from apps.bounties import data as bd
    # Credit balances so the Leaderboard + My Balance tabs populate.
    for name, cents in [("tyler", 4250), ("katie", 3175), ("david", 1500), ("maria", 900)]:
        for amt, note in [(cents, "Chores bonus"), (500, "Extra help"), (250, "Good grades")]:
            _try("bounty_credits", lambda u=name, a=amt, n=note: bd.credit_balance(u, a, note=n, created_by="admin"))


def seed_meals_extra():
    from apps.meals import data as meals
    comps = [("Grilled Chicken", "protein"), ("Brown Rice", "starch"), ("Broccoli", "vegetable"),
             ("Marinara Sauce", "sauce"), ("Ground Beef", "protein"), ("Mashed Potatoes", "starch"),
             ("Green Beans", "vegetable"), ("Caesar Dressing", "sauce"), ("Baked Salmon", "protein"),
             ("Quinoa", "starch"), ("Roasted Carrots", "vegetable"), ("Pesto", "sauce"),
             ("Black Beans", "protein"), ("Dinner Rolls", "starch"), ("Side Salad", "vegetable")]
    for name, ctype in comps:
        _try("meal_components", lambda n=name, c=ctype:
             meals.create_component("mcp-" + uuid.uuid4().hex[:8], n, comp_type=c, by="admin"))
    logs = ["Spaghetti Bolognese", "Sheet-pan Chicken", "Taco Tuesday", "Grilled Salmon",
            "Homemade Pizza", "Chicken Curry", "Beef Stew", "Turkey Burgers", "Fried Rice",
            "Pot Roast", "Quesadillas", "Baked Ziti", "Shrimp Scampi", "Meatloaf", "Pork Chops",
            "Soup & Grilled Cheese", "Breakfast for Dinner", "Veggie Chili", "Caesar Wraps", "BBQ Ribs"]
    types = ["dinner", "lunch", "breakfast"]
    for i, desc in enumerate(logs):
        _try("meal_logs", lambda d=desc, i=i: meals.create_meal_log(
            "mlog-" + uuid.uuid4().hex[:8], _ds(-(i + 1)), d, logged_by="admin", meal_type=types[i % 3]))


def seed_bounties_complete():
    from apps.bounties import store as bs
    from app_platform.db import fetch_all_in_schema
    try:
        rows = fetch_all_in_schema("app_bounties",
                                   "SELECT id FROM bounties WHERE status='open' ORDER BY created_at LIMIT 12")
    except Exception as e:
        print(f"    (bounties read failed: {e})"); rows = []
    kids = ["tyler", "katie"]
    for i, r in enumerate(rows):
        def go(bid=r["id"], kid=kids[i % 2]):
            bs.submit_bounty(bid, kid)          # kid claims it
            bs.approve_bounty(bid, "david")     # parent approves -> status=approved -> leaderboard + balance
        _try("bounty_completions", go)


SEEDERS = {
    "weather": seed_weather, "lists": seed_lists, "todo": seed_todo, "auto": seed_auto,
    "recipes": seed_recipes, "meals": seed_meals, "reminders": seed_reminders,
    "schedules": seed_schedules, "chores": seed_chores, "goals": seed_goals,
    "bounties": seed_bounties, "medical": seed_medical,
    # fill-empty-tabs (additive; safe to run alone via --only)
    "home": seed_home, "medical_extra": seed_medical_extra, "auto_extra": seed_auto_extra,
    "bounties_extra": seed_bounties_extra, "meals_extra": seed_meals_extra,
    "bounties_complete": seed_bounties_complete,
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
