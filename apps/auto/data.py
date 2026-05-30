"""Auto Maintenance — Schema-aware data layer
===============================================
All queries target the app_auto schema via app_platform.db helpers.
Cross-schema references (public.images, app_schedules.schedules) use explicit schema prefixes.
"""

import logging
from datetime import datetime, timezone

from app_platform.db import (
    fetch_one_in_schema,
    fetch_all_in_schema,
    execute_in_schema,
    execute_returning_in_schema,
    scoped_conn,
)
from data_layer.links import ensure_edge
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

SCHEMA = "app_auto"

_VEHICLE_HINT = (
    "Focus on: vehicle year, make, model, trim level, color, current odometer, "
    "owner or responsible user, and any notable notes."
)
_SERVICE_HINT = (
    "Focus on: vehicle ID, service type, date performed, odometer at service, "
    "cost, shop name, description of work done, and next due date or mileage."
)
_ISSUE_HINT = (
    "Focus on: vehicle ID, issue title, description, severity (minor/moderate/major/critical), "
    "status (open/fixed), date noticed, fix description if resolved, and cost."
)
_VALUATION_HINT = (
    "Focus on: vehicle ID, date recorded, private party value, trade-in value, "
    "condition rating, mileage at valuation, and source (e.g. KBB)."
)
_CONDITION_HINT = (
    "Focus on: vehicle ID, date recorded, mileage, brakes, tires (with tread depth), "
    "battery, exterior, interior, lights/signals, fluids, oil life percentage, and notes."
)


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
        "responsible_user": row.get("responsible_user") or "",
        "owner": row.get("owner") or "",
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


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def save_vehicle(vehicle: dict, by: str = ""):
    """Insert or update a vehicle."""
    is_new = get_vehicle(vehicle["id"]) is None
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vehicles (id, name, make, model, trim_level, year, vin, license_plate,
                                      odometer, color, notes, responsible_user, owner, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
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
                    responsible_user = EXCLUDED.responsible_user,
                    owner = EXCLUDED.owner,
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
                vehicle.get("responsible_user", ""),
                vehicle.get("owner", ""),
                vehicle.get("created_by", ""),
                vehicle.get("created_at", _now()),
                vehicle.get("updated_at", _now()),
            ))
        conn.commit()
    saved = get_vehicle(vehicle["id"])
    if saved:
        digest_record(
            app_id="auto",
            entity_type="vehicle",
            action="created" if is_new else "updated",
            entity_id=vehicle["id"],
            record=saved,
            by=by or vehicle.get("created_by", ""),
            context_hint=_VEHICLE_HINT,
        )


def get_vehicle(vehicle_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM vehicles WHERE id = %s", (vehicle_id,))
    return _vehicle_row(row) if row else None


def get_all_vehicles() -> list[dict]:
    return [_vehicle_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM vehicles ORDER BY year DESC NULLS LAST, name"
    )]


