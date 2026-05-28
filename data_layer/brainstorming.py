"""Brainstorming — Postgres CRUD for ideas + idea_parts
=======================================================
"""

import json
import logging
import os
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute, execute_returning
from data_layer.links import ensure_edge
from app_platform.memory import digest_record

logger = logging.getLogger(__name__)

_IDEA_HINT = (
    "Focus on: idea title, summary, status (idea/active/on_hold/done/archived), "
    "priority, tags, creator, and key content from the main document."
)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{os.urandom(4).hex()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Ideas CRUD
# ---------------------------------------------------------------------------

def _idea_digest_record(idea: dict) -> dict:
    """Build a memory-safe record for an idea: include summary and trimmed main content."""
    record = {k: v for k, v in idea.items() if k != "parts"}
    main = next((p for p in (idea.get("parts") or []) if p.get("is_main")), None)
    if main:
        record["main_content_preview"] = (main.get("content") or "")[:500]
    return record


def create_idea(title: str, summary: str = "", tags: list[str] | None = None,
                priority: str = "medium", created_by: str = "") -> dict:
    """Create a new idea with an auto-created main document part."""
    idea_id = _new_id("bs")
    part_id = _new_id("bp")
    now = _now_iso()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ideas (id, title, summary, status, priority, tags, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, 'idea', %s, %s, %s, %s, %s)
            """, (idea_id, title, summary, priority, tags or [], created_by, now, now))

            cur.execute("""
                INSERT INTO idea_parts (id, idea_id, type, title, is_main, sort_order, content, meta, version, created_at, updated_at)
                VALUES (%s, %s, 'document', 'Main Doc', TRUE, 0, '', '{}', 1, %s, %s)
            """, (part_id, idea_id, now, now))
        conn.commit()
    ensure_edge(part_id, idea_id, "child_of", "parent_of")

    saved = get_idea(idea_id)
    if saved:
        digest_record(app_id="brainstorming", entity_type="idea", action="created",
                      entity_id=idea_id, record=_idea_digest_record(saved),
                      by=created_by, context_hint=_IDEA_HINT)
    return saved


def get_idea(idea_id: str) -> dict | None:
    """Get an idea with all its parts."""
    row = fetch_one("SELECT * FROM ideas WHERE id = %s", (idea_id,))
    if not row:
        return None
    idea = _idea_row(row)
    idea["parts"] = get_idea_parts(idea_id)
    return idea


def list_ideas(status: str = "", tag: str = "", search: str = "",
               created_by: str = "") -> list[dict]:
    """List ideas with optional filters."""
    clauses = []
    params = []

    if status:
        clauses.append("status = %s")
        params.append(status)
    if tag:
        clauses.append("%s = ANY(tags)")
        params.append(tag)
    if search:
        clauses.append("(title ILIKE %s OR summary ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if created_by:
        clauses.append("created_by = %s")
        params.append(created_by)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = fetch_all(
        f"SELECT * FROM ideas{where} ORDER BY updated_at DESC",
        tuple(params),
    )
    ideas = [_idea_row(r) for r in rows]
    # Attach part counts
    for idea in ideas:
        idea["part_count"] = _count_parts(idea["id"])
    return ideas


def update_idea(idea_id: str, **fields) -> dict | None:
    """Update idea metadata. Allowed fields: title, summary, status, priority, tags, project_id."""
    allowed = {"title", "summary", "status", "priority", "tags", "project_id"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_idea(idea_id)

    set_parts = []
    params = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        params.append(v)
    set_parts.append("updated_at = %s")
    params.append(_now_iso())
    params.append(idea_id)

    execute(
        f"UPDATE ideas SET {', '.join(set_parts)} WHERE id = %s",
        tuple(params),
    )
    saved = get_idea(idea_id)
    if saved:
        digest_record(app_id="brainstorming", entity_type="idea", action="updated",
                      entity_id=idea_id, record=_idea_digest_record(saved),
                      by="", context_hint=_IDEA_HINT)
    return saved


def delete_idea(idea_id: str) -> bool:
    """Delete an idea and all its parts (CASCADE)."""
    idea = get_idea(idea_id)
    ok = execute("DELETE FROM ideas WHERE id = %s", (idea_id,)) > 0
    if ok and idea:
        digest_record(app_id="brainstorming", entity_type="idea", action="deleted",
                      entity_id=idea_id, record=_idea_digest_record(idea), by="")
    return ok


# ---------------------------------------------------------------------------
# Idea Parts CRUD
# ---------------------------------------------------------------------------

def get_idea_parts(idea_id: str) -> list[dict]:
    """Get all parts for an idea, ordered by sort_order."""
    rows = fetch_all(
        "SELECT * FROM idea_parts WHERE idea_id = %s ORDER BY sort_order, created_at",
        (idea_id,),
    )
    return [_part_row(r) for r in rows]


def get_part(part_id: str) -> dict | None:
    """Get a single part by ID."""
    row = fetch_one("SELECT * FROM idea_parts WHERE id = %s", (part_id,))
    return _part_row(row) if row else None


def add_part(idea_id: str, part_type: str = "document", title: str = "",
             content: str = "", meta: dict | None = None) -> dict | None:
    """Add a new part to an idea."""
    part_id = _new_id("bp")
    now = _now_iso()

    # Get next sort_order
    row = fetch_one(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM idea_parts WHERE idea_id = %s",
        (idea_id,),
    )
    sort_order = row["next_order"] if row else 0

    execute(
        """INSERT INTO idea_parts (id, idea_id, type, title, is_main, sort_order, content, meta, version, created_at, updated_at)
           VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, 1, %s, %s)""",
        (part_id, idea_id, part_type, title, sort_order,
         content, json.dumps(meta or {}), now, now),
    )
    # Touch parent idea
    execute("UPDATE ideas SET updated_at = %s WHERE id = %s", (now, idea_id))
    ensure_edge(part_id, idea_id, "child_of", "parent_of")
    return get_part(part_id)


def update_part(part_id: str, **fields) -> dict | None:
    """Update a part. Allowed fields: title, content, meta, sort_order."""
    allowed = {"title", "content", "meta", "sort_order"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_part(part_id)

    set_parts = []
    params = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        if k == "meta":
            params.append(json.dumps(v))
        else:
            params.append(v)

    # Bump version if content changed
    if "content" in updates:
        set_parts.append("version = version + 1")

    set_parts.append("updated_at = %s")
    now = _now_iso()
    params.append(now)
    params.append(part_id)

    execute(
        f"UPDATE idea_parts SET {', '.join(set_parts)} WHERE id = %s",
        tuple(params),
    )

    # Touch parent idea
    part = get_part(part_id)
    if part:
        execute("UPDATE ideas SET updated_at = %s WHERE id = %s", (now, part["idea_id"]))
    return part


def delete_part(part_id: str) -> str:
    """Delete a part. Cannot delete the main document."""
    part = get_part(part_id)
    if not part:
        return "Error: Part not found."
    if part.get("is_main"):
        return "Error: Cannot delete the main document."

    execute("DELETE FROM idea_parts WHERE id = %s", (part_id,))
    execute("UPDATE ideas SET updated_at = %s WHERE id = %s", (_now_iso(), part["idea_id"]))
    return "Part deleted."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_parts(idea_id: str) -> int:
    row = fetch_one("SELECT COUNT(*) AS cnt FROM idea_parts WHERE idea_id = %s", (idea_id,))
    return row["cnt"] if row else 0


def _idea_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row.get("summary") or "",
        "status": row["status"],
        "priority": row.get("priority") or "medium",
        "tags": row.get("tags") or [],
        "project_id": row.get("project_id") or None,
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }


def _part_row(row: dict) -> dict:
    meta = row.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    return {
        "id": row["id"],
        "idea_id": row["idea_id"],
        "type": row["type"],
        "title": row.get("title") or "",
        "is_main": row.get("is_main", False),
        "sort_order": row.get("sort_order", 0),
        "content": row.get("content") or "",
        "meta": meta,
        "version": row.get("version", 1),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else "",
    }
