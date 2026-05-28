"""Data layer for scrum_items — daily PM digest items persisted per person."""

import uuid
from datetime import date, timedelta

from data_layer.db import fetch_all, fetch_one, execute, get_conn
from data_layer.links import ensure_edge


def _new_id() -> str:
    return f"si-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_scrum_item(
    report_date: date,
    person: str,
    item_type: str,
    title: str,
    detail: str = "",
    source_entity_id: str | None = None,
    source_entity_type: str | None = None,
    project_name: str | None = None,
    severity: str | None = None,
) -> dict:
    """Insert a single scrum item and return it."""
    item_id = _new_id()
    execute(
        """INSERT INTO scrum_items
               (id, report_date, person, item_type, title, detail,
                source_entity_id, source_entity_type, project_name, severity)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (item_id, report_date, person.lower().strip(), item_type,
         title, detail or None,
         source_entity_id or None, source_entity_type or None,
         project_name or None, severity or None),
    )
    if source_entity_id:
        ensure_edge(item_id, source_entity_id, "linked_to", "linked_to")
    return {
        "id": item_id, "report_date": report_date.isoformat(),
        "person": person, "item_type": item_type,
        "title": title, "detail": detail,
        "source_entity_id": source_entity_id,
        "source_entity_type": source_entity_type,
        "project_name": project_name, "severity": severity,
    }


def save_scrum_items_bulk(items: list[dict]) -> int:
    """Insert many scrum items in one transaction. Returns count inserted.

    Each dict must have: report_date, person, item_type, title.
    Optional: detail, source_entity_id, source_entity_type, project_name, severity.
    """
    if not items:
        return 0
    generated_ids = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for it in items:
                iid = _new_id()
                generated_ids.append((iid, it.get("source_entity_id")))
                cur.execute(
                    """INSERT INTO scrum_items
                           (id, report_date, person, item_type, title, detail,
                            source_entity_id, source_entity_type, project_name, severity)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (iid,
                     it["report_date"],
                     it["person"].lower().strip(),
                     it["item_type"],
                     it["title"],
                     it.get("detail") or None,
                     it.get("source_entity_id") or None,
                     it.get("source_entity_type") or None,
                     it.get("project_name") or None,
                     it.get("severity") or None),
                )
        conn.commit()
    for iid, src_id in generated_ids:
        if src_id:
            ensure_edge(iid, src_id, "linked_to", "linked_to")
    return len(items)


def items_exist_for_date(report_date: date, person: str | None = None) -> bool:
    """Check if scrum items already exist for a given date (and optionally person)."""
    if person:
        row = fetch_one(
            "SELECT 1 FROM scrum_items WHERE report_date = %s AND person = %s LIMIT 1",
            (report_date, person.lower().strip()),
        )
    else:
        row = fetch_one(
            "SELECT 1 FROM scrum_items WHERE report_date = %s LIMIT 1",
            (report_date,),
        )
    return row is not None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def _row_to_dict(row: dict) -> dict:
    d = dict(row)
    if d.get("report_date"):
        d["report_date"] = d["report_date"].isoformat() if hasattr(d["report_date"], "isoformat") else str(d["report_date"])
    if d.get("created_at"):
        d["created_at"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
    if d.get("responded_at"):
        d["responded_at"] = d["responded_at"].isoformat() if hasattr(d["responded_at"], "isoformat") else str(d["responded_at"])
    return d


def get_scrum_items(
    person: str | None = None,
    report_date: date | None = None,
    days: int = 7,
    item_type: str | None = None,
) -> list[dict]:
    """Query scrum items with flexible filters.

    - If report_date is set, return items for that single date.
    - Otherwise return items for the last `days` days.
    - If person is set, filter to that user.
    - If item_type is set, filter by type.
    """
    clauses: list[str] = []
    params: list = []

    if report_date:
        clauses.append("report_date = %s")
        params.append(report_date)
    else:
        cutoff = date.today() - timedelta(days=days)
        clauses.append("report_date >= %s")
        params.append(cutoff)

    if person:
        clauses.append("person = %s")
        params.append(person.lower().strip())

    if item_type:
        clauses.append("item_type = %s")
        params.append(item_type)

    where = " AND ".join(clauses) if clauses else "TRUE"
    rows = fetch_all(
        f"SELECT * FROM scrum_items WHERE {where} ORDER BY report_date DESC, created_at ASC",
        tuple(params),
    )
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Phase 2 stub — respond
# ---------------------------------------------------------------------------

def respond_to_item(item_id: str, response: str) -> dict | None:
    """Save a user response to a scrum item. No-op if already responded (atomic)."""
    execute(
        "UPDATE scrum_items SET response = %s, responded_at = now() WHERE id = %s AND response IS NULL",
        (response, item_id),
    )
    row = fetch_one("SELECT * FROM scrum_items WHERE id = %s", (item_id,))
    return _row_to_dict(row) if row else None
