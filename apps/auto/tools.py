"""
Auto Maintenance Tools — Track vehicles, service records, issues, valuations, and conditions.
All vehicles are stored as veh-* entities with service history, issue tracking, value tracking,
and periodic condition reports.
"""

import uuid
from datetime import date

from config import logger
from apps.auto import data as _dl


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def _build_name(year=0, make="", model="", trim_level="", color=""):
    parts = []
    if year and year > 0:
        parts.append(str(year))
    if make:
        parts.append(make.strip())
    if model:
        parts.append(model.strip())
    if trim_level:
        parts.append(trim_level.strip())
    if color:
        parts.append(color.strip())
    return " ".join(parts) or "New Vehicle"


def create_vehicle(
    created_by: str,
    make: str = "",
    model: str = "",
    trim_level: str = "",
    year: int = 0,
    color: str = "",
    vin: str = "",
    license_plate: str = "",
    odometer: int = 0,
    owner: str = "",
    notes: str = "",
) -> str:
    """Create a new vehicle to track maintenance for.

    After creating, ALWAYS call open_app(app_type="auto-vehicle", autoVehicleId="<the_id>")
    to open the vehicle detail view.

    The display name is auto-generated from year, make, model, trim_level, and color.

    Args:
        created_by: Who is creating it (a person's name).
        make: Vehicle make (e.g. "Ford", "Honda").
        model: Vehicle model (e.g. "F-150", "Civic").
        trim_level: Trim level (e.g. "SL", "EX-L", "XLT").
        year: Model year (e.g. 2021). 0 = not specified.
        color: Exterior color (e.g. "White", "Pearl Black").
        vin: VIN number (optional).
        license_plate: License plate (optional).
        odometer: Current odometer reading. 0 = not specified.
        owner: Vehicle owner (a person's name). Gets escalation notifications. Empty = defaults to created_by.
        notes: Additional notes.

    Returns:
        Confirmation with vehicle ID.

    Ack: Adding vehicle...
    """
    try:
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        name = _build_name(year, make, model, trim_level, color)
        veh_id = f"veh-{uuid.uuid4().hex[:8]}"
        vehicle = {
            "id": veh_id,
            "name": name,
            "make": make.strip() if make else "",
            "model": model.strip() if model else "",
            "trim_level": trim_level.strip() if trim_level else "",
            "year": year if year > 0 else None,
            "color": color.strip() if color else "",
            "vin": vin.strip() if vin else "",
            "license_plate": license_plate.strip() if license_plate else "",
            "odometer": odometer if odometer > 0 else None,
            "owner": owner.strip() if owner else "",
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip(),
        }

        _dl.save_vehicle(vehicle)
        logger.info("AUTO: Created vehicle '%s' (%s) by %s", name, veh_id, created_by.strip())

        return (
            f"Vehicle created: '{name}' ({veh_id})\n"
            f"Now call open_app(app_type=\"auto-vehicle\", autoVehicleId=\"{veh_id}\") to open it."
        )

    except Exception as e:
        return f"Error in create_vehicle: {str(e)}"


def get_vehicle(vehicle_id: str) -> str:
    """Get full details of a vehicle.

    Args:
        vehicle_id: The vehicle ID (e.g. "veh-abc12345").

    Returns:
        Formatted vehicle details.

    Ack: Loading vehicle...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        if not vehicle:
            return f"Error: Vehicle '{vehicle_id}' not found."

        return _format_vehicle(vehicle)

    except Exception as e:
        return f"Error in get_vehicle: {str(e)}"


def list_vehicles() -> str:
    """List all tracked vehicles with summary info.

    Returns:
        Formatted list of vehicles.

    Ack: Listing vehicles...
    """
    try:
        vehicles = _dl.get_all_vehicles()
        if not vehicles:
            return "No vehicles tracked yet."

        lines = [f"Vehicles ({len(vehicles)}):\n"]
        for v in vehicles:
            yr = f"{v['year']} " if v.get("year") else ""
            odo = f" | {v['odometer']:,} mi" if v.get("odometer") else ""
            summary = _dl.get_vehicle_summary(v["id"])
            issues = f" | {summary['open_issue_count']} open issue(s)" if summary.get("open_issue_count") else ""
            next_svc = ""
            if summary.get("next_service") and summary["next_service"].get("next_due_date"):
                next_svc = f" | Next: {summary['next_service']['service_type']} due {summary['next_service']['next_due_date']}"
            lines.append(f"- {yr}{v['name']} ({v['id']}){odo}{issues}{next_svc}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_vehicles: {str(e)}"


def update_vehicle(
    vehicle_id: str,
    make: str = "",
    model: str = "",
    trim_level: str = "",
    year: int = -1,
    color: str = "",
    vin: str = "",
    license_plate: str = "",
    odometer: int = -1,
    owner: str = "",
    notes: str = "",
) -> str:
    """Update a vehicle. Only provided fields are changed.

    The display name is auto-regenerated from the component fields.

    Args:
        vehicle_id: The vehicle to update.
        make: New make (empty = keep current).
        model: New model (empty = keep current).
        trim_level: New trim level (empty = keep current).
        year: New year (-1 = keep current, 0 = clear).
        color: New color (empty = keep current).
        vin: New VIN (empty = keep current).
        license_plate: New plate (empty = keep current).
        odometer: New odometer (-1 = keep current).
        owner: New owner (empty = keep current).
        notes: New notes (empty = keep current).

    Returns:
        Confirmation of update.

    Ack: Updating vehicle {vehicle_id}...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        updates = {}
        if make: updates["make"] = make.strip()
        if model: updates["model"] = model.strip()
        if trim_level: updates["trim_level"] = trim_level.strip()
        if year >= 0: updates["year"] = year if year > 0 else None
        if color: updates["color"] = color.strip()
        if vin: updates["vin"] = vin.strip()
        if license_plate: updates["license_plate"] = license_plate.strip()
        if odometer >= 0: updates["odometer"] = odometer if odometer > 0 else None
        if owner: updates["owner"] = owner.strip()
        if notes: updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."

        # Auto-regenerate name from component fields
        current = _dl.get_vehicle(vehicle_id.strip())
        if not current:
            return f"Error: Vehicle '{vehicle_id}' not found."
        merged = {**current, **updates}
        updates["name"] = _build_name(
            merged.get("year") or 0, merged.get("make", ""),
            merged.get("model", ""), merged.get("trim_level", ""),
            merged.get("color", ""),
        )

        success = _dl.update_vehicle(vehicle_id.strip(), updates)
        if success:
            fields = ", ".join(k for k in updates.keys() if k != "name")
            return f"Vehicle {vehicle_id} updated. Changed: {fields}"
        return f"Error: Vehicle '{vehicle_id}' not found."

    except Exception as e:
        return f"Error in update_vehicle: {str(e)}"


