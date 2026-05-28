"""Link Registry
===============
Bidirectional hard links between any entity types.
Supports creating, querying, and removing links between entities
identified by their prefixed IDs (g-*, p-*, t-*, sch-*, veh-*, etc.).

Backed by Postgres via data_layer.links.
Entity type resolution via data_layer.entity_types (DB-backed registry).
"""

import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import TIMEZONE
from auto_memory import log_entity_change
import data_layer.links as _dl_links
import data_layer.entity_types as _dl_entity_types

CENTRAL_TZ = ZoneInfo(TIMEZONE)



def _now_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


def _entity_type(entity_id: str) -> str:
    """Return human-readable type name for an entity ID."""
    return _dl_entity_types.entity_type_name(entity_id)


def _is_valid_entity_id(val: str) -> bool:
    return _dl_entity_types.is_valid_entity_id(val)




# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_link(
    source_id: str,
    target_id: str,
    relation: str = "",
    created_by: str = "",
) -> dict | str:
    """Create a bidirectional link between two entities.

    Args:
        source_id: First entity ID (e.g. "r-abc123").
        target_id: Second entity ID (e.g. "t-def456").
        relation: Optional label describing the relationship (e.g. "reminds_about",
                  "attached_to", "blocks", "depends_on").
        created_by: Who created this link.

    Returns:
        The link record, or an error string.
    """
    if not _is_valid_entity_id(source_id):
        return f"Error: '{source_id}' is not a valid entity ID."
    if not _is_valid_entity_id(target_id):
        return f"Error: '{target_id}' is not a valid entity ID."
    if source_id == target_id:
        return "Error: Cannot link an entity to itself."

    record = _dl_links.create_link(
        source_id=source_id,
        target_id=target_id,
        relation=relation.strip() if relation else "",
        created_by=created_by.strip().lower() if created_by else "",
    )

    rel_label = f" ({relation.strip()})" if relation and relation.strip() else ""
    log_entity_change("linked", record["id"], "link",
                      f"{source_id} ↔ {target_id}{rel_label}",
                      by=created_by,
                      related_entities=[source_id, target_id])
    return record


def get_links(entity_id: str, relation: Optional[str] = None) -> list[dict]:
    """Get all links involving an entity (either direction).

    Args:
        entity_id: Entity ID to look up.
        relation: Optional filter by relation label.

    Returns:
        List of link records where entity_id is source or target.
    """
    results = _dl_links.get_links(entity_id)
    if relation:
        rel_filter = relation.strip().lower()
        results = [l for l in results if l.get("relation", "").lower() == rel_filter]
    return results


def get_linked_ids(entity_id: str, relation: Optional[str] = None) -> list[str]:
    """Get just the IDs of entities linked to entity_id.

    Returns the 'other side' of each link (not entity_id itself).
    Deduplicates — each linked ID appears at most once.
    """
    seen = set()
    results = []
    for link in get_links(entity_id, relation):
        other = link["target_id"] if link["source_id"] == entity_id else link["source_id"]
        if other not in seen:
            seen.add(other)
            results.append(other)
    return results


def delete_link(link_id: str) -> bool:
    """Delete a link by its ID.

    Returns:
        True if deleted, False if not found.
    """
    return _dl_links.delete_link(link_id)


def delete_links_for_entity(entity_id: str) -> int:
    """Delete all links involving an entity. Use when an entity is deleted.

    Returns:
        Number of links removed.
    """
    return _dl_links.delete_links_for_entity(entity_id)


def get_blast_radius(
    entity_id: str,
    max_depth: int = 3,
    exclude_relations: Optional[list[str]] = None,
    include_relations: Optional[list[str]] = None,
) -> list[dict]:
    """Walk the entity graph outward from entity_id.

    Returns all entities reachable within max_depth hops, with cycle
    detection. Uses a recursive CTE over the bidirectional links table.

    Args:
        entity_id: Starting entity ID.
        max_depth: Maximum hops (default 3).
        exclude_relations: Relations to skip (e.g., ['backs', 'backed_by']).
        include_relations: If set, ONLY traverse these relations.

    Returns:
        List of dicts sorted by depth: [{id, type, relation, depth}].
        The starting entity is NOT included.
    """
    return _dl_links.get_blast_radius(
        entity_id,
        max_depth=max_depth,
        exclude_relations=exclude_relations,
        include_relations=include_relations,
    )


def format_links(entity_id: str) -> str:
    """Format links for an entity into a readable string."""
    links = get_links(entity_id)
    if not links:
        return f"No links for {entity_id}."

    lines = [f"Links for {entity_id} ({len(links)}):"]
    for link in links:
        other_id = link["target_id"] if link["source_id"] == entity_id else link["source_id"]
        other_type = _entity_type(other_id)
        rel = f" ({link['relation']})" if link.get("relation") else ""
        lines.append(f"  {other_id} [{other_type}]{rel}")
    return "\n".join(lines)
