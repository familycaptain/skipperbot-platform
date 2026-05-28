> **DEPRECATED** — Moved to `apps/auto/guide.md` (app package).
> This file is no longer loaded. Safe to delete.

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
- `log_service` — record an oil change, tire rotation, brake job, etc. Auto-creates reminders if next_due_date is set.
- `get_vehicle_history` — full service timeline for a vehicle
- `search_service_records` — search across all vehicles
- `get_upcoming_maintenance` — what's due soon across all vehicles

### Issues
- `report_vehicle_issue` — log a problem (paint damage, windshield nick, check engine light, etc.)
- `update_vehicle_issue` — update status, mark as fixed, add fix details
- `list_vehicle_issues` — list open issues (all vehicles or one)

### Valuations
- `log_vehicle_valuation` — record blue book values (private party + trade-in)
- `get_vehicle_valuations` — value history for a vehicle

### Condition Reports
- `log_vehicle_condition` — periodic snapshot of brakes, tires, battery, exterior, interior, etc.
- `get_vehicle_conditions` — condition history
- `get_latest_vehicle_condition` — most recent snapshot

## Important Rules

1. **Always search first** — if the user asks about a vehicle by name, use `list_vehicles` to find the ID before acting.
2. **Parse service details** — when the user says "I got an oil change today at Jiffy Lube, $45, truck is at 62,000 miles", extract: service_type="Oil Change", shop_name="Jiffy Lube", cost=45, odometer_at_service=62000.
3. **Auto-reminders** — when logging a service, ask if there's a next due date. Oil changes are typically every 5,000 miles or 6 months. Set next_due_date accordingly.
4. **Open the app** — after creating a vehicle, call `open_app(app_type="auto-vehicle", autoVehicleId="<id>")`. After listing vehicles, call `open_app(app_type="auto")`.
5. **Infer severity** — "check engine light" is major, "small scratch" is minor, "brakes grinding" is critical.
6. **Condition defaults** — if the user gives a partial condition report, use "good" for unmentioned components.
7. **Valuation source** — default to "kbb" unless the user specifies another source.
8. **Update odometer** — when logging a service or condition with mileage, the vehicle odometer is auto-updated.