def delete_vehicle(vehicle_id: str) -> str:
    """Delete a vehicle and all its records permanently.

    Args:
        vehicle_id: The vehicle to delete.

    Returns:
        Confirmation or error.

    Ack: Deleting vehicle {vehicle_id}...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        success = _dl.delete_vehicle(vehicle_id.strip())
        if success:
            return f"Vehicle '{vehicle_id}' and all associated records deleted."
        return f"Error: Vehicle '{vehicle_id}' not found."

    except Exception as e:
        return f"Error in delete_vehicle: {str(e)}"


# ---------------------------------------------------------------------------
# Service Records
# ---------------------------------------------------------------------------

def log_service(
    vehicle_id: str,
    service_type: str,
    created_by: str,
    date_performed: str = "",
    odometer_at_service: int = 0,
    cost: float = 0.0,
    shop_name: str = "",
    description: str = "",
    next_due_date: str = "",
    next_due_mileage: int = 0,
    notes: str = "",
) -> str:
    """Log a service record for a vehicle. Optionally creates a reminder for next due date.

    Args:
        vehicle_id: The vehicle ID.
        service_type: Type of service (e.g. "Oil Change", "Tire Rotation", "Brake Pads", "Inspection").
        created_by: Who is logging it.
        date_performed: When done (YYYY-MM-DD). Empty = today.
        odometer_at_service: Mileage at time of service. 0 = not specified.
        cost: Cost in dollars. 0 = not specified.
        shop_name: Where it was done (or "DIY").
        description: Details of what was done.
        next_due_date: When the service should be done again (YYYY-MM-DD). Empty = none.
        next_due_mileage: At what mileage. 0 = not specified.
        notes: Additional notes.

    Returns:
        Confirmation with record ID and reminder status.

    Ack: Logging {service_type} for vehicle...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."
        if not service_type or not service_type.strip():
            return "Error: service_type is required."

        svc_id = f"svc-{uuid.uuid4().hex[:8]}"
        record = {
            "id": svc_id,
            "vehicle_id": vehicle_id.strip(),
            "service_type": service_type.strip(),
            "description": description.strip() if description else "",
            "date_performed": date_performed.strip() if date_performed else date.today().isoformat(),
            "odometer_at_service": odometer_at_service if odometer_at_service > 0 else None,
            "cost": cost if cost > 0 else None,
            "shop_name": shop_name.strip() if shop_name else "",
            "next_due_date": next_due_date.strip() if next_due_date else None,
            "next_due_mileage": next_due_mileage if next_due_mileage > 0 else None,
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }

        # Auto-create reminder if next_due_date is set
        reminder_msg = ""
        if next_due_date and next_due_date.strip():
            try:
                vehicle = _dl.get_vehicle(vehicle_id.strip())
                veh_name = vehicle["name"] if vehicle else vehicle_id
                from apps.reminders.data import save_reminder
                reminder_id = f"r-{uuid.uuid4().hex[:8]}"
                reminder = {
                    "id": reminder_id,
                    "user_id": created_by.strip() if created_by else "",
                    "title": f"{service_type.strip()} due for {veh_name}",
                    "due_at": f"{next_due_date.strip()}T09:00:00",
                    "source": "auto_maintenance",
                    "notes": f"Vehicle: {veh_name}\nService: {service_type.strip()}",
                }
                if next_due_mileage > 0:
                    reminder["notes"] += f"\nDue at: {next_due_mileage:,} miles"
                save_reminder(reminder)
                record["reminder_id"] = reminder_id
                reminder_msg = f"\nReminder created for {next_due_date.strip()}."
            except Exception as re:
                logger.warning("AUTO: Failed to create reminder: %s", re)
                reminder_msg = "\n(Could not create reminder automatically.)"

        _dl.save_service_record(record)

        # Update vehicle odometer if provided
        if odometer_at_service > 0:
            _dl.update_vehicle(vehicle_id.strip(), {"odometer": odometer_at_service})

        # Auto-create oil change tracking if this is an oil change with mileage
        oil_msg = ""
        if odometer_at_service > 0:
            import re
            _oil_pat = re.compile(r"oil\s*(change|[&/]|and)\s*(filter|change)?", re.IGNORECASE)
            stype = service_type.strip().lower()
            if "oil change" in stype or _oil_pat.search(stype):
                try:
                    tracking = _dl.upsert_oil_tracking(vehicle_id.strip(), {
                        "date_performed": record["date_performed"],
                        "odometer_at_service": odometer_at_service,
                        "service_record_id": svc_id,
                    })
                    if tracking:
                        oil_msg = f"\nOil change tracking set: next due at {tracking['next_due_mileage']:,} mi."
                except Exception as oe:
                    logger.warning("AUTO: Failed to create oil tracking: %s", oe)

        logger.info("AUTO: Logged %s for %s (%s)", service_type.strip(), vehicle_id.strip(), svc_id)

        cost_str = f" — ${cost:.2f}" if cost > 0 else ""
        return f"Service logged: {service_type.strip()} ({svc_id}){cost_str}{reminder_msg}{oil_msg}"

    except Exception as e:
        return f"Error in log_service: {str(e)}"