def search_vehicles(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT * FROM vehicles
           WHERE name ILIKE %s OR make ILIKE %s OR model ILIKE %s
                 OR vin ILIKE %s OR license_plate ILIKE %s OR color ILIKE %s OR notes ILIKE %s
           ORDER BY name""",
        (pattern, pattern, pattern, pattern, pattern, pattern, pattern),
    )
    return [_vehicle_row(r) for r in rows]


def update_vehicle(vehicle_id: str, updates: dict, by: str = "") -> bool:
    allowed = {"name", "make", "model", "trim_level", "year", "vin", "license_plate", "odometer", "color", "notes", "responsible_user", "owner"}
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
    ok = execute_in_schema(
        SCHEMA, f"UPDATE vehicles SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_vehicle(vehicle_id)
        if updated:
            digest_record(
                app_id="auto",
                entity_type="vehicle",
                action="updated",
                entity_id=vehicle_id,
                record=updated,
                by=by,
                context_hint=_VEHICLE_HINT,
            )
    return ok


def delete_vehicle(vehicle_id: str, by: str = "") -> bool:
    vehicle = get_vehicle(vehicle_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM vehicles WHERE id = %s", (vehicle_id,)) > 0
    if ok and vehicle:
        digest_record(
            app_id="auto",
            entity_type="vehicle",
            action="deleted",
            entity_id=vehicle_id,
            record=vehicle,
            by=by,
        )
    return ok


# ---------------------------------------------------------------------------
# Service Records
# ---------------------------------------------------------------------------

def save_service_record(record: dict, by: str = ""):
    """Insert a service record."""
    with scoped_conn(SCHEMA) as conn:
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
    saved = get_service_record(record["id"])
    if saved:
        digest_record(
            app_id="auto",
            entity_type="service_record",
            action="created",
            entity_id=record["id"],
            record=saved,
            by=by or record.get("created_by", ""),
            context_hint=_SERVICE_HINT,
        )


def get_service_records(vehicle_id: str) -> list[dict]:
    return [_service_row(r) for r in fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM service_records WHERE vehicle_id = %s ORDER BY date_performed DESC, created_at DESC",
        (vehicle_id,),
    )]


def get_service_record(record_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM service_records WHERE id = %s", (record_id,))
    return _service_row(row) if row else None


def search_service_records(query: str) -> list[dict]:
    pattern = f"%{query}%"
    rows = fetch_all_in_schema(
        SCHEMA,
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
    """Return upcoming maintenance: service records with future due dates/mileage
    AND platform schedules linked to vehicles."""
    from data_layer.db import fetch_all as _pub_fetch_all
    from apps.schedules.data import _row_to_dict as _sch_row, describe_recurrence

    # Service records with next_due_date or next_due_mileage
    svc_rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT sr.*, v.name as vehicle_name, v.odometer as current_odometer
           FROM service_records sr
           JOIN vehicles v ON v.id = sr.vehicle_id
           WHERE sr.next_due_date IS NOT NULL OR sr.next_due_mileage IS NOT NULL
           ORDER BY sr.next_due_date ASC NULLS LAST"""
    )
    results = [_service_row(r) for r in svc_rows]

    # Platform schedules linked to vehicles
    sch_rows = _pub_fetch_all(
        """SELECT s.*, v.name as vehicle_name
           FROM app_schedules.schedules s
           JOIN app_auto.vehicles v ON v.id = s.linked_entity_id
           WHERE s.linked_entity_type = 'vehicle'
             AND s.active = TRUE
             AND s.next_due IS NOT NULL
           ORDER BY s.next_due ASC"""
    )
    for r in sch_rows:
        d = _sch_row(r)
        if d:
            d["_type"] = "schedule"
            d["vehicle_name"] = r.get("vehicle_name") or d.get("linked_entity_id", "?")
            d["recurrence_description"] = describe_recurrence(
                d.get("recurrence_type", ""),
                d.get("recurrence_rule") or {},
            )
            results.append(d)

    return results


