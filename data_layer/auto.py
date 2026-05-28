"""DEPRECATED — Moved to apps/auto/data.py (app package).
This file is no longer imported. Safe to delete.

Original: Auto Maintenance — Postgres CRUD
Data layer for vehicles, service records, issues, valuations, conditions, and images.
"""

import logging
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def save_vehicle(vehicle: dict):
    """Insert or update a vehicle."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicles (id, name, make, model, trim_level, year, vin, license_plate,
                                      odometer, color, notes, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    make = EXCLUDED.make,
                    model = EXCLUDED.model,
                    trim_level = EXCLUDED.trim_level,
                    year = EXCLUDED.year,
                    vin = EXCLUDED.vin,
                    license_plate = EXCLUDED.license_plate,
                    odometer = EXCLUDED.odometer,
                    color = EXCLUDED.color,
                    notes = EXCLUDED.notes,
                    updated_at = EXCLUDED.updated_at
            """, (
                vehicle["id"],
                vehicle.get("name", ""),
                vehicle.get("make", ""),
                vehicle.get("model", ""),
                vehicle.get("trim_level", ""),
                vehicle.get("year"),
                vehicle.get("vin", ""),
                vehicle.get("license_plate", ""),
                vehicle.get("odometer"),
                vehicle.get("color", ""),
                vehicle.get("notes", ""),
                vehicle.get("created_by", ""),
                vehicle.get("created_at", _now()),
                vehicle.get("updated_at", _now()),
            ))
        conn.commit()