def get_vehicle_history(vehicle_id: str) -> str:
    """Get full service history for a vehicle.

    Args:
        vehicle_id: The vehicle ID.

    Returns:
        Formatted service history.

    Ack: Loading service history...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        records = _dl.get_service_records(vehicle_id.strip())
        if not records:
            return f"No service records found for vehicle '{vehicle_id}'."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        veh_name = vehicle["name"] if vehicle else vehicle_id

        lines = [f"Service History for {veh_name} ({len(records)} records):\n"]
        for r in records:
            dt = r.get("date_performed") or "?"
            cost = f" — ${r['cost']:.2f}" if r.get("cost") is not None else ""
            odo = f" @ {r['odometer_at_service']:,} mi" if r.get("odometer_at_service") else ""
            shop = f" at {r['shop_name']}" if r.get("shop_name") else ""
            lines.append(f"- [{dt}] {r['service_type']}{cost}{odo}{shop} ({r['id']})")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_vehicle_history: {str(e)}"


def search_service_records(query: str) -> str:
    """Search across all service records by type, description, shop, or vehicle name.

    Args:
        query: Search terms.

    Returns:
        Matching service records.

    Ack: Searching service records for "{query}"...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."

        records = _dl.search_service_records(query.strip())
        if not records:
            return f"No service records match '{query}'."

        lines = [f"Found {len(records)} record(s) matching '{query}':\n"]
        for r in records:
            dt = r.get("date_performed") or "?"
            veh = f" [{r['vehicle_name']}]" if r.get("vehicle_name") else ""
            lines.append(f"- [{dt}] {r['service_type']}{veh} ({r['id']})")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in search_service_records: {str(e)}"


