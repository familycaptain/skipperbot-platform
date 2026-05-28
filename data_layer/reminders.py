"""Reminders — Postgres CRUD
============================
Drop-in replacement for reminder_store.py's flat-file persistence.
"""

import logging
from typing import Optional

from data_layer.db import get_conn, fetch_one, fetch_all, execute
from data_layer.links import ensure_edge

logger = logging.getLogger(__name__)


def save_reminder(r: dict):
    """Insert or update a reminder."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO reminders (id, user_id, message, remind_at, recurrence,
                                       active, nag, last_nagged, time_slot, created_at, sort_order,
                                       schedule_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    message = EXCLUDED.message,
                    remind_at = EXCLUDED.remind_at,
                    recurrence = EXCLUDED.recurrence,
                    active = EXCLUDED.active,
                    nag = EXCLUDED.nag,
                    last_nagged = EXCLUDED.last_nagged,
                    time_slot = EXCLUDED.time_slot,
                    sort_order = EXCLUDED.sort_order,
                    schedule_id = EXCLUDED.schedule_id
            """, (
                r["id"], r.get("user_id", ""), r["message"],
                r["remind_at"], r.get("recurrence"),
                r.get("active", True), r.get("nag", False),
                r.get("last_nagged", ""), r.get("time_slot", ""),
                r.get("created_at", ""), r.get("sort_order", 0),
                r.get("schedule_id") or None,
            ))
        conn.commit()
    if r.get("schedule_id"):
        ensure_edge(r["id"], r["schedule_id"], "backed_by", "backs")


def get_reminder(reminder_id: str) -> dict | None:
    row = fetch_one("SELECT * FROM reminders WHERE id = %s", (reminder_id,))
    return _row(row) if row else None


def get_all_reminders() -> list[dict]:
    return [_row(r) for r in fetch_all("SELECT * FROM reminders ORDER BY sort_order, created_at")]


def get_active_reminders() -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM reminders WHERE active = TRUE ORDER BY sort_order, created_at")]


def get_user_reminders(user_id: str) -> list[dict]:
    return [_row(r) for r in fetch_all(
        "SELECT * FROM reminders WHERE user_id = %s ORDER BY sort_order, created_at", (user_id,))]


def delete_reminder(reminder_id: str) -> bool:
    return execute("DELETE FROM reminders WHERE id = %s", (reminder_id,)) > 0


def save_all_reminders(reminders: list[dict]):
    """Bulk save — used by reminder_store's _save_reminders pattern."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in reminders:
                cur.execute("""
                    INSERT INTO reminders (id, user_id, message, remind_at, recurrence,
                                           active, nag, last_nagged, time_slot, created_at, sort_order,
                                           schedule_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        message = EXCLUDED.message,
                        remind_at = EXCLUDED.remind_at,
                        recurrence = EXCLUDED.recurrence,
                        active = EXCLUDED.active,
                        nag = EXCLUDED.nag,
                        last_nagged = EXCLUDED.last_nagged,
                        time_slot = EXCLUDED.time_slot,
                        sort_order = EXCLUDED.sort_order,
                        schedule_id = EXCLUDED.schedule_id
                """, (
                    r["id"], r.get("user_id", ""), r["message"],
                    r["remind_at"], r.get("recurrence"),
                    r.get("active", True), r.get("nag", False),
                    r.get("last_nagged", ""), r.get("time_slot", ""),
                    r.get("created_at", ""), r.get("sort_order", 0),
                    r.get("schedule_id") or None,
                ))
        conn.commit()
    for r in reminders:
        if r.get("schedule_id"):
            ensure_edge(r["id"], r["schedule_id"], "backed_by", "backs")


def next_sort_order() -> int:
    """Return the next available sort_order value (max + 1)."""
    row = fetch_one("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_val FROM reminders")
    return row["next_val"] if row else 1


def reorder_reminder(reminder_id: str, direction: str,
                     user_id: str = "", active_only: bool = True) -> bool:
    """Move a reminder up or down within its type (nag vs regular).

    Swaps sort_order with the adjacent *visible* reminder — honours the same
    user_id and active filters the frontend is currently showing so the swap
    always affects a neighbour the user can actually see.
    """
    current = fetch_one("SELECT id, sort_order, nag FROM reminders WHERE id = %s", (reminder_id,))
    if not current:
        return False

    cur_order = current["sort_order"]
    is_nag = current["nag"]

    # Build a WHERE clause that mirrors the frontend's visible list
    conditions = ["nag = %s"]
    params: list = [is_nag]

    if active_only:
        conditions.append("active = TRUE")
    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)

    if direction == "up":
        conditions.append("sort_order < %s")
        params.append(cur_order)
        where = " AND ".join(conditions)
        neighbor = fetch_one(
            f"SELECT id, sort_order FROM reminders WHERE {where} ORDER BY sort_order DESC LIMIT 1",
            tuple(params),
        )
    else:
        conditions.append("sort_order > %s")
        params.append(cur_order)
        where = " AND ".join(conditions)
        neighbor = fetch_one(
            f"SELECT id, sort_order FROM reminders WHERE {where} ORDER BY sort_order ASC LIMIT 1",
            tuple(params),
        )

    if not neighbor:
        return False

    # Swap sort_order values
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reminders SET sort_order = %s WHERE id = %s", (neighbor["sort_order"], reminder_id))
            cur.execute("UPDATE reminders SET sort_order = %s WHERE id = %s", (cur_order, neighbor["id"]))
        conn.commit()
    return True


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row.get("user_id") or "",
        "message": row["message"],
        "remind_at": row["remind_at"].isoformat() if row.get("remind_at") else "",
        "recurrence": row.get("recurrence"),
        "active": row.get("active", True),
        "nag": row.get("nag", False),
        "last_nagged": row.get("last_nagged") or "",
        "time_slot": row.get("time_slot") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "sort_order": row.get("sort_order", 0),
        "schedule_id": row.get("schedule_id") or None,
    }
