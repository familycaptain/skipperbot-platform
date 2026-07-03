"""
Home App Tools — Home maintenance tasks, task categories, and home issues.
"""

import uuid

from config import logger
from apps.home import data as _dl


# ---------------------------------------------------------------------------
# Home Maintenance Task Tools
# ---------------------------------------------------------------------------

def create_home_task(
    name: str,
    created_by: str,
    task_type: str = "recurring",
    interval_days: int = 0,
    category: str = "General",
    next_due_at: str = "",
    description: str = "",
    notes: str = "",
) -> str:
    """Create a home maintenance task (recurring or ad-hoc).

    Use for things like "add a task to clean the A/C filter every 90 days" or
    "remind me to do septic tank treatment monthly" or "add a one-time task to
    clean gutters due 2025-04-01".

    Args:
        name: Task name (e.g. "Clean A/C filter", "Septic tank treatment").
        created_by: Who is creating the task (a person's name).
        task_type: "recurring" for repeating tasks, "adhoc" for one-time tasks.
        interval_days: For recurring tasks, days between each completion (e.g. 90 for quarterly, 30 for monthly). 0 = not set.
        category: Task category — HVAC, Plumbing, Exterior, Electrical, Pest Control, General, etc.
        next_due_at: Date when task is next due (YYYY-MM-DD). For recurring, this is the first due date.
        description: Additional details about what needs to be done.
        notes: Extra notes.

    Returns:
        Confirmation with task ID.

    Ack: Creating maintenance task "{name}"...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."

        task_id = f"hmt-{uuid.uuid4().hex[:8]}"
        task = {
            "id": task_id,
            "name": name.strip(),
            "description": description.strip() if description else "",
            "category": category.strip() if category else "General",
            "task_type": task_type if task_type in ("recurring", "adhoc") else "recurring",
            "interval_days": interval_days if interval_days and interval_days > 0 else None,
            "next_due_at": next_due_at.strip() if next_due_at and next_due_at.strip() else None,
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }

        result = _dl.create_task(task)
        if not result:
            return "Error: Failed to create task."

        interval_text = f" every {interval_days} days" if interval_days and interval_days > 0 else ""
        due_text = f", first due {next_due_at}" if next_due_at else ""
        return (
            f"Task created: '{name.strip()}' ({task_id})\n"
            f"Type: {task_type}{interval_text}{due_text}\n"
            f"Category: {category}"
        )

    except Exception as e:
        return f"Error in create_home_task: {str(e)}"


def list_home_tasks(category: str = "", include_done: bool = False) -> str:
    """List home maintenance tasks.

    Args:
        category: Filter by category (e.g. "HVAC", "Plumbing"). Empty = all.
        include_done: If True, also show completed ad-hoc tasks.

    Returns:
        Formatted task list with due status.

    Ack: Loading home maintenance tasks...
    """
    try:
        from datetime import date
        if category and category.strip():
            tasks = _dl.get_tasks_by_category(category.strip())
        else:
            tasks = _dl.get_all_tasks(include_inactive=include_done)

        if not tasks:
            return "No maintenance tasks found."

        today = date.today()
        lines = [f"Home Maintenance Tasks ({len(tasks)}):\n"]
        for t in tasks:
            status = ""
            if t.get("next_due_at"):
                due = date.fromisoformat(t["next_due_at"])
                if due < today:
                    status = " 🔴 OVERDUE"
                elif (due - today).days <= 7:
                    status = f" 🟡 due {t['next_due_at']}"
                else:
                    status = f" 🟢 due {t['next_due_at']}"
            interval = f" (every {t['interval_days']}d)" if t.get("interval_days") else ""
            cat = f" [{t['category']}]" if t.get("category") else ""
            lines.append(f"- {t['name']} ({t['id']}){cat}{interval}{status}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_home_tasks: {str(e)}"


def get_home_task(task_id: str) -> str:
    """Get details and completion history for a home maintenance task.

    Args:
        task_id: Task ID (e.g. "hmt-abc12345").

    Returns:
        Full task details plus recent completion log.

    Ack: Loading task details...
    """
    try:
        task = _dl.get_task(task_id.strip())
        if not task:
            return f"Error: Task '{task_id}' not found."

        log = _dl.get_task_log(task_id.strip(), limit=10)
        interval = f" (every {task['interval_days']} days)" if task.get("interval_days") else ""
        last = f"Last done: {task['last_done_at']}" if task.get("last_done_at") else "Never completed"
        due = f"Next due: {task['next_due_at']}" if task.get("next_due_at") else "No due date set"

        lines = [
            f"# {task['name']} ({task['id']})",
            f"Category: {task['category']}  |  Type: {task['task_type']}{interval}",
            last, due,
        ]
        if task.get("description"):
            lines.append(f"\n{task['description']}")
        if log:
            lines.append(f"\nCompletion history ({len(log)} entries):")
            for entry in log[:5]:
                by = f" by {entry['completed_by']}" if entry.get("completed_by") else ""
                note = f" — {entry['notes']}" if entry.get("notes") else ""
                lines.append(f"  ✓ {entry['completed_at']}{by}{note}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in get_home_task: {str(e)}"


def complete_home_task(
    task_id: str,
    completed_by: str = "",
    completed_at: str = "",
    notes: str = "",
) -> str:
    """Mark a home maintenance task as done.

    For recurring tasks, this advances the next due date automatically.
    For ad-hoc tasks, this marks the task as completed.

    Args:
        task_id: Task ID (e.g. "hmt-abc12345").
        completed_by: Who completed it (a person's name). Empty = system.
        completed_at: Date completed (YYYY-MM-DD). Empty = today.
        notes: Any notes about this completion (e.g. "Used MERV-13 filter").

    Returns:
        Confirmation with updated next due date.

    Ack: Marking task as done...
    """
    try:
        result = _dl.complete_task(
            task_id.strip(),
            completed_at=completed_at.strip() if completed_at else "",
            completed_by=completed_by.strip() if completed_by else "",
            notes=notes.strip() if notes else "",
        )
        if "error" in result:
            return f"Error: {result['error']}"

        task = result.get("task") or {}
        next_due = task.get("next_due_at") or ""
        task_name = task.get("name") or task_id
        by = f" by {completed_by}" if completed_by else ""
        on = f" on {completed_at}" if completed_at else " today"
        if task.get("task_type") == "recurring" and next_due:
            return f"✓ '{task_name}' completed{by}{on}. Next due: {next_due}"
        return f"✓ '{task_name}' completed{by}{on} (task closed)."

    except Exception as e:
        return f"Error in complete_home_task: {str(e)}"


# ---------------------------------------------------------------------------
# Home Issues
# ---------------------------------------------------------------------------

def list_home_issues(status: str = "", location: str = "") -> str:
    """List home issues (problems, repairs, things to fix).

    Args:
        status: Filter by status: "open", "in_progress", "resolved". Empty = all open.
        location: Filter by location (e.g. "Kitchen", "Basement"). Empty = all locations.

    Returns:
        Formatted list of issues with severity and status.

    Ack: Listing home issues...
    """
    try:
        issues = _dl.get_all_issues(
            status=status.strip() if status else None,
            location=location.strip() if location else None,
        )
        if not issues:
            return "No home issues found."

        lines = [f"Home Issues ({len(issues)}):\n"]
        for iss in issues:
            sev_icon = {"critical": "🔴", "major": "🟠", "moderate": "🟡", "minor": "🟢"}.get(iss.get("severity", "minor"), "⚪")
            loc = f" — {iss['location']}" if iss.get("location") else ""
            sub = f" ({iss['sub_location']})" if iss.get("sub_location") else ""
            st = f" [{iss['status']}]" if iss.get("status", "open") != "open" else ""
            cat = f" [{iss['category']}]" if iss.get("category") else ""
            lines.append(f"- {sev_icon} {iss['title']}{loc}{sub}{cat}{st} ({iss['id']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_home_issues: {str(e)}"


def create_home_issue(
    title: str,
    created_by: str,
    description: str = "",
    location: str = "",
    sub_location: str = "",
    category: str = "General",
    severity: str = "minor",
    date_noticed: str = "",
    notes: str = "",
) -> str:
    """Report a home issue — something that needs attention, repair, or monitoring.

    Args:
        title: Brief description (e.g. "Leaky faucet in kitchen", "Crack in drywall").
        created_by: Who is reporting it.
        description: Detailed description of the problem.
        location: Where the issue is (e.g. "Kitchen", "Basement", "Roof").
        sub_location: More specific spot (e.g. "Under the sink", "South wall").
        category: Category — Plumbing, Electrical, HVAC, Structural, Exterior, General, etc.
        severity: "minor", "moderate", "major", or "critical".
        date_noticed: When first noticed (YYYY-MM-DD). Empty = today.
        notes: Additional notes.

    Returns:
        Confirmation with issue ID.

    Ack: Logging home issue...
    """
    try:
        if not title or not title.strip():
            return "Error: title is required."
        from datetime import date
        issue_id = f"hi-{uuid.uuid4().hex[:8]}"
        issue = {
            "id": issue_id,
            "title": title.strip(),
            "description": description.strip() if description else "",
            "location": location.strip() if location else "",
            "sub_location": sub_location.strip() if sub_location else "",
            "category": category.strip() if category else "General",
            "severity": severity if severity in ("minor", "moderate", "major", "critical") else "minor",
            "date_noticed": date_noticed.strip() if date_noticed else date.today().isoformat(),
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }
        result = _dl.create_issue(issue)
        if not result:
            return "Error: Failed to create issue."
        loc_str = f" at {location.strip()}" if location else ""
        logger.info("HOME: Created issue '%s' (%s)", title.strip(), issue_id)
        return f"Issue logged: '{title.strip()}' ({issue_id}){loc_str} — severity: {severity}"
    except Exception as e:
        return f"Error in create_home_issue: {str(e)}"


def get_home_issue(issue_id: str) -> str:
    """Get full details of a home issue.

    Args:
        issue_id: The issue ID (hi-xxx).

    Returns:
        Full issue details.

    Ack: Loading issue details...
    """
    try:
        if not issue_id or not issue_id.strip():
            return "Error: issue_id is required."
        issue = _dl.get_issue(issue_id.strip())
        if not issue:
            return f"Error: Issue '{issue_id}' not found."

        sev_icon = {"critical": "🔴", "major": "🟠", "moderate": "🟡", "minor": "🟢"}.get(issue.get("severity", "minor"), "⚪")
        loc = f"\nLocation: {issue['location']}" if issue.get("location") else ""
        sub = f" > {issue['sub_location']}" if issue.get("sub_location") else ""
        desc = f"\n{issue['description']}" if issue.get("description") else ""
        fixed = f"\nFixed: {issue['date_fixed']} — {issue.get('fix_description', '')}" if issue.get("date_fixed") else ""
        cost = f"\nCost: ${issue['cost']:.2f}" if issue.get("cost") is not None else ""
        notes = f"\nNotes: {issue['notes']}" if issue.get("notes") else ""

        return (
            f"{sev_icon} {issue['title']} ({issue['id']})\n"
            f"Status: {issue.get('status', 'open')} | Category: {issue.get('category', '?')} | "
            f"Severity: {issue.get('severity', '?')}"
            f"{loc}{sub}"
            f"\nNoticed: {issue.get('date_noticed', '?')}"
            f"{desc}{fixed}{cost}{notes}"
        ).strip()
    except Exception as e:
        return f"Error in get_home_issue: {str(e)}"


def update_home_issue(
    issue_id: str,
    title: str = "",
    description: str = "",
    location: str = "",
    sub_location: str = "",
    category: str = "",
    severity: str = "",
    status: str = "",
    date_fixed: str = "",
    fix_description: str = "",
    cost: float = -1.0,
    notes: str = "",
) -> str:
    """Update a home issue. Only provided fields are changed.

    Common use: mark as resolved with status="resolved", date_fixed="YYYY-MM-DD", fix_description="what was done".

    Args:
        issue_id: The issue ID (hi-xxx).
        title: New title (empty = keep).
        description: New description (empty = keep).
        location: New location (empty = keep).
        sub_location: New sub-location (empty = keep).
        category: New category (empty = keep).
        severity: New severity: "minor", "moderate", "major", "critical" (empty = keep).
        status: New status: "open", "in_progress", "resolved" (empty = keep).
        date_fixed: Date the issue was resolved (YYYY-MM-DD).
        fix_description: What was done to fix it.
        cost: Repair cost (-1 = keep, 0 = clear).
        notes: New notes (empty = keep).

    Returns:
        Confirmation of update.

    Ack: Updating issue {issue_id}...
    """
    try:
        if not issue_id or not issue_id.strip():
            return "Error: issue_id is required."
        updates = {}
        if title: updates["title"] = title.strip()
        if description: updates["description"] = description.strip()
        if location: updates["location"] = location.strip()
        if sub_location: updates["sub_location"] = sub_location.strip()
        if category: updates["category"] = category.strip()
        if severity: updates["severity"] = severity.strip()
        if status: updates["status"] = status.strip()
        if date_fixed: updates["date_fixed"] = date_fixed.strip()
        if fix_description: updates["fix_description"] = fix_description.strip()
        if cost >= 0: updates["cost"] = cost or None
        if notes: updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."
        ok = _dl.update_issue(issue_id.strip(), updates)
        if ok:
            fields = ", ".join(updates.keys())
            return f"Issue {issue_id} updated. Changed: {fields}"
        return f"Error: Issue '{issue_id}' not found."
    except Exception as e:
        return f"Error in update_home_issue: {str(e)}"


def delete_home_issue(issue_id: str) -> str:
    """Delete a home issue permanently.

    Args:
        issue_id: The issue ID (hi-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting issue {issue_id}...
    """
    try:
        if not issue_id or not issue_id.strip():
            return "Error: issue_id is required."
        ok = _dl.delete_issue(issue_id.strip())
        if ok:
            return f"Issue '{issue_id}' deleted."
        return f"Error: Issue '{issue_id}' not found."
    except Exception as e:
        return f"Error in delete_home_issue: {str(e)}"


# ---------------------------------------------------------------------------
# Home Appliances
# ---------------------------------------------------------------------------

def create_home_appliance(
    name: str,
    created_by: str,
    appliance_type: str = "General",
    brand: str = "",
    model: str = "",
    serial_number: str = "",
    location: str = "",
    purchase_date: str = "",
    purchase_price: float = -1.0,
    warranty_expires: str = "",
    notes: str = "",
) -> str:
    """Add a household appliance to track (brand, model, serial, purchase & warranty).

    Use for things like "add our LG refrigerator in the kitchen, bought 2023-05-01
    for $1800, warranty through 2028-05-01" or "track the garage water heater".

    Args:
        name: Appliance name (e.g. "Kitchen refrigerator", "Water heater").
        created_by: Who is adding it (a person's name).
        appliance_type: Type — Refrigerator, Dishwasher, Washer, Dryer, HVAC, Water Heater, General, etc.
        brand: Manufacturer/brand (e.g. "LG", "Samsung", "Whirlpool").
        model: Model number/name.
        serial_number: Serial number.
        location: Where it is (e.g. "Kitchen", "Garage", "Laundry room").
        purchase_date: Date purchased (YYYY-MM-DD).
        purchase_price: Purchase price in dollars (-1 = not set).
        warranty_expires: Warranty expiration date (YYYY-MM-DD).
        notes: Additional notes.

    Returns:
        Confirmation with appliance ID.

    Ack: Adding appliance "{name}"...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        appliance_id = f"ha-{uuid.uuid4().hex[:8]}"
        appliance = {
            "id": appliance_id,
            "name": name.strip(),
            "appliance_type": appliance_type.strip() if appliance_type else "General",
            "brand": brand.strip() if brand else "",
            "model": model.strip() if model else "",
            "serial_number": serial_number.strip() if serial_number else "",
            "location": location.strip() if location else "",
            "purchase_date": purchase_date.strip() if purchase_date and purchase_date.strip() else None,
            "purchase_price": purchase_price if purchase_price is not None and purchase_price >= 0 else None,
            "warranty_expires": warranty_expires.strip() if warranty_expires and warranty_expires.strip() else None,
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip() if created_by else "",
        }
        result = _dl.create_appliance(appliance)
        if not result:
            return "Error: Failed to create appliance."
        loc_str = f" in {location.strip()}" if location and location.strip() else ""
        logger.info("HOME: Created appliance '%s' (%s)", name.strip(), appliance_id)
        return f"Appliance added: '{name.strip()}' ({appliance_id}){loc_str} — type: {appliance['appliance_type']}"
    except Exception as e:
        return f"Error in create_home_appliance: {str(e)}"


def list_home_appliances(appliance_type: str = "", location: str = "") -> str:
    """List household appliances.

    Args:
        appliance_type: Filter by type (e.g. "Refrigerator", "Dishwasher"). Empty = all.
        location: Filter by location (e.g. "Kitchen", "Garage"). Empty = all locations.

    Returns:
        Formatted list of appliances with brand/model and warranty status.

    Ack: Listing home appliances...
    """
    try:
        from datetime import date
        appliances = _dl.get_all_appliances(
            appliance_type=appliance_type.strip() if appliance_type else None,
            location=location.strip() if location else None,
        )
        if not appliances:
            return "No appliances found."

        today = date.today()
        lines = [f"Home Appliances ({len(appliances)}):\n"]
        for a in appliances:
            bm = " ".join(x for x in [a.get("brand"), a.get("model")] if x)
            bm = f" — {bm}" if bm else ""
            loc = f" @ {a['location']}" if a.get("location") else ""
            warranty = ""
            if a.get("warranty_expires"):
                exp = date.fromisoformat(a["warranty_expires"])
                if exp < today:
                    warranty = f" 🔴 warranty expired {a['warranty_expires']}"
                elif (exp - today).days <= 30:
                    warranty = f" 🟡 warranty expires {a['warranty_expires']}"
                else:
                    warranty = f" 🟢 warranty until {a['warranty_expires']}"
            lines.append(f"- {a['name']} [{a['appliance_type']}]{bm}{loc}{warranty} ({a['id']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_home_appliances: {str(e)}"


def get_home_appliance(appliance_id: str) -> str:
    """Get full details of a household appliance.

    Args:
        appliance_id: The appliance ID (ha-xxx).

    Returns:
        Full appliance details.

    Ack: Loading appliance details...
    """
    try:
        if not appliance_id or not appliance_id.strip():
            return "Error: appliance_id is required."
        a = _dl.get_appliance(appliance_id.strip())
        if not a:
            return f"Error: Appliance '{appliance_id}' not found."

        bm = " ".join(x for x in [a.get("brand"), a.get("model")] if x)
        brand_model = f"\nBrand/Model: {bm}" if bm else ""
        serial = f"\nSerial: {a['serial_number']}" if a.get("serial_number") else ""
        loc = f"\nLocation: {a['location']}" if a.get("location") else ""
        purchased = f"\nPurchased: {a['purchase_date']}" if a.get("purchase_date") else ""
        price = f"\nPrice: ${a['purchase_price']:.2f}" if a.get("purchase_price") is not None else ""
        warranty = f"\nWarranty expires: {a['warranty_expires']}" if a.get("warranty_expires") else ""
        notes = f"\nNotes: {a['notes']}" if a.get("notes") else ""

        return (
            f"{a['name']} ({a['id']})\n"
            f"Type: {a.get('appliance_type', 'General')}"
            f"{brand_model}{serial}{loc}{purchased}{price}{warranty}{notes}"
        ).strip()
    except Exception as e:
        return f"Error in get_home_appliance: {str(e)}"


def update_home_appliance(
    appliance_id: str,
    name: str = "",
    appliance_type: str = "",
    brand: str = "",
    model: str = "",
    serial_number: str = "",
    location: str = "",
    purchase_date: str = "",
    purchase_price: float = -1.0,
    warranty_expires: str = "",
    notes: str = "",
) -> str:
    """Update a household appliance. Only provided fields are changed.

    Args:
        appliance_id: The appliance ID (ha-xxx).
        name: New name (empty = keep).
        appliance_type: New type (empty = keep).
        brand: New brand (empty = keep).
        model: New model (empty = keep).
        serial_number: New serial number (empty = keep).
        location: New location (empty = keep).
        purchase_date: New purchase date YYYY-MM-DD (empty = keep).
        purchase_price: New price (-1 = keep, 0 = clear).
        warranty_expires: New warranty date YYYY-MM-DD (empty = keep).
        notes: New notes (empty = keep).

    Returns:
        Confirmation of update.

    Ack: Updating appliance {appliance_id}...
    """
    try:
        if not appliance_id or not appliance_id.strip():
            return "Error: appliance_id is required."
        updates = {}
        if name: updates["name"] = name.strip()
        if appliance_type: updates["appliance_type"] = appliance_type.strip()
        if brand: updates["brand"] = brand.strip()
        if model: updates["model"] = model.strip()
        if serial_number: updates["serial_number"] = serial_number.strip()
        if location: updates["location"] = location.strip()
        if purchase_date: updates["purchase_date"] = purchase_date.strip()
        if purchase_price >= 0: updates["purchase_price"] = purchase_price or None
        if warranty_expires: updates["warranty_expires"] = warranty_expires.strip()
        if notes: updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."
        ok = _dl.update_appliance(appliance_id.strip(), updates)
        if ok:
            fields = ", ".join(updates.keys())
            return f"Appliance {appliance_id} updated. Changed: {fields}"
        return f"Error: Appliance '{appliance_id}' not found."
    except Exception as e:
        return f"Error in update_home_appliance: {str(e)}"


def delete_home_appliance(appliance_id: str) -> str:
    """Delete a household appliance permanently.

    Args:
        appliance_id: The appliance ID (ha-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting appliance {appliance_id}...
    """
    try:
        if not appliance_id or not appliance_id.strip():
            return "Error: appliance_id is required."
        ok = _dl.delete_appliance(appliance_id.strip())
        if ok:
            return f"Appliance '{appliance_id}' deleted."
        return f"Error: Appliance '{appliance_id}' not found."
    except Exception as e:
        return f"Error in delete_home_appliance: {str(e)}"


# ---------------------------------------------------------------------------
# Maintenance Task — update / delete / log
# ---------------------------------------------------------------------------

def update_home_task(
    task_id: str,
    name: str = "",
    description: str = "",
    category: str = "",
    task_type: str = "",
    interval_days: int = -1,
    next_due_at: str = "",
    active: bool | None = None,
    notes: str = "",
) -> str:
    """Update an existing home maintenance task.

    Args:
        task_id: Task ID (hmt-xxx).
        name: New name (empty = keep).
        description: New description (empty = keep).
        category: New category (empty = keep).
        task_type: "recurring" or "adhoc" (empty = keep).
        interval_days: New interval in days (-1 = keep, 0 = clear).
        next_due_at: New next due date YYYY-MM-DD (empty = keep).
        active: True = activate, False = deactivate, None = keep.
        notes: New notes (empty = keep).

    Returns:
        Confirmation of what was updated.

    Ack: Updating task {task_id}...
    """
    try:
        if not task_id or not task_id.strip():
            return "Error: task_id is required."
        updates = {}
        if name: updates["name"] = name.strip()
        if description: updates["description"] = description.strip()
        if category: updates["category"] = category.strip()
        if task_type: updates["task_type"] = task_type.strip()
        if interval_days >= 0: updates["interval_days"] = interval_days or None
        if next_due_at: updates["next_due_at"] = next_due_at.strip()
        if active is not None: updates["active"] = active
        if notes: updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."
        ok = _dl.update_task(task_id.strip(), updates)
        if ok:
            fields = ", ".join(updates.keys())
            return f"Task {task_id} updated. Changed: {fields}"
        return f"Error: Task '{task_id}' not found."
    except Exception as e:
        return f"Error in update_home_task: {str(e)}"


def delete_home_task(task_id: str) -> str:
    """Delete a home maintenance task and its completion history permanently.

    Args:
        task_id: Task ID (hmt-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting task {task_id}...
    """
    try:
        if not task_id or not task_id.strip():
            return "Error: task_id is required."
        ok = _dl.delete_task(task_id.strip())
        if ok:
            return f"Task '{task_id}' deleted."
        return f"Error: Task '{task_id}' not found."
    except Exception as e:
        return f"Error in delete_home_task: {str(e)}"


def get_recent_maintenance_log(limit: int = 20) -> str:
    """Get the most recent home maintenance completions across all tasks.

    Args:
        limit: How many recent entries to show (default 20).

    Returns:
        Formatted completion log.

    Ack: Loading maintenance log...
    """
    try:
        entries = _dl.get_recent_log(limit=limit if limit > 0 else 20)
        if not entries:
            return "No maintenance log entries yet."
        lines = [f"Recent maintenance completions ({len(entries)}):\n"]
        for e in entries:
            task = e.get("task_name") or e.get("task_id", "?")
            by = f" by {e['completed_by']}" if e.get("completed_by") else ""
            note = f" — {e['notes']}" if e.get("notes") else ""
            lines.append(f"- ✓ [{e.get('completed_at', '?')}] {task}{by}{note} ({e['id']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_recent_maintenance_log: {str(e)}"


def delete_maintenance_log_entry(log_id: str) -> str:
    """Delete a specific maintenance log entry (completion record).

    Args:
        log_id: Log entry ID from get_recent_maintenance_log or get_home_task.

    Returns:
        Confirmation or error.

    Ack: Deleting log entry {log_id}...
    """
    try:
        if not log_id or not log_id.strip():
            return "Error: log_id is required."
        ok = _dl.delete_log_entry(log_id.strip())
        if ok:
            return f"Log entry '{log_id}' deleted."
        return f"Error: Log entry '{log_id}' not found."
    except Exception as e:
        return f"Error in delete_maintenance_log_entry: {str(e)}"


# ---------------------------------------------------------------------------
# Task Categories
# ---------------------------------------------------------------------------

def list_task_categories() -> str:
    """List all home maintenance task categories.

    Returns:
        Formatted list of categories with IDs.

    Ack: Loading task categories...
    """
    try:
        cats = _dl.get_all_task_categories()
        if not cats:
            return "No task categories defined."
        lines = [f"Task categories ({len(cats)}):\n"]
        for c in cats:
            lines.append(f"- {c['name']} ({c['id']}) [color: {c.get('color', 'slate')}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_task_categories: {str(e)}"


def create_task_category(name: str, color: str = "slate") -> str:
    """Create a new home maintenance task category.

    Args:
        name: Category name (e.g. "Roofing", "Landscaping", "Pool").
        color: UI color label (e.g. "slate", "blue", "green", "red", "orange", "yellow").

    Returns:
        Confirmation with category ID.

    Ack: Creating task category "{name}"...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        cat_id = f"htcat-{uuid.uuid4().hex[:8]}"
        cat = _dl.create_task_category(cat_id, name.strip(), color.strip() if color else "slate")
        if cat:
            return f"Task category created: '{cat['name']}' ({cat['id']})"
        return "Error: Category creation failed (name may already exist)."
    except Exception as e:
        return f"Error in create_task_category: {str(e)}"


def update_task_category(cat_id: str, name: str = "", color: str = "", sort_order: int = -1) -> str:
    """Update a home maintenance task category.

    Args:
        cat_id: Category ID (htcat-xxx).
        name: New name (empty = keep).
        color: New color (empty = keep).
        sort_order: New sort position (-1 = keep).

    Returns:
        Confirmation or error.

    Ack: Updating category {cat_id}...
    """
    try:
        if not cat_id or not cat_id.strip():
            return "Error: cat_id is required."
        updates = {}
        if name: updates["name"] = name.strip()
        if color: updates["color"] = color.strip()
        if sort_order >= 0: updates["sort_order"] = sort_order
        if not updates:
            return "No fields to update."
        ok = _dl.update_task_category(cat_id.strip(), updates)
        if ok:
            return f"Category {cat_id} updated. Changed: {', '.join(updates.keys())}"
        return f"Error: Category '{cat_id}' not found."
    except Exception as e:
        return f"Error in update_task_category: {str(e)}"


def delete_task_category(cat_id: str) -> str:
    """Delete a home maintenance task category.

    Args:
        cat_id: Category ID (htcat-xxx).

    Returns:
        Confirmation or error.

    Ack: Deleting category {cat_id}...
    """
    try:
        if not cat_id or not cat_id.strip():
            return "Error: cat_id is required."
        ok = _dl.delete_task_category(cat_id.strip())
        if ok:
            return f"Category '{cat_id}' deleted."
        return f"Error: Category '{cat_id}' not found."
    except Exception as e:
        return f"Error in delete_task_category: {str(e)}"


def get_overdue_home_tasks() -> str:
    """Get all overdue or due-soon home maintenance tasks.

    Use when user asks "what home maintenance is due?" or "what's overdue around the house?"

    Returns:
        List of overdue and upcoming tasks.

    Ack: Checking home maintenance schedule...
    """
    try:
        from datetime import date
        tasks = _dl.get_due_tasks(days_ahead=14)
        if not tasks:
            return "No home maintenance tasks are due in the next 2 weeks."

        today = date.today()
        overdue, due_soon = [], []
        for t in tasks:
            if t.get("next_due_at"):
                due = date.fromisoformat(t["next_due_at"])
                if due < today:
                    overdue.append((t, due))
                else:
                    due_soon.append((t, due))

        lines = []
        if overdue:
            lines.append(f"🔴 Overdue ({len(overdue)}):")
            for t, due in overdue:
                days = (today - due).days
                lines.append(f"  • {t['name']} [{t['category']}] — {days}d overdue")
        if due_soon:
            lines.append(f"\n🟡 Due within 2 weeks ({len(due_soon)}):")
            for t, due in due_soon:
                days = (due - today).days
                lines.append(f"  • {t['name']} [{t['category']}] — due in {days}d ({t['next_due_at']})")
        return "\n".join(lines) if lines else "All home maintenance is on schedule."

    except Exception as e:
        return f"Error in get_overdue_home_tasks: {str(e)}"