def create_maintenance_schedule(
    vehicle_id: str,
    title: str,
    created_by: str,
    recurrence: str = "yearly",
    first_due_date: str = "",
    interval_days: int = 0,
    description: str = "",
) -> str:
    """Create a recurring maintenance schedule linked to a vehicle.

    After creating, the schedule ID (sch-*) can be passed to complete_maintenance.

    Args:
        vehicle_id: The vehicle ID (veh-xxx).
        title: Service item name (e.g. "Wax headlights", "Tire rotation").
        created_by: Who is creating it.
        recurrence: How often — "yearly", "monthly", "quarterly", "biweekly",
                    "weekly", or "interval" (use interval_days for custom cadence).
        first_due_date: First due date (YYYY-MM-DD). Empty = today.
        interval_days: Days between occurrences when recurrence="interval".
                       E.g. 365 for yearly, 90 for quarterly, 30 for monthly.
        description: Optional notes about the maintenance item.

    Returns:
        Confirmation with the new schedule ID (sch-xxx).

    Ack: Creating maintenance schedule...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."
        if not title or not title.strip():
            return "Error: title is required."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        if not vehicle:
            return f"Error: Vehicle '{vehicle_id}' not found."

        rec = recurrence.strip().lower() if recurrence else "yearly"

        # Map named shortcuts to recurrence_type + rule
        _RECURRENCE_MAP = {
            "yearly":    ("yearly",   {}),
            "monthly":   ("monthly",  {}),
            "weekly":    ("weekly",   {}),
            "quarterly": ("interval", {"days": 91}),
            "biweekly":  ("interval", {"days": 14}),
        }

        if rec in _RECURRENCE_MAP:
            recurrence_type, rule = _RECURRENCE_MAP[rec]
        elif rec == "interval":
            if not interval_days or interval_days <= 0:
                return "Error: interval_days is required when recurrence='interval'."
            recurrence_type, rule = "interval", {"days": interval_days}
        else:
            return f"Error: Unknown recurrence '{recurrence}'. Use: yearly, monthly, quarterly, biweekly, weekly, interval."

        from apps.schedules.data import create_schedule
        sch = create_schedule(
            title=title.strip(),
            created_by=created_by.strip() if created_by else "user",
            category="auto",
            description=description.strip() if description else "",
            recurrence_type=recurrence_type,
            recurrence_rule=rule,
            linked_entity_id=vehicle_id.strip(),
            linked_entity_type="vehicle",
            start_date=first_due_date.strip() if first_due_date else date.today().isoformat(),
        )

        sch_id = sch["id"]
        veh_name = vehicle.get("name", vehicle_id)
        due_str = sch.get("next_due", "")
        if due_str:
            due_str = due_str[:10]

        from apps.schedules.data import describe_recurrence
        recur_desc = describe_recurrence(recurrence_type, rule)

        logger.info("AUTO: Created maintenance schedule '%s' (%s) for %s", title.strip(), sch_id, vehicle_id.strip())
        return (
            f"Maintenance schedule created: '{title.strip()}' ({sch_id})\n"
            f"Vehicle: {veh_name}\n"
            f"Recurrence: {recur_desc}\n"
            f"First due: {due_str}\n"
            f"Now call complete_maintenance(schedule_id='{sch_id}', vehicle_id='{vehicle_id.strip()}', ...) to log completion."
        )

    except Exception as e:
        return f"Error in create_maintenance_schedule: {str(e)}"


def complete_maintenance(
    schedule_id: str,
    vehicle_id: str,
    completed_by: str = "",
    service_type: str = "",
    date_performed: str = "",
    odometer: int = 0,
    cost: float = 0.0,
    shop_name: str = "",
    notes: str = "",
) -> str:
    """Mark a recurring maintenance schedule as done. Advances next_due and logs a service record.

    Use this when the user says they completed a maintenance item (e.g. "I started the car",
    "I changed the oil", "I checked the washer fluid"). Get the schedule_id from
    get_upcoming_maintenance (shown as [schedule:sch-xxx]).

    Args:
        schedule_id: The schedule ID (sch-xxx) from get_upcoming_maintenance.
        vehicle_id: The vehicle ID (veh-xxx).
        completed_by: Username of who completed it.
        service_type: Override the service type label (default: schedule title).
        date_performed: Date completed (YYYY-MM-DD). Empty = today.
        odometer: Current odometer reading. 0 = not specified.
        cost: Cost in dollars. 0 = not specified.
        shop_name: Where it was done (or "DIY"). Empty = not specified.
        notes: Any additional notes.

    Returns:
        Confirmation with new next_due date and service record ID.

    Ack: Marking maintenance complete...
    """
    try:
        if not schedule_id or not schedule_id.strip():
            return "Error: schedule_id is required."
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        result = _dl.complete_maintenance(
            schedule_id=schedule_id.strip(),
            vehicle_id=vehicle_id.strip(),
            completed_by=completed_by.strip() if completed_by else "",
            service_type=service_type.strip() if service_type else "",
            date_performed=date_performed.strip() if date_performed else "",
            odometer=odometer if odometer > 0 else None,
            cost=cost if cost > 0 else None,
            shop_name=shop_name.strip() if shop_name else "",
            notes=notes.strip() if notes else "",
        )

        if result.get("error"):
            return f"Error: {result['error']}"

        sch = result.get("schedule", {})
        svc = result.get("service_record", {})
        new_due = sch.get("next_due", "")
        if new_due:
            new_due = new_due[:10]
        svc_id = svc.get("id", "?") if svc else "?"
        title = sch.get("title", schedule_id)
        return (
            f"Maintenance complete: {title}\n"
            f"Service record: {svc_id}\n"
            f"Next due: {new_due}"
        )

    except Exception as e:
        return f"Error in complete_maintenance: {str(e)}"


def get_upcoming_maintenance() -> str:
    """Get all upcoming maintenance across all vehicles.

    Returns:
        List of upcoming service items with due dates/mileage.

    Ack: Checking upcoming maintenance...
    """
    try:
        records = _dl.get_upcoming_maintenance()
        if not records:
            return "No upcoming maintenance scheduled."

        lines = ["Upcoming Maintenance:\n"]
        for r in records:
            veh = r.get("vehicle_name") or r.get("vehicle_id", "?")
            rid = r.get("id", "?")
            if r.get("_type") == "schedule":
                # Platform schedule linked to vehicle
                name = r.get("title", "Maintenance")
                due = f" due {r['next_due'][:10]}" if r.get("next_due") else ""
                recur = r.get("recurrence_description", "")
                recur_str = f" ({recur})" if recur else ""
                lines.append(f"- {name} for {veh}{due}{recur_str} [schedule:{rid}]")
            else:
                # Service record with next_due_date / next_due_mileage
                due = ""
                if r.get("next_due_date"):
                    due = f" due {r['next_due_date']}"
                if r.get("next_due_mileage"):
                    due += f" / {r['next_due_mileage']:,} mi"
                    if r.get("current_odometer"):
                        remaining = r["next_due_mileage"] - r["current_odometer"]
                        due += f" ({remaining:,} mi remaining)"
                lines.append(f"- {r['service_type']} for {veh}{due} [svc:{rid}]")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_upcoming_maintenance: {str(e)}"


# ---------------------------------------------------------------------------
# Mileage Reporting (Oil Change Tracking)
# ---------------------------------------------------------------------------

def report_mileage(
    vehicle_id: str,
    odometer: int,
    created_by: str = "",
) -> str:
    """Report current mileage for a vehicle to check oil change status.

    When the vehicle has oil change tracking set up, this records the mileage
    check and determines if the oil change is due.

    Args:
        vehicle_id: The vehicle ID.
        odometer: Current odometer reading.
        created_by: Who is reporting (optional).

    Returns:
        Status message indicating whether the oil change is due.

    Ack: Recording mileage...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."
        if not odometer or odometer <= 0:
            return "Error: odometer must be a positive number."

        tracking = _dl.record_mileage_check(vehicle_id.strip(), odometer)
        if not tracking:
            # No oil tracking — just update vehicle odometer
            _dl.update_vehicle(vehicle_id.strip(), {"odometer": odometer})
            return f"Mileage recorded: {odometer:,} mi. (No oil change tracking set up for this vehicle.)"

        if tracking["is_due"]:
            return (
                f"Mileage recorded: {odometer:,} mi.\n"
                f"Oil change is OVERDUE! (due at {tracking['next_due_mileage']:,} mi)"
            )
        remaining = tracking["next_due_mileage"] - odometer
        return (
            f"Mileage recorded: {odometer:,} mi.\n"
            f"Oil change not yet due (due at {tracking['next_due_mileage']:,} mi — {remaining:,} mi remaining)."
        )

    except Exception as e:
        return f"Error in report_mileage: {str(e)}"


# ---------------------------------------------------------------------------
# Vehicle Issues
# ---------------------------------------------------------------------------

