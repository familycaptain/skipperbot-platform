"""Entity Links — Postgres CRUD
================================
Drop-in replacement for link_registry.py's flat-file persistence.
"""

import logging
import uuid
from datetime import datetime, timezone

from data_layer.db import get_conn, fetch_one, fetch_all, execute

logger = logging.getLogger(__name__)


def create_link(
    source_id: str,
    target_id: str,
    relation: str = "",
    created_by: str = "",
) -> dict:
    """Create a bidirectional link between two entities."""
    # Determine types from ID prefixes
    source_type = _type_from_id(source_id)
    target_type = _type_from_id(target_id)

    link = {
        "id": f"lnk-{uuid.uuid4().hex[:8]}",
        "source_id": source_id,
        "target_id": target_id,
        "source_type": source_type,
        "target_type": target_type,
        "relation": relation,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO links (id, source_id, target_id, source_type,
                                   target_type, relation, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, target_id, relation) DO NOTHING
            """, (
                link["id"], link["source_id"], link["target_id"],
                link["source_type"], link["target_type"],
                link["relation"], link["created_by"], link["created_at"],
            ))
        conn.commit()
    return link


def get_links(entity_id: str) -> list[dict]:
    """Get all links involving an entity (as source or target)."""
    rows = fetch_all(
        "SELECT * FROM links WHERE source_id = %s OR target_id = %s ORDER BY created_at",
        (entity_id, entity_id),
    )
    return [_row(r) for r in rows]


def delete_links_for_entity(entity_id: str) -> int:
    """Delete all links involving an entity. Returns count deleted."""
    return execute(
        "DELETE FROM links WHERE source_id = %s OR target_id = %s",
        (entity_id, entity_id),
    )


def delete_link(link_id: str) -> bool:
    return execute("DELETE FROM links WHERE id = %s", (link_id,)) > 0


def ensure_edge(
    source_id: str,
    target_id: str,
    forward_relation: str,
    reverse_relation: str,
) -> None:
    """Register a bidirectional structural edge between two entities.

    Inserts both forward and reverse rows with ON CONFLICT DO NOTHING,
    so it's safe to call on every save (idempotent). Skips silently if
    either ID is empty/None.
    """
    if not source_id or not target_id:
        return
    src_type = _type_from_id(source_id)
    tgt_type = _type_from_id(target_id)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO links (id, source_id, target_id, source_type,
                                       target_type, relation, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'system:structural', %s)
                    ON CONFLICT (source_id, target_id, relation) DO NOTHING
                """, (f"lnk-{uuid.uuid4().hex[:8]}",
                      source_id, target_id, src_type, tgt_type,
                      forward_relation, now))
                cur.execute("""
                    INSERT INTO links (id, source_id, target_id, source_type,
                                       target_type, relation, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'system:structural', %s)
                    ON CONFLICT (source_id, target_id, relation) DO NOTHING
                """, (f"lnk-{uuid.uuid4().hex[:8]}",
                      target_id, source_id, tgt_type, src_type,
                      reverse_relation, now))
            conn.commit()
    except Exception:
        logger.warning("ensure_edge failed: %s → %s (%s/%s)",
                       source_id, target_id, forward_relation, reverse_relation,
                       exc_info=True)


def get_blast_radius(
    entity_id: str,
    max_depth: int = 3,
    exclude_relations: list[str] | None = None,
    include_relations: list[str] | None = None,
) -> list[dict]:
    """Walk the entity graph outward from entity_id using a recursive CTE.

    Since edges are stored bidirectionally, walking source_id → target_id
    is sufficient to reach all connected entities.

    Args:
        entity_id: Starting entity ID.
        max_depth: Maximum hops to traverse (default 3).
        exclude_relations: Relations to skip (e.g., ['backs', 'backed_by']).
        include_relations: If set, ONLY follow these relations (overrides exclude).

    Returns:
        List of dicts: [{id, type, relation, depth}] — ordered by depth then id.
        The starting entity is NOT included in the results.
    """
    # Build the relation filter clause for the recursive step
    rel_filter = ""
    rel_params: list = []
    if include_relations:
        rel_filter = "AND l.relation = ANY(%s)"
        rel_params = [include_relations]
    elif exclude_relations:
        rel_filter = "AND l.relation != ALL(%s)"
        rel_params = [exclude_relations]

    sql = f"""
        WITH RECURSIVE blast AS (
            -- Seed: direct neighbors of the starting entity
            SELECT
                l.target_id AS id,
                l.target_type AS type,
                l.relation,
                1 AS depth,
                ARRAY[%s, l.target_id] AS visited
            FROM links l
            WHERE l.source_id = %s
              {rel_filter}

            UNION ALL

            -- Recurse: neighbors of already-found entities
            SELECT
                l.target_id,
                l.target_type,
                l.relation,
                b.depth + 1,
                b.visited || l.target_id
            FROM blast b
            JOIN links l ON l.source_id = b.id
            WHERE b.depth < %s
              AND NOT (l.target_id = ANY(b.visited))
              {rel_filter}
        )
        SELECT DISTINCT ON (id) id, type, relation, depth
        FROM blast
        ORDER BY id, depth
    """

    # Assemble params: seed_visited, source_id, [rel_params], max_depth, [rel_params]
    params: list = [entity_id, entity_id]
    params.extend(rel_params)
    params.append(max_depth)
    params.extend(rel_params)

    rows = fetch_all(sql, tuple(params))
    return [
        {"id": r["id"], "type": r["type"] or "", "relation": r["relation"] or "", "depth": r["depth"]}
        for r in rows
    ]


def _type_from_id(entity_id: str) -> str:
    from data_layer.entity_types import entity_type_name
    name = entity_type_name(entity_id)
    return name if name != "unknown" else ""


def _row(row: dict) -> dict:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "source_type": row.get("source_type") or "",
        "target_type": row.get("target_type") or "",
        "relation": row.get("relation") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