def get_vehicle(vehicle_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM vehicles WHERE id = %s", (vehicle_id,))
    return _vehicle_row(row) if row else None


def get_all_vehicles() -> list[dict]:
    return [_vehicle_row(r) for r in fetch_all(
        "SELECT * FROM vehicles ORDER BY year DESC NULLS LAST, name"
    )]


def search_vehicles(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all(
        """SELECT * FROM vehicles
           WHERE name ILIKE %s OR make ILIKE %s OR model ILIKE %s
                 OR vin ILIKE %s OR license_plate ILIKE %s OR color ILIKE %s OR notes ILIKE %s
           ORDER BY name""",
        (pattern, pattern, pattern, pattern, pattern, pattern, pattern),
    )
    return [_vehicle_row(r) for r in rows]


def update_vehicle(vehicle_id: str, updates: dict) -> bool:
    allowed = {"name", "make", "model", "trim_level", "year", "vin", "license_plate", "odometer", "color", "notes"}
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(vehicle_id)
    return execute(
        f"UPDATE vehicles SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_vehicle(vehicle_id: str) -> bool:
    return execute("DELETE FROM vehicles WHERE id = %s", (vehicle_id,)) > 0


# ---------------------------------------------------------------------------
# Service Records
# ---------------------------------------------------------------------------

def save_service_record(record: dict):
    """Insert a service record."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO service_records (id, vehicle_id, service_type, description,
                                             date_performed, odometer_at_service, cost,
                                             shop_name, next_due_date, next_due_mileage,
                                             reminder_id, notes, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                record["id"],
                record["vehicle_id"],
                record.get("service_type", ""),
                record.get("description", ""),
                record.get("date_performed"),
                record.get("odometer_at_service"),
                record.get("cost"),
                record.get("shop_name", ""),
                record.get("next_due_date"),
                record.get("next_due_mileage"),
                record.get("reminder_id"),
                record.get("notes", ""),
                record.get("created_by", ""),
                record.get("created_at", _now()),
            ))
        conn.commit()
    ensure_edge(record["id"], record["vehicle_id"], "child_of", "parent_of")


def get_service_records(vehicle_id: str) -> list[dict]:
    return [_service_row(r) for r in fetch_all(
        "SELECT * FROM service_records WHERE vehicle_id = %s ORDER BY date_performed DESC, created_at DESC",
        (vehicle_id,),
    )]


def get_service_record(record_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM service_records WHERE id = %s", (record_id,))
    return _service_row(row) if row else None


def search_service_records(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all(
        """SELECT sr.*, v.name as vehicle_name FROM service_records sr
           JOIN vehicles v ON v.id = sr.vehicle_id
           WHERE sr.service_type ILIKE %s OR sr.description ILIKE %s
                 OR sr.shop_name ILIKE %s OR sr.notes ILIKE %s
                 OR v.name ILIKE %s
           ORDER BY sr.date_performed DESC""",
        (pattern, pattern, pattern, pattern, pattern),
    )
    return [_service_row(r) for r in rows]


def get_upcoming_maintenance() -> list[dict]:
    """Return service records with upcoming due dates or mileage."""
    rows = fetch_all(
        """SELECT sr.*, v.name as vehicle_name, v.odometer as current_odometer
           FROM service_records sr
           JOIN vehicles v ON v.id = sr.vehicle_id
           WHERE sr.next_due_date IS NOT NULL OR sr.next_due_mileage IS NOT NULL
           ORDER BY sr.next_due_date ASC NULLS LAST"""
    )
    return [_service_row(r) for r in rows]


def update_service_record(record_id: str, updates: dict) -> bool:
    allowed = {
        "service_type", "description", "date_performed", "odometer_at_service",
        "cost", "shop_name", "next_due_date", "next_due_mileage", "reminder_id", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    vals.append(record_id)
    return execute(
        f"UPDATE service_records SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_service_record(record_id: str) -> bool:
    return execute("DELETE FROM service_records WHERE id = %s", (record_id,)) > 0


# ---------------------------------------------------------------------------
# Vehicle Issues
# ---------------------------------------------------------------------------

def save_issue(issue: dict):
    """Insert a vehicle issue."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicle_issues (id, vehicle_id, title, description, severity,
                                            status, date_noticed, date_fixed,
                                            fix_description, cost, notes,
                                            created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                issue["id"],
                issue["vehicle_id"],
                issue.get("title", ""),
                issue.get("description", ""),
                issue.get("severity", "minor"),
                issue.get("status", "open"),
                issue.get("date_noticed"),
                issue.get("date_fixed"),
                issue.get("fix_description", ""),
                issue.get("cost"),
                issue.get("notes", ""),
                issue.get("created_by", ""),
                issue.get("created_at", _now()),
                issue.get("updated_at", _now()),
            ))
        conn.commit()
    ensure_edge(issue["id"], issue["vehicle_id"], "child_of", "parent_of")


def get_issues(vehicle_id: str, status: str = None) -> list[dict]:
    if status:
        return [_issue_row(r) for r in fetch_all(
            "SELECT * FROM vehicle_issues WHERE vehicle_id = %s AND status = %s ORDER BY created_at DESC",
            (vehicle_id, status),
        )]
    return [_issue_row(r) for r in fetch_all(
        "SELECT * FROM vehicle_issues WHERE vehicle_id = %s ORDER BY status != 'open', created_at DESC",
        (vehicle_id,),
    )]


def get_issue(issue_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM vehicle_issues WHERE id = %s", (issue_id,))
    return _issue_row(row) if row else None


def update_issue(issue_id: str, updates: dict) -> bool:
    allowed = {
        "title", "description", "severity", "status", "date_noticed",
        "date_fixed", "fix_description", "cost", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    sets.append("updated_at = %s")
    vals.append(_now())
    vals.append(issue_id)
    return execute(
        f"UPDATE vehicle_issues SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0


def delete_issue(issue_id: str) -> bool:
    return execute("DELETE FROM vehicle_issues WHERE id = %s", (issue_id,)) > 0


def get_all_open_issues() -> list[dict]:
    """Get all open issues across all vehicles."""
    rows = fetch_all(
        """SELECT vi.*, v.name as vehicle_name FROM vehicle_issues vi
           JOIN vehicles v ON v.id = vi.vehicle_id
           WHERE vi.status != 'fixed'
           ORDER BY
             CASE vi.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1
                              WHEN 'moderate' THEN 2 ELSE 3 END,
             vi.created_at DESC"""
    )
    return [_issue_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Vehicle Valuations
# ---------------------------------------------------------------------------

def save_valuation(val: dict):
    """Insert a vehicle valuation record."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicle_valuations (id, vehicle_id, date_recorded,
                    private_party_value, trade_in_value, condition,
                    mileage_at_valuation, source, notes, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                val["id"],
                val["vehicle_id"],
                val["date_recorded"],
                val.get("private_party_value"),
                val.get("trade_in_value"),
                val.get("condition", "good"),
                val.get("mileage_at_valuation"),
                val.get("source", "kbb"),
                val.get("notes", ""),
                val.get("created_by", ""),
                val.get("created_at", _now()),
            ))
        conn.commit()
    ensure_edge(val["id"], val["vehicle_id"], "child_of", "parent_of")


def get_valuations(vehicle_id: str) -> list[dict]:
    return [_valuation_row(r) for r in fetch_all(
        "SELECT * FROM vehicle_valuations WHERE vehicle_id = %s ORDER BY date_recorded DESC",
        (vehicle_id,),
    )]


def delete_valuation(val_id: str) -> bool:
    return execute("DELETE FROM vehicle_valuations WHERE id = %s", (val_id,)) > 0


# ---------------------------------------------------------------------------
# Vehicle Conditions
# ---------------------------------------------------------------------------

def save_condition(cond: dict):
    """Insert a vehicle condition report."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicle_conditions (id, vehicle_id, date_recorded,
                    mileage_at_report, brakes, tires, tire_tread_depth, oil_life_pct,
                    battery, exterior, interior, lights_signals, fluids,
                    notes, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                cond["id"],
                cond["vehicle_id"],
                cond["date_recorded"],
                cond.get("mileage_at_report"),
                cond.get("brakes", "good"),
                cond.get("tires", "good"),
                cond.get("tire_tread_depth"),
                cond.get("oil_life_pct"),
                cond.get("battery", "good"),
                cond.get("exterior", "good"),
                cond.get("interior", "good"),
                cond.get("lights_signals", "all_working"),
                cond.get("fluids", "all_good"),
                cond.get("notes", ""),
                cond.get("created_by", ""),
                cond.get("created_at", _now()),
            ))
        conn.commit()
    ensure_edge(cond["id"], cond["vehicle_id"], "child_of", "parent_of")


def get_conditions(vehicle_id: str) -> list[dict]:
    return [_condition_row(r) for r in fetch_all(
        "SELECT * FROM vehicle_conditions WHERE vehicle_id = %s ORDER BY date_recorded DESC",
        (vehicle_id,),
    )]


def get_latest_condition(vehicle_id: str) -> dict | None:
    row = fetch_one(
        "SELECT * FROM vehicle_conditions WHERE vehicle_id = %s ORDER BY date_recorded DESC LIMIT 1",
        (vehicle_id,),
    )
    return _condition_row(row) if row else None


def delete_condition(cond_id: str) -> bool:
    return execute("DELETE FROM vehicle_conditions WHERE id = %s", (cond_id,)) > 0


# ---------------------------------------------------------------------------
# Vehicle Images (polymorphic: vehicle, issue, or condition)
# ---------------------------------------------------------------------------

def get_vehicle_images(vehicle_id: str) -> list[dict]:
    rows = fetch_all(
        """SELECT i.*, vi.sort_order FROM images i
           JOIN vehicle_images vi ON vi.image_id = i.id
           WHERE vi.vehicle_id = %s
           ORDER BY vi.sort_order, i.created_at""",
        (vehicle_id,),
    )
    return [_image_row(r) for r in rows]


def get_issue_images(issue_id: str) -> list[dict]:
    rows = fetch_all(
        """SELECT i.*, vi.sort_order FROM images i
           JOIN vehicle_images vi ON vi.image_id = i.id
           WHERE vi.issue_id = %s
           ORDER BY vi.sort_order, i.created_at""",
        (issue_id,),
    )
    return [_image_row(r) for r in rows]


def get_condition_images(condition_id: str) -> list[dict]:
    rows = fetch_all(
        """SELECT i.*, vi.sort_order FROM images i
           JOIN vehicle_images vi ON vi.image_id = i.id
           WHERE vi.condition_id = %s
           ORDER BY vi.sort_order, i.created_at""",
        (condition_id,),
    )
    return [_image_row(r) for r in rows]


def link_image_to_vehicle(vehicle_id: str, image_id: str, sort_order: int = 0):
    execute(
        """INSERT INTO vehicle_images (image_id, vehicle_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, vehicle_id, sort_order),
    )


def link_image_to_issue(issue_id: str, image_id: str, sort_order: int = 0):
    execute(
        """INSERT INTO vehicle_images (image_id, issue_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, issue_id, sort_order),
    )


def link_image_to_condition(condition_id: str, image_id: str, sort_order: int = 0):
    execute(
        """INSERT INTO vehicle_images (image_id, condition_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, condition_id, sort_order),
    )


def unlink_image(image_id: str):
    execute("DELETE FROM vehicle_images WHERE image_id = %s", (image_id,))


# ---------------------------------------------------------------------------
# Vehicle Maintenance Schedules (linked schedules)
# ---------------------------------------------------------------------------

def get_vehicle_maintenance(vehicle_id: str) -> list[dict]:
    """Get active maintenance schedules linked to a vehicle."""
    rows = fetch_all(
        """SELECT * FROM schedules
           WHERE linked_entity_type = 'vehicle'
             AND linked_entity_id = %s
             AND active = TRUE
           ORDER BY next_due ASC NULLS LAST""",
        (vehicle_id,),
    )
    from data_layer.schedules import _row_to_dict, describe_recurrence
    result = []
    for r in rows:
        d = _row_to_dict(r)
        if d:
            d["recurrence_description"] = describe_recurrence(
                d.get("recurrence_type", ""),
                d.get("recurrence_rule") or {},
            )
            result.append(d)
    return result


def complete_maintenance(
    schedule_id: str,
    vehicle_id: str,
    completed_by: str = "",
    service_type: str = "",
    date_performed: str = "",
    odometer: int | None = None,
    cost: float | None = None,
    shop_name: str = "",
    notes: str = "",
) -> dict:
    """Complete a maintenance schedule: advance the schedule + create a service record.

    Returns: { schedule, service_record }
    """
    import uuid
    from data_layer.schedules import complete_schedule, get_schedule

    # 1. Complete the schedule (advances next_due)
    sch = complete_schedule(schedule_id, completed_by=completed_by, notes=notes)
    if not sch:
        return {"error": "Schedule not found"}

    # 2. Create a service record for the completed maintenance
    svc_id = f"svc-{uuid.uuid4().hex[:8]}"
    record = {
        "id": svc_id,
        "vehicle_id": vehicle_id,
        "service_type": service_type or sch.get("title", "Maintenance"),
        "description": f"Completed scheduled maintenance: {sch.get('title', '')}",
        "date_performed": date_performed or _now()[:10],
        "odometer_at_service": odometer,
        "cost": cost,
        "shop_name": shop_name,
        "notes": notes,
        "created_by": completed_by,
        "created_at": _now(),
    }
    save_service_record(record)

    # 3. Update vehicle odometer if provided
    if odometer:
        execute(
            "UPDATE vehicles SET odometer = %s, updated_at = %s WHERE id = %s AND (odometer IS NULL OR odometer < %s)",
            (odometer, _now(), vehicle_id, odometer),
        )

    return {
        "schedule": sch,
        "service_record": _service_row(fetch_one(
            "SELECT * FROM service_records WHERE id = %s", (svc_id,)
        )),
    }


# ---------------------------------------------------------------------------
# Summary helpers (for list view cards)
# ---------------------------------------------------------------------------

def get_vehicle_summary(vehicle_id: str) -> dict:
    """Get summary info for a vehicle card: next service, open issues, latest condition."""
    # Next upcoming service
    next_svc = fetch_one(
        """SELECT service_type, next_due_date, next_due_mileage
           FROM service_records
           WHERE vehicle_id = %s AND (next_due_date IS NOT NULL OR next_due_mileage IS NOT NULL)
           ORDER BY next_due_date ASC NULLS LAST
           LIMIT 1""",
        (vehicle_id,),
    )
    # Open issue count
    issue_row = fetch_one(
        "SELECT COUNT(*) as cnt FROM vehicle_issues WHERE vehicle_id = %s AND status != 'fixed'",
        (vehicle_id,),
    )
    # Latest condition
    latest_cond = get_latest_condition(vehicle_id)
    return {
        "next_service": _service_row(next_svc) if next_svc else None,
        "open_issue_count": issue_row["cnt"] if issue_row else 0,
        "latest_condition": latest_cond,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vehicle_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "make": row.get("make") or "",
        "model": row.get("model") or "",
        "trim_level": row.get("trim_level") or "",
        "year": row.get("year"),
        "color": row.get("color") or "",
        "vin": row.get("vin") or "",
        "license_plate": row.get("license_plate") or "",
        "odometer": row.get("odometer"),
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _service_row(row: dict) -> dict:
    if not row:
        return {}
    result = {
        "id": row.get("id") or "",
        "vehicle_id": row.get("vehicle_id") or "",
        "service_type": row.get("service_type") or "",
        "description": row.get("description") or "",
        "date_performed": row["date_performed"].isoformat() if row.get("date_performed") else "",
        "odometer_at_service": row.get("odometer_at_service"),
        "cost": float(row["cost"]) if row.get("cost") is not None else None,
        "shop_name": row.get("shop_name") or "",
        "next_due_date": row["next_due_date"].isoformat() if row.get("next_due_date") else "",
        "next_due_mileage": row.get("next_due_mileage"),
        "reminder_id": row.get("reminder_id") or "",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
    if row.get("vehicle_name"):
        result["vehicle_name"] = row["vehicle_name"]
    if row.get("current_odometer") is not None:
        result["current_odometer"] = row["current_odometer"]
    return result


def _issue_row(row: dict) -> dict:
    if not row:
        return {}
    result = {
        "id": row["id"],
        "vehicle_id": row.get("vehicle_id") or "",
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "severity": row.get("severity") or "minor",
        "status": row.get("status") or "open",
        "date_noticed": row["date_noticed"].isoformat() if row.get("date_noticed") else "",
        "date_fixed": row["date_fixed"].isoformat() if row.get("date_fixed") else "",
        "fix_description": row.get("fix_description") or "",
        "cost": float(row["cost"]) if row.get("cost") is not None else None,
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }
    if row.get("vehicle_name"):
        result["vehicle_name"] = row["vehicle_name"]
    return result


def _valuation_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "vehicle_id": row.get("vehicle_id") or "",
        "date_recorded": row["date_recorded"].isoformat() if row.get("date_recorded") else "",
        "private_party_value": float(row["private_party_value"]) if row.get("private_party_value") is not None else None,
        "trade_in_value": float(row["trade_in_value"]) if row.get("trade_in_value") is not None else None,
        "condition": row.get("condition") or "good",
        "mileage_at_valuation": row.get("mileage_at_valuation"),
        "source": row.get("source") or "kbb",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _condition_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "vehicle_id": row.get("vehicle_id") or "",
        "date_recorded": row["date_recorded"].isoformat() if row.get("date_recorded") else "",
        "mileage_at_report": row.get("mileage_at_report"),
        "brakes": row.get("brakes") or "good",
        "tires": row.get("tires") or "good",
        "tire_tread_depth": float(row["tire_tread_depth"]) if row.get("tire_tread_depth") is not None else None,
        "oil_life_pct": row.get("oil_life_pct"),
        "battery": row.get("battery") or "good",
        "exterior": row.get("exterior") or "good",
        "interior": row.get("interior") or "good",
        "lights_signals": row.get("lights_signals") or "all_working",
        "fluids": row.get("fluids") or "all_good",
        "notes": row.get("notes") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }


def _image_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "filename": row.get("filename") or "",
        "mime_type": row.get("mime_type") or "",
        "size_bytes": row.get("size_bytes", 0),
        "storage_path": row.get("storage_path") or "",
        "sort_order": row.get("sort_order", 0),
        "uploaded_by": row.get("uploaded_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