def update_service_record(record_id: str, updates: dict, by: str = "") -> bool:
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
    ok = execute_in_schema(
        SCHEMA, f"UPDATE service_records SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_service_record(record_id)
        if updated:
            digest_record(
                app_id="auto",
                entity_type="service_record",
                action="updated",
                entity_id=record_id,
                record=updated,
                by=by,
                context_hint=_SERVICE_HINT,
            )
    return ok


def delete_service_record(record_id: str, by: str = "") -> bool:
    record = get_service_record(record_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM service_records WHERE id = %s", (record_id,)) > 0
    if ok and record:
        digest_record(
            app_id="auto",
            entity_type="service_record",
            action="deleted",
            entity_id=record_id,
            record=record,
            by=by,
        )
    return ok


# ---------------------------------------------------------------------------
# Vehicle Issues
# ---------------------------------------------------------------------------

def save_issue(issue: dict, by: str = ""):
    """Insert a vehicle issue."""
    with scoped_conn(SCHEMA) as conn:
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
    saved = get_issue(issue["id"])
    if saved:
        digest_record(
            app_id="auto",
            entity_type="vehicle_issue",
            action="created",
            entity_id=issue["id"],
            record=saved,
            by=by or issue.get("created_by", ""),
            context_hint=_ISSUE_HINT,
        )


def get_issues(vehicle_id: str, status: str = None) -> list[dict]:
    if status:
        return [_issue_row(r) for r in fetch_all_in_schema(
            SCHEMA,
            "SELECT * FROM vehicle_issues WHERE vehicle_id = %s AND status = %s ORDER BY created_at DESC",
            (vehicle_id, status),
        )]
    return [_issue_row(r) for r in fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM vehicle_issues WHERE vehicle_id = %s ORDER BY status != 'open', created_at DESC",
        (vehicle_id,),
    )]


def get_issue(issue_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM vehicle_issues WHERE id = %s", (issue_id,))
    return _issue_row(row) if row else None


def update_issue(issue_id: str, updates: dict, by: str = "") -> bool:
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
    ok = execute_in_schema(
        SCHEMA, f"UPDATE vehicle_issues SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_issue(issue_id)
        if updated:
            digest_record(
                app_id="auto",
                entity_type="vehicle_issue",
                action="updated",
                entity_id=issue_id,
                record=updated,
                by=by,
                context_hint=_ISSUE_HINT,
            )
    return ok


def delete_issue(issue_id: str, by: str = "") -> bool:
    issue = get_issue(issue_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM vehicle_issues WHERE id = %s", (issue_id,)) > 0
    if ok and issue:
        digest_record(
            app_id="auto",
            entity_type="vehicle_issue",
            action="deleted",
            entity_id=issue_id,
            record=issue,
            by=by,
        )
    return ok


def get_all_open_issues() -> list[dict]:
    """Get all open issues across all vehicles."""
    rows = fetch_all_in_schema(
        SCHEMA,
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

def save_valuation(val: dict, by: str = ""):
    """Insert a vehicle valuation record."""
    with scoped_conn(SCHEMA) as conn:
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
    saved_val = fetch_one_in_schema(SCHEMA, "SELECT * FROM vehicle_valuations WHERE id = %s", (val["id"],))
    if saved_val:
        digest_record(
            app_id="auto",
            entity_type="vehicle_valuation",
            action="created",
            entity_id=val["id"],
            record=_valuation_row(saved_val),
            by=by or val.get("created_by", ""),
            context_hint=_VALUATION_HINT,
        )


def get_valuations(vehicle_id: str) -> list[dict]:
    return [_valuation_row(r) for r in fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM vehicle_valuations WHERE vehicle_id = %s ORDER BY date_recorded DESC",
        (vehicle_id,),
    )]


def delete_valuation(val_id: str, by: str = "") -> bool:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM vehicle_valuations WHERE id = %s", (val_id,))
    val = _valuation_row(row) if row else None
    ok = execute_in_schema(SCHEMA, "DELETE FROM vehicle_valuations WHERE id = %s", (val_id,)) > 0
    if ok and val:
        digest_record(
            app_id="auto",
            entity_type="vehicle_valuation",
            action="deleted",
            entity_id=val_id,
            record=val,
            by=by,
        )
    return ok


# ---------------------------------------------------------------------------
# Vehicle Conditions
# ---------------------------------------------------------------------------

def save_condition(cond: dict, by: str = ""):
    """Insert a vehicle condition report."""
    with scoped_conn(SCHEMA) as conn:
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
    saved_cond = get_condition(cond["id"])
    if saved_cond:
        digest_record(
            app_id="auto",
            entity_type="vehicle_condition",
            action="created",
            entity_id=cond["id"],
            record=saved_cond,
            by=by or cond.get("created_by", ""),
            context_hint=_CONDITION_HINT,
        )


def get_conditions(vehicle_id: str) -> list[dict]:
    return [_condition_row(r) for r in fetch_all_in_schema(
        SCHEMA,
        "SELECT * FROM vehicle_conditions WHERE vehicle_id = %s ORDER BY date_recorded DESC",
        (vehicle_id,),
    )]


def get_latest_condition(vehicle_id: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM vehicle_conditions WHERE vehicle_id = %s ORDER BY date_recorded DESC LIMIT 1",
        (vehicle_id,),
    )
    return _condition_row(row) if row else None


def get_condition(cond_id: str) -> dict | None:
    row = fetch_one_in_schema(SCHEMA, "SELECT * FROM vehicle_conditions WHERE id = %s", (cond_id,))
    return _condition_row(row) if row else None


def update_condition(cond_id: str, updates: dict, by: str = "") -> bool:
    allowed = {
        "date_recorded", "mileage_at_report", "brakes", "tires",
        "tire_tread_depth", "oil_life_pct", "battery", "exterior",
        "interior", "lights_signals", "fluids", "notes",
    }
    sets, vals = [], []
    for key, val in updates.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    if not sets:
        return False
    vals.append(cond_id)
    ok = execute_in_schema(
        SCHEMA, f"UPDATE vehicle_conditions SET {', '.join(sets)} WHERE id = %s", tuple(vals)
    ) > 0
    if ok:
        updated = get_condition(cond_id)
        if updated:
            digest_record(
                app_id="auto",
                entity_type="vehicle_condition",
                action="updated",
                entity_id=cond_id,
                record=updated,
                by=by,
                context_hint=_CONDITION_HINT,
            )
    return ok


def delete_condition(cond_id: str, by: str = "") -> bool:
    cond = get_condition(cond_id)
    ok = execute_in_schema(SCHEMA, "DELETE FROM vehicle_conditions WHERE id = %s", (cond_id,)) > 0
    if ok and cond:
        digest_record(
            app_id="auto",
            entity_type="vehicle_condition",
            action="deleted",
            entity_id=cond_id,
            record=cond,
            by=by,
        )
    return ok


# ---------------------------------------------------------------------------
# Vehicle Images (polymorphic: vehicle, issue, or condition)
# Images table lives in public schema — soft FK, no constraint.
# ---------------------------------------------------------------------------

def get_vehicle_images(vehicle_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, vi.sort_order FROM public.images i
           JOIN vehicle_images vi ON vi.image_id = i.id
           WHERE vi.vehicle_id = %s
           ORDER BY vi.sort_order, i.created_at""",
        (vehicle_id,),
    )
    return [_image_row(r) for r in rows]


def get_issue_images(issue_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, vi.sort_order FROM public.images i
           JOIN vehicle_images vi ON vi.image_id = i.id
           WHERE vi.issue_id = %s
           ORDER BY vi.sort_order, i.created_at""",
        (issue_id,),
    )
    return [_image_row(r) for r in rows]


def get_condition_images(condition_id: str) -> list[dict]:
    rows = fetch_all_in_schema(
        SCHEMA,
        """SELECT i.*, vi.sort_order FROM public.images i
           JOIN vehicle_images vi ON vi.image_id = i.id
           WHERE vi.condition_id = %s
           ORDER BY vi.sort_order, i.created_at""",
        (condition_id,),
    )
    return [_image_row(r) for r in rows]


def link_image_to_vehicle(vehicle_id: str, image_id: str, sort_order: int = 0):
    execute_in_schema(
        SCHEMA,
        """INSERT INTO vehicle_images (image_id, vehicle_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, vehicle_id, sort_order),
    )


def link_image_to_issue(issue_id: str, image_id: str, sort_order: int = 0):
    execute_in_schema(
        SCHEMA,
        """INSERT INTO vehicle_images (image_id, issue_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, issue_id, sort_order),
    )


def link_image_to_condition(condition_id: str, image_id: str, sort_order: int = 0):
    execute_in_schema(
        SCHEMA,
        """INSERT INTO vehicle_images (image_id, condition_id, sort_order)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
        (image_id, condition_id, sort_order),
    )


def unlink_image(image_id: str):
    execute_in_schema(SCHEMA, "DELETE FROM vehicle_images WHERE image_id = %s", (image_id,))


# ---------------------------------------------------------------------------
# Vehicle Maintenance Schedules (platform schedules linked to vehicle)
# ---------------------------------------------------------------------------

def get_vehicle_maintenance(vehicle_id: str) -> list[dict]:
    """Get active maintenance schedules linked to a vehicle.
    Schedules live in the public schema (platform service).
    """
    from data_layer.db import fetch_all as _pub_fetch_all
    rows = _pub_fetch_all(
        """SELECT * FROM app_schedules.schedules
           WHERE linked_entity_type = 'vehicle'
             AND linked_entity_id = %s
             AND active = TRUE
           ORDER BY next_due ASC NULLS LAST""",
        (vehicle_id,),
    )
    from apps.schedules.data import _row_to_dict, describe_recurrence
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
    """Complete a maintenance schedule: advance the schedule + create a service record."""
    import uuid
    from apps.schedules.data import complete_schedule

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
        execute_in_schema(
            SCHEMA,
            "UPDATE vehicles SET odometer = %s, updated_at = %s WHERE id = %s AND (odometer IS NULL OR odometer < %s)",
            (odometer, _now(), vehicle_id, odometer),
        )

    return {
        "schedule": sch,
        "service_record": get_service_record(svc_id),
    }


# ---------------------------------------------------------------------------
# Oil Change Tracking
# ---------------------------------------------------------------------------

def _oil_tracking_row(row: dict) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "vehicle_id": row.get("vehicle_id") or "",
        "service_record_id": row.get("service_record_id") or "",
        "date_performed": row["date_performed"].isoformat() if row.get("date_performed") else "",
        "odometer_at_service": row.get("odometer_at_service"),
        "mileage_interval": row.get("mileage_interval") or 5000,
        "next_due_mileage": row.get("next_due_mileage"),
        "cooldown_months": row.get("cooldown_months") or 3,
        "cooldown_expires": row["cooldown_expires"].isoformat() if row.get("cooldown_expires") else "",
        "last_mileage_check": row["last_mileage_check"].isoformat() if row.get("last_mileage_check") else "",
        "last_reported_mileage": row.get("last_reported_mileage"),
        "is_due": bool(row.get("is_due")),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def get_oil_tracking(vehicle_id: str) -> dict | None:
    row = fetch_one_in_schema(
        SCHEMA,
        "SELECT * FROM oil_change_tracking WHERE vehicle_id = %s",
        (vehicle_id,),
    )
    return _oil_tracking_row(row) if row else None


def upsert_oil_tracking(vehicle_id: str, data: dict):
    """Create or replace the oil change tracking row for a vehicle."""
    from dateutil.relativedelta import relativedelta
    from datetime import date as _date

    tracking_id = data.get("id") or f"oct-{__import__('uuid').uuid4().hex[:8]}"
    date_performed = data.get("date_performed") or _date.today().isoformat()
    odometer = data["odometer_at_service"]
    interval = data.get("mileage_interval", 5000)
    cooldown = data.get("cooldown_months", 3)
    next_due = odometer + interval

    dp = _date.fromisoformat(date_performed) if isinstance(date_performed, str) else date_performed
    cooldown_expires = (dp + relativedelta(months=cooldown)).isoformat()

    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO oil_change_tracking
                    (id, vehicle_id, service_record_id, date_performed, odometer_at_service,
                     mileage_interval, next_due_mileage, cooldown_months, cooldown_expires,
                     last_mileage_check, last_reported_mileage, is_due, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, FALSE, %s, %s)
                ON CONFLICT (vehicle_id) DO UPDATE SET
                    id = EXCLUDED.id,
                    service_record_id = EXCLUDED.service_record_id,
                    date_performed = EXCLUDED.date_performed,
                    odometer_at_service = EXCLUDED.odometer_at_service,
                    mileage_interval = EXCLUDED.mileage_interval,
                    next_due_mileage = EXCLUDED.next_due_mileage,
                    cooldown_months = EXCLUDED.cooldown_months,
                    cooldown_expires = EXCLUDED.cooldown_expires,
                    last_mileage_check = NULL,
                    last_reported_mileage = NULL,
                    is_due = FALSE,
                    updated_at = EXCLUDED.updated_at
            """, (
                tracking_id,
                vehicle_id,
                data.get("service_record_id"),
                date_performed,
                odometer,
                interval,
                next_due,
                cooldown,
                cooldown_expires,
                _now(),
                _now(),
            ))
        conn.commit()
    return get_oil_tracking(vehicle_id)


def update_oil_tracking_settings(vehicle_id: str, updates: dict) -> dict | None:
    """Update mileage_interval and/or cooldown_months, recomputing derived fields."""
    from dateutil.relativedelta import relativedelta
    from datetime import date as _date

    tracking = get_oil_tracking(vehicle_id)
    if not tracking:
        return None

    interval = updates.get("mileage_interval", tracking["mileage_interval"])
    cooldown = updates.get("cooldown_months", tracking["cooldown_months"])
    odometer = tracking["odometer_at_service"]
    next_due = odometer + interval

    dp = _date.fromisoformat(tracking["date_performed"])
    cooldown_expires = (dp + relativedelta(months=cooldown)).isoformat()

    execute_in_schema(
        SCHEMA,
        """UPDATE oil_change_tracking
           SET mileage_interval = %s, next_due_mileage = %s,
               cooldown_months = %s, cooldown_expires = %s, updated_at = %s
           WHERE vehicle_id = %s""",
        (interval, next_due, cooldown, cooldown_expires, _now(), vehicle_id),
    )
    return get_oil_tracking(vehicle_id)


def record_mileage_check(vehicle_id: str, odometer: int) -> dict | None:
    """Record a mileage check against oil change tracking. Returns updated tracking."""
    from datetime import date as _date

    tracking = get_oil_tracking(vehicle_id)
    if not tracking:
        return None

    is_due = odometer >= tracking["next_due_mileage"]
    today = _date.today().isoformat()

    execute_in_schema(
        SCHEMA,
        """UPDATE oil_change_tracking
           SET last_mileage_check = %s, last_reported_mileage = %s,
               is_due = %s, updated_at = %s
           WHERE vehicle_id = %s""",
        (today, odometer, is_due, _now(), vehicle_id),
    )

    # Also update vehicle odometer if this is higher
    execute_in_schema(
        SCHEMA,
        "UPDATE vehicles SET odometer = %s, updated_at = %s WHERE id = %s AND (odometer IS NULL OR odometer < %s)",
        (odometer, _now(), vehicle_id, odometer),
    )

    return get_oil_tracking(vehicle_id)


def delete_oil_tracking(vehicle_id: str) -> bool:
    return execute_in_schema(
        SCHEMA, "DELETE FROM oil_change_tracking WHERE vehicle_id = %s", (vehicle_id,)
    ) > 0


# ---------------------------------------------------------------------------
# List-all helpers (for backfill / memory ingestion)
# ---------------------------------------------------------------------------

def get_all_service_records() -> list[dict]:
    return [_service_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM service_records ORDER BY date_performed DESC, created_at DESC"
    )]


def get_all_issues() -> list[dict]:
    return [_issue_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM vehicle_issues ORDER BY created_at DESC"
    )]


def get_all_valuations() -> list[dict]:
    return [_valuation_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM vehicle_valuations ORDER BY date_recorded DESC"
    )]


def get_all_conditions() -> list[dict]:
    return [_condition_row(r) for r in fetch_all_in_schema(
        SCHEMA, "SELECT * FROM vehicle_conditions ORDER BY date_recorded DESC"
    )]


# ---------------------------------------------------------------------------
# Summary helpers (for list view cards)
# ---------------------------------------------------------------------------

def get_vehicle_summary(vehicle_id: str) -> dict:
    """Get summary info for a vehicle card: next service, open issues, latest condition."""
    next_svc = fetch_one_in_schema(
        SCHEMA,
        """SELECT service_type, next_due_date, next_due_mileage
           FROM service_records
           WHERE vehicle_id = %s AND (next_due_date IS NOT NULL OR next_due_mileage IS NOT NULL)
           ORDER BY next_due_date ASC NULLS LAST
           LIMIT 1""",
        (vehicle_id,),
    )
    issue_row = fetch_one_in_schema(
        SCHEMA,
        "SELECT COUNT(*) as cnt FROM vehicle_issues WHERE vehicle_id = %s AND status != 'fixed'",
        (vehicle_id,),
    )
    latest_cond = get_latest_condition(vehicle_id)
    return {
        "next_service": _service_row(next_svc) if next_svc else None,
        "open_issue_count": issue_row["cnt"] if issue_row else 0,
        "latest_condition": latest_cond,
    }


# ---------------------------------------------------------------------------
# Backfill registry — consumed by backfill_app_memories.py via discover_apps()
# ---------------------------------------------------------------------------
BACKFILL_ENTITIES = [
    {"entity_type": "vehicle", "list_fn": get_all_vehicles, "context_hint": _VEHICLE_HINT},
    {"entity_type": "service record", "list_fn": get_all_service_records, "context_hint": _SERVICE_HINT},
    {"entity_type": "vehicle issue", "list_fn": get_all_issues, "context_hint": _ISSUE_HINT},
    {"entity_type": "vehicle valuation", "list_fn": get_all_valuations, "context_hint": _VALUATION_HINT},
    {"entity_type": "vehicle condition", "list_fn": get_all_conditions, "context_hint": _CONDITION_HINT},
]
