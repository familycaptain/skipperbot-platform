# Auto Maintenance — Tool Guide

## Overview
Track household vehicles, service history, issues, valuations, and condition reports.
Users will ask about oil changes, tire rotations, vehicle value, upcoming maintenance, etc.

## Available Tools

### Vehicles
- `create_vehicle` — add a new vehicle
- `get_vehicle` — get vehicle details
- `list_vehicles` — list all vehicles with summary
- `update_vehicle` — update vehicle info (name, odometer, etc.)
- `delete_vehicle` — remove a vehicle and all records

### Service Records
- `log_service` — record an oil change, tire rotation, brake job, etc. Auto-creates reminders if next_due_date is set. **Oil changes with mileage auto-create mileage tracking** (next due at current + 5,000 mi, 3-month cooldown).
- `get_vehicle_history` — full service timeline for a vehicle
- `search_service_records` — search across all vehicles
- `update_service_record` — edit an existing service record (fix typos, add cost, change date, etc.)
- `delete_service_record` — remove a service record permanently
- `get_upcoming_maintenance` — what's due soon across all vehicles
- `report_mileage` — enter current mileage to check oil change status. Updates vehicle odometer and evaluates if oil change is due.

### Oil Change Tracking
- `setup_oil_tracking` — manually configure mileage-based oil change tracking (use when not set up via log_service, e.g. for existing vehicles). Requires current odometer at last oil change.
- `update_oil_tracking` — change the mileage interval or cooldown months for an existing tracking setup.

### Recurring Maintenance Schedules
- `create_maintenance_schedule` — create a new recurring maintenance item linked to a vehicle (e.g. "Wax headlights" yearly). Recurrence options: "yearly", "monthly", "quarterly", "biweekly", "weekly", or "interval" (with interval_days). Specify first_due_date (YYYY-MM-DD) for the first occurrence. Returns a sch-* ID.
- `complete_maintenance` — mark an existing recurring schedule as done; advances next_due and logs a service record. Requires a real sch-* ID from get_upcoming_maintenance or create_maintenance_schedule.
- `get_vehicle_maintenance` — list all recurring maintenance schedules for a specific vehicle with their sch-* IDs.
- `delete_maintenance_schedule` — remove a recurring maintenance schedule permanently.

**Pattern for "user just did something, create a yearly reminder":**
1. `create_maintenance_schedule(vehicle_id, title, created_by, recurrence="yearly", first_due_date="<today>")`
2. `complete_maintenance(schedule_id="<sch-id from step 1>", vehicle_id, ...)` — logs today's completion, advances next_due by one year.

**CRITICAL — Check before creating:** Before calling `create_maintenance_schedule`, ALWAYS call `get_vehicle_maintenance(vehicle_id)` first. If an existing schedule already matches what the user did (same action, even if the title uses a different phrase — e.g. "Start the Elantra" = "start kid1's car"), complete THAT schedule with `complete_maintenance` instead of creating a new one. Never create a duplicate schedule for something already tracked.

### Issues
- `report_vehicle_issue` — log a problem (paint damage, windshield nick, check engine light, etc.)
- `update_vehicle_issue` — update status, mark as fixed, add fix details
- `list_vehicle_issues` — list open issues (all vehicles or one)
- `delete_vehicle_issue` — remove an issue permanently

### Valuations
- `log_vehicle_valuation` — record blue book values (private party + trade-in)
- `get_vehicle_valuations` — value history for a vehicle
- `delete_vehicle_valuation` — remove a valuation record permanently

### Condition Reports
- `log_vehicle_condition` — periodic snapshot of brakes, tires, battery, exterior, interior, etc.
- `get_vehicle_conditions` — condition history
- `get_latest_vehicle_condition` — most recent snapshot

## Important Rules

1. **Always search first** — if the user asks about a vehicle by name, use `list_vehicles` to find the ID before acting.
2. **Parse service details** — when the user says "I got an oil change today at Jiffy Lube, $45, truck is at 62,000 miles", extract: service_type="Oil Change", shop_name="Jiffy Lube", cost=45, odometer_at_service=62000.
3. **Auto-reminders** — when logging a service, ask if there's a next due date. Oil changes are typically every 5,000 miles or 6 months. Set next_due_date accordingly.
9. **Oil change tracking** — when logging an oil change with mileage, mileage-based tracking is auto-created (default: every 5,000 mi, 3-month cooldown). After cooldown, the nag will prompt the user monthly to enter mileage via `report_mileage`. If the user mentions their current mileage for a vehicle, use `report_mileage` to record it.
4. **Open the app** — after creating a vehicle, call `open_app(app_type="auto-vehicle", autoVehicleId="<id>")`. After listing vehicles, call `open_app(app_type="auto")`.
5. **Infer severity** — "check engine light" is major, "small scratch" is minor, "brakes grinding" is critical.
6. **Condition defaults** — if the user gives a partial condition report, use "good" for unmentioned components.
7. **Valuation source** — default to "kbb" unless the user specifies another source.
8. **Update odometer** — when logging a service or condition with mileage, the vehicle odometer is auto-updated.