def report_vehicle_issue(
    vehicle_id: str,
    title: str,
    created_by: str,
    severity: str = "minor",
    description: str = "",
    date_noticed: str = "",
    notes: str = "",
) -> str:
    """Report a new issue with a vehicle.

    Args:
        vehicle_id: The vehicle ID.
        title: Brief issue title (e.g. "Paint peeling on hood", "Nick on windshield").
        created_by: Who is reporting it.
        severity: "minor", "moderate", "major", or "critical".
        description: Detailed description.
        date_noticed: When first noticed (YYYY-MM-DD). Empty = today.
        notes: Additional notes.

    Returns:
        Confirmation with issue ID.

    Ack: Reporting issue for vehicle...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."
        if not title or not title.strip():
            return "Error: title is required."

        issue_id = f"vis-{uuid.uuid4().hex[:8]}"
        issue = {
            "id": issue_id,
            "vehicle_id": vehicle_id.strip(),
            "title": title.strip(),
            "description": description.strip() if description else "",
            "severity": severity.strip() if severity in ("minor", "moderate", "major", "critical") else "minor",
            "date_noticed": date_noticed.strip() if date_noticed else date.today().isoformat(),
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }

        _dl.save_issue(issue)
        logger.info("AUTO: Reported issue '%s' for %s (%s)", title.strip(), vehicle_id.strip(), issue_id)

        return f"Issue reported: '{title.strip()}' ({issue_id}) — severity: {severity}"

    except Exception as e:
        return f"Error in report_vehicle_issue: {str(e)}"


def update_vehicle_issue(
    issue_id: str,
    status: str = "",
    fix_description: str = "",
    date_fixed: str = "",
    cost: float = -1.0,
    severity: str = "",
    notes: str = "",
) -> str:
    """Update or resolve a vehicle issue.

    Args:
        issue_id: The issue ID.
        status: New status: "open", "monitoring", or "fixed".
        fix_description: What was done to fix it.
        date_fixed: When it was fixed (YYYY-MM-DD).
        cost: Repair cost (-1 = don't change).
        severity: New severity level.
        notes: Updated notes.

    Returns:
        Confirmation of update.

    Ack: Updating issue {issue_id}...
    """
    try:
        if not issue_id or not issue_id.strip():
            return "Error: issue_id is required."

        updates = {}
        if status: updates["status"] = status.strip()
        if fix_description: updates["fix_description"] = fix_description.strip()
        if date_fixed: updates["date_fixed"] = date_fixed.strip()
        if cost >= 0: updates["cost"] = cost if cost > 0 else None
        if severity: updates["severity"] = severity.strip()
        if notes: updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."

        success = _dl.update_issue(issue_id.strip(), updates)
        if success:
            fields = ", ".join(updates.keys())
            return f"Issue {issue_id} updated. Changed: {fields}"
        return f"Error: Issue '{issue_id}' not found."

    except Exception as e:
        return f"Error in update_vehicle_issue: {str(e)}"


def list_vehicle_issues(vehicle_id: str = "", status: str = "") -> str:
    """List vehicle issues, optionally filtered.

    Args:
        vehicle_id: Filter by vehicle. Empty = all open issues across all vehicles.
        status: Filter by status: "open", "monitoring", "fixed". Empty = all non-fixed.

    Returns:
        Formatted list of issues.

    Ack: Listing vehicle issues...
    """
    try:
        if vehicle_id and vehicle_id.strip():
            issues = _dl.get_issues(vehicle_id.strip(), status.strip() if status else None)
        else:
            issues = _dl.get_all_open_issues()

        if not issues:
            return "No issues found."

        lines = [f"Vehicle Issues ({len(issues)}):\n"]
        for iss in issues:
            sev_icon = {"critical": "\U0001f534", "major": "\U0001f7e0", "moderate": "\U0001f7e1", "minor": "\U0001f7e2"}.get(iss["severity"], "\u26aa")
            veh = f" [{iss['vehicle_name']}]" if iss.get("vehicle_name") else ""
            status_str = f" [{iss['status']}]" if iss.get("status") != "open" else ""
            lines.append(f"- {sev_icon} {iss['title']}{veh}{status_str} ({iss['id']})")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_vehicle_issues: {str(e)}"


# ---------------------------------------------------------------------------
# Vehicle Valuations
# ---------------------------------------------------------------------------

def log_vehicle_valuation(
    vehicle_id: str,
    private_party_value: float,
    trade_in_value: float,
    created_by: str,
    condition: str = "good",
    mileage_at_valuation: int = 0,
    source: str = "kbb",
    date_recorded: str = "",
    notes: str = "",
) -> str:
    """Log a vehicle valuation lookup (blue book value).

    Args:
        vehicle_id: The vehicle ID.
        private_party_value: Private party value in dollars.
        trade_in_value: Trade-in value in dollars.
        created_by: Who is logging it.
        condition: Vehicle condition: "excellent", "very_good", "good", "fair".
        mileage_at_valuation: Mileage at time of lookup. 0 = use current odometer.
        source: Value source: "kbb", "edmunds", "nada", "other".
        date_recorded: Date of lookup (YYYY-MM-DD). Empty = today.
        notes: Additional notes.

    Returns:
        Confirmation with valuation ID.

    Ack: Logging valuation for vehicle...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        val_id = f"vval-{uuid.uuid4().hex[:8]}"
        val = {
            "id": val_id,
            "vehicle_id": vehicle_id.strip(),
            "date_recorded": date_recorded.strip() if date_recorded else date.today().isoformat(),
            "private_party_value": private_party_value,
            "trade_in_value": trade_in_value,
            "condition": condition.strip() if condition in ("excellent", "very_good", "good", "fair") else "good",
            "mileage_at_valuation": mileage_at_valuation if mileage_at_valuation > 0 else None,
            "source": source.strip() if source in ("kbb", "edmunds", "nada", "other") else "kbb",
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }

        _dl.save_valuation(val)
        logger.info("AUTO: Logged valuation for %s (%s)", vehicle_id.strip(), val_id)

        return (
            f"Valuation logged ({val_id}):\n"
            f"Private party: ${private_party_value:,.2f} | Trade-in: ${trade_in_value:,.2f}\n"
            f"Condition: {condition} | Source: {source}"
        )

    except Exception as e:
        return f"Error in log_vehicle_valuation: {str(e)}"


def get_vehicle_valuations(vehicle_id: str) -> str:
    """Get valuation history for a vehicle.

    Args:
        vehicle_id: The vehicle ID.

    Returns:
        Formatted valuation history.

    Ack: Loading valuation history...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        vals = _dl.get_valuations(vehicle_id.strip())
        if not vals:
            return f"No valuations recorded for vehicle '{vehicle_id}'."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        veh_name = vehicle["name"] if vehicle else vehicle_id

        lines = [f"Valuation History for {veh_name} ({len(vals)} records):\n"]
        for v in vals:
            pp = f"${v['private_party_value']:,.2f}" if v.get("private_party_value") is not None else "?"
            ti = f"${v['trade_in_value']:,.2f}" if v.get("trade_in_value") is not None else "?"
            lines.append(f"- [{v['date_recorded']}] Private: {pp} | Trade-in: {ti} ({v['source']}, {v['condition']})")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_vehicle_valuations: {str(e)}"


# ---------------------------------------------------------------------------
# Vehicle Conditions
# ---------------------------------------------------------------------------

def log_vehicle_condition(
    vehicle_id: str,
    created_by: str,
    date_recorded: str = "",
    mileage_at_report: int = 0,
    brakes: str = "good",
    tires: str = "good",
    tire_tread_depth: float = 0.0,
    oil_life_pct: int = -1,
    battery: str = "good",
    exterior: str = "good",
    interior: str = "good",
    lights_signals: str = "all_working",
    fluids: str = "all_good",
    notes: str = "",
) -> str:
    """Log a vehicle condition report — periodic snapshot of component health.

    Args:
        vehicle_id: The vehicle ID.
        created_by: Who is logging it.
        date_recorded: Date of report (YYYY-MM-DD). Empty = today.
        mileage_at_report: Current odometer. 0 = not specified.
        brakes: "good", "fair", "worn", or "needs_replacement".
        tires: "good", "fair", "worn", or "needs_replacement".
        tire_tread_depth: Tread depth in 32nds of an inch. 0 = not measured.
        oil_life_pct: Oil life remaining 0-100. -1 = not checked.
        battery: "good", "fair", "weak", or "needs_replacement".
        exterior: "excellent", "good", "fair", or "poor".
        interior: "excellent", "good", "fair", or "poor".
        lights_signals: "all_working" or "issues".
        fluids: "all_good" or "needs_attention".
        notes: Observations.

    Returns:
        Confirmation with condition ID.

    Ack: Logging condition report for vehicle...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        cond_id = f"vcon-{uuid.uuid4().hex[:8]}"
        cond = {
            "id": cond_id,
            "vehicle_id": vehicle_id.strip(),
            "date_recorded": date_recorded.strip() if date_recorded else date.today().isoformat(),
            "mileage_at_report": mileage_at_report if mileage_at_report > 0 else None,
            "brakes": brakes.strip(),
            "tires": tires.strip(),
            "tire_tread_depth": tire_tread_depth if tire_tread_depth > 0 else None,
            "oil_life_pct": oil_life_pct if oil_life_pct >= 0 else None,
            "battery": battery.strip(),
            "exterior": exterior.strip(),
            "interior": interior.strip(),
            "lights_signals": lights_signals.strip(),
            "fluids": fluids.strip(),
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }

        _dl.save_condition(cond)

        # Update vehicle odometer if provided
        if mileage_at_report > 0:
            _dl.update_vehicle(vehicle_id.strip(), {"odometer": mileage_at_report})

        logger.info("AUTO: Logged condition for %s (%s)", vehicle_id.strip(), cond_id)

        return f"Condition report logged ({cond_id}). Brakes: {brakes}, Tires: {tires}, Battery: {battery}"

    except Exception as e:
        return f"Error in log_vehicle_condition: {str(e)}"


def get_vehicle_conditions(vehicle_id: str) -> str:
    """Get condition history for a vehicle.

    Args:
        vehicle_id: The vehicle ID.

    Returns:
        Formatted condition history.

    Ack: Loading condition history...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        conditions = _dl.get_conditions(vehicle_id.strip())
        if not conditions:
            return f"No condition reports for vehicle '{vehicle_id}'."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        veh_name = vehicle["name"] if vehicle else vehicle_id

        lines = [f"Condition History for {veh_name} ({len(conditions)} reports):\n"]
        for c in conditions:
            odo = f" @ {c['mileage_at_report']:,} mi" if c.get("mileage_at_report") else ""
            lines.append(f"- [{c['date_recorded']}]{odo}: Brakes={c['brakes']}, Tires={c['tires']}, Battery={c['battery']}, Ext={c['exterior']}, Int={c['interior']}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_vehicle_conditions: {str(e)}"


def get_latest_vehicle_condition(vehicle_id: str) -> str:
    """Get the most recent condition report for a vehicle.

    Args:
        vehicle_id: The vehicle ID.

    Returns:
        Latest condition snapshot.

    Ack: Loading latest condition...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        cond = _dl.get_latest_condition(vehicle_id.strip())
        if not cond:
            return f"No condition reports for vehicle '{vehicle_id}'."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        veh_name = vehicle["name"] if vehicle else vehicle_id

        return _format_condition(cond, veh_name)

    except Exception as e:
        return f"Error in get_latest_vehicle_condition: {str(e)}"


# ---------------------------------------------------------------------------
# Service Record — update / delete
# ---------------------------------------------------------------------------

def update_service_record(
    svc_id: str,
    service_type: str = "",
    date_performed: str = "",
    odometer_at_service: int = -1,
    cost: float = -1.0,
    shop_name: str = "",
    description: str = "",
    next_due_date: str = "",
    next_due_mileage: int = -1,
    notes: str = "",
) -> str:
    """Edit an existing service record. Only provided fields are changed.

    Args:
        svc_id: The service record ID (svc-xxx).
        service_type: New service type label (empty = keep).
        date_performed: New date (YYYY-MM-DD, empty = keep).
        odometer_at_service: New mileage (-1 = keep, 0 = clear).
        cost: New cost in dollars (-1 = keep, 0 = clear).
        shop_name: New shop name (empty = keep).
        description: New description (empty = keep).
        next_due_date: New next due date (YYYY-MM-DD, empty = keep).
        next_due_mileage: New next due mileage (-1 = keep, 0 = clear).
        notes: New notes (empty = keep).

    Returns:
        Confirmation of what was updated.

    Ack: Updating service record {svc_id}...
    """
    try:
        if not svc_id or not svc_id.strip():
            return "Error: svc_id is required."

        updates = {}
        if service_type: updates["service_type"] = service_type.strip()
        if date_performed: updates["date_performed"] = date_performed.strip()
        if odometer_at_service >= 0: updates["odometer_at_service"] = odometer_at_service or None
        if cost >= 0: updates["cost"] = cost or None
        if shop_name: updates["shop_name"] = shop_name.strip()
        if description: updates["description"] = description.strip()
        if next_due_date: updates["next_due_date"] = next_due_date.strip() or None
        if next_due_mileage >= 0: updates["next_due_mileage"] = next_due_mileage or None
        if notes: updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."

        ok = _dl.update_service_record(svc_id.strip(), updates)
        if ok:
            fields = ", ".join(updates.keys())
            return f"Service record {svc_id} updated. Changed: {fields}"
        return f"Error: Service record '{svc_id}' not found."

    except Exception as e:
        return f"Error in update_service_record: {str(e)}"


def delete_service_record(svc_id: str) -> str:
    """Delete a service record permanently.

    Args:
        svc_id: The service record ID (svc-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting service record {svc_id}...
    """
    try:
        if not svc_id or not svc_id.strip():
            return "Error: svc_id is required."

        ok = _dl.delete_service_record(svc_id.strip())
        if ok:
            return f"Service record '{svc_id}' deleted."
        return f"Error: Service record '{svc_id}' not found."

    except Exception as e:
        return f"Error in delete_service_record: {str(e)}"


# ---------------------------------------------------------------------------
# Vehicle Issues — delete
# ---------------------------------------------------------------------------

def delete_vehicle_issue(issue_id: str) -> str:
    """Delete a vehicle issue permanently.

    Args:
        issue_id: The issue ID (vis-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting vehicle issue {issue_id}...
    """
    try:
        if not issue_id or not issue_id.strip():
            return "Error: issue_id is required."

        ok = _dl.delete_issue(issue_id.strip())
        if ok:
            return f"Vehicle issue '{issue_id}' deleted."
        return f"Error: Issue '{issue_id}' not found."

    except Exception as e:
        return f"Error in delete_vehicle_issue: {str(e)}"


# ---------------------------------------------------------------------------
# Maintenance Schedules — per-vehicle list / delete
# ---------------------------------------------------------------------------

def get_vehicle_maintenance(vehicle_id: str) -> str:
    """List all recurring maintenance schedules set up for a specific vehicle.

    Args:
        vehicle_id: The vehicle ID (veh-xxx).

    Returns:
        Formatted list of recurring schedules with next due dates and IDs.

    Ack: Loading maintenance schedules...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        vehicle = _dl.get_vehicle(vehicle_id.strip())
        if not vehicle:
            return f"Error: Vehicle '{vehicle_id}' not found."

        schedules = _dl.get_vehicle_maintenance(vehicle_id.strip())
        if not schedules:
            return f"No recurring maintenance schedules for {vehicle.get('name', vehicle_id)}."

        veh_name = vehicle.get("name", vehicle_id)
        lines = [f"Maintenance schedules for {veh_name} ({len(schedules)}):\n"]
        for s in schedules:
            due = f" | Next due: {s['next_due'][:10]}" if s.get("next_due") else ""
            recur = f" ({s['recurrence_description']})" if s.get("recurrence_description") else ""
            active = "" if s.get("active", True) else " [inactive]"
            lines.append(f"- {s['title']}{due}{recur}{active} [{s['id']}]")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_vehicle_maintenance: {str(e)}"


def delete_maintenance_schedule(schedule_id: str) -> str:
    """Delete a recurring maintenance schedule permanently.

    Args:
        schedule_id: The schedule ID (sch-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting maintenance schedule {schedule_id}...
    """
    try:
        if not schedule_id or not schedule_id.strip():
            return "Error: schedule_id is required."

        from apps.schedules.data import delete_schedule
        ok = delete_schedule(schedule_id.strip())
        if ok:
            return f"Maintenance schedule '{schedule_id}' deleted."
        return f"Error: Schedule '{schedule_id}' not found."

    except Exception as e:
        return f"Error in delete_maintenance_schedule: {str(e)}"


# ---------------------------------------------------------------------------
# Valuations — delete
# ---------------------------------------------------------------------------

def delete_vehicle_valuation(val_id: str) -> str:
    """Delete a vehicle valuation record permanently.

    Args:
        val_id: The valuation ID (vval-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting valuation {val_id}...
    """
    try:
        if not val_id or not val_id.strip():
            return "Error: val_id is required."

        ok = _dl.delete_valuation(val_id.strip())
        if ok:
            return f"Valuation '{val_id}' deleted."
        return f"Error: Valuation '{val_id}' not found."

    except Exception as e:
        return f"Error in delete_vehicle_valuation: {str(e)}"


# ---------------------------------------------------------------------------
# Oil Change Tracking — setup / update settings
# ---------------------------------------------------------------------------

def setup_oil_tracking(
    vehicle_id: str,
    odometer_at_service: int,
    date_performed: str = "",
    mileage_interval: int = 5000,
    cooldown_months: int = 3,
) -> str:
    """Set up or reset oil change tracking for a vehicle.

    Use this to manually configure oil change tracking when it wasn't set up
    via log_service (e.g. existing vehicles or manual backfill).

    Args:
        vehicle_id: The vehicle ID (veh-xxx).
        odometer_at_service: Mileage at the last oil change.
        date_performed: Date of last oil change (YYYY-MM-DD). Empty = today.
        mileage_interval: Miles between oil changes (default 5000).
        cooldown_months: Months before a nag triggers (default 3).

    Returns:
        Confirmation with next due mileage.

    Ack: Setting up oil change tracking...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."
        if not odometer_at_service or odometer_at_service <= 0:
            return "Error: odometer_at_service must be a positive number."

        tracking = _dl.upsert_oil_tracking(vehicle_id.strip(), {
            "date_performed": date_performed.strip() if date_performed else date.today().isoformat(),
            "odometer_at_service": odometer_at_service,
            "mileage_interval": mileage_interval if mileage_interval > 0 else 5000,
            "cooldown_months": cooldown_months if cooldown_months > 0 else 3,
        })
        if not tracking:
            return f"Error: Vehicle '{vehicle_id}' not found."

        return (
            f"Oil change tracking configured for {vehicle_id}.\n"
            f"Last service: {odometer_at_service:,} mi\n"
            f"Next due: {tracking['next_due_mileage']:,} mi (every {tracking['mileage_interval']:,} mi)"
        )

    except Exception as e:
        return f"Error in setup_oil_tracking: {str(e)}"


def update_oil_tracking(
    vehicle_id: str,
    mileage_interval: int = 0,
    cooldown_months: int = 0,
) -> str:
    """Update oil change tracking settings for a vehicle.

    Args:
        vehicle_id: The vehicle ID (veh-xxx).
        mileage_interval: New miles-between-changes interval (0 = keep current).
        cooldown_months: New cooldown in months before nag triggers (0 = keep).

    Returns:
        Confirmation with updated settings.

    Ack: Updating oil tracking settings...
    """
    try:
        if not vehicle_id or not vehicle_id.strip():
            return "Error: vehicle_id is required."

        updates = {}
        if mileage_interval > 0: updates["mileage_interval"] = mileage_interval
        if cooldown_months > 0: updates["cooldown_months"] = cooldown_months

        if not updates:
            return "No fields to update."

        tracking = _dl.update_oil_tracking_settings(vehicle_id.strip(), updates)
        if not tracking:
            return f"Error: No oil tracking found for '{vehicle_id}'. Use setup_oil_tracking first."

        return (
            f"Oil tracking updated for {vehicle_id}.\n"
            f"Interval: every {tracking['mileage_interval']:,} mi | "
            f"Cooldown: {tracking['cooldown_months']} months | "
            f"Next due: {tracking['next_due_mileage']:,} mi"
        )

    except Exception as e:
        return f"Error in update_oil_tracking: {str(e)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_vehicle(v: dict) -> str:
    yr = f"{v['year']} " if v.get("year") else ""
    make_model = f"{v['make']} {v['model']}".strip()
    trim = f" {v['trim_level']}" if v.get("trim_level") else ""
    if make_model:
        make_model = f" ({make_model}{trim})"
    odo = f"\nOdometer: {v['odometer']:,} miles" if v.get("odometer") else ""
    vin = f"\nVIN: {v['vin']}" if v.get("vin") else ""
    plate = f"\nPlate: {v['license_plate']}" if v.get("license_plate") else ""
    notes = f"\nNotes: {v['notes']}" if v.get("notes") else ""

    return (
        f"# {yr}{v['name']}{make_model} ({v['id']}){odo}{vin}{plate}{notes}\n"
        f"Added by: {v.get('created_by', '?')}"
    ).strip()


def _format_condition(c: dict, veh_name: str = "") -> str:
    header = f"Condition Report for {veh_name}" if veh_name else "Condition Report"
    odo = f" @ {c['mileage_at_report']:,} mi" if c.get("mileage_at_report") else ""
    oil = f"\nOil life: {c['oil_life_pct']}%" if c.get("oil_life_pct") is not None else ""
    tread = f"\nTire tread: {c['tire_tread_depth']}/32\"" if c.get("tire_tread_depth") is not None else ""
    notes = f"\nNotes: {c['notes']}" if c.get("notes") else ""

    return (
        f"{header} — {c['date_recorded']}{odo}\n"
        f"Brakes: {c['brakes']} | Tires: {c['tires']} | Battery: {c['battery']}\n"
        f"Exterior: {c['exterior']} | Interior: {c['interior']}\n"
        f"Lights/Signals: {c['lights_signals']} | Fluids: {c['fluids']}"
        f"{oil}{tread}{notes}"
    ).strip()
