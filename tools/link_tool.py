"""
Link Registry Tools - Create and query hard links between entities.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from link_registry import (
    create_link as _create_link,
    get_links as _get_links,
    delete_link as _delete_link,
    format_links as _format_links,
)


def link_entities(
    source_id: str,
    target_id: str,
    relation: str = "",
    created_by: str = "",
) -> str:
    """Create a link between two entities.

    Use this to connect related items, e.g. a reminder to a task,
    an artifact to a project, or a list item to a goal.

    Args:
        source_id: First entity ID (e.g. "r-abc123", "t-def456").
        target_id: Second entity ID.
        relation: Optional label (e.g. "reminds_about", "attached_to",
                  "blocks", "depends_on", "related_to").
        created_by: Who is creating this link.

    Returns:
        Confirmation or error.
    """
    try:
        if not source_id or not source_id.strip():
            return "Error: source_id is required."
        if not target_id or not target_id.strip():
            return "Error: target_id is required."

        result = _create_link(
            source_id=source_id.strip(),
            target_id=target_id.strip(),
            relation=relation.strip() if relation else "",
            created_by=created_by.strip().lower() if created_by else "",
        )

        if isinstance(result, str):
            return result  # Error or duplicate message

        return (
            f"Linked {result['source_id']} [{result['source_type']}] "
            f"↔ {result['target_id']} [{result['target_type']}]"
            f"{' (' + result['relation'] + ')' if result.get('relation') else ''}"
            f" (id: {result['id']})"
        )
    except Exception as e:
        return f"Error in link_entities: {str(e)}"


def get_entity_links(entity_id: str, relation: str = "") -> str:
    """Show all links for an entity.

    Args:
        entity_id: Entity ID to look up (e.g. "p-1234", "t-5678").
        relation: Optional filter by relation label.

    Returns:
        Formatted list of linked entities.
    """
    try:
        if not entity_id or not entity_id.strip():
            return "Error: entity_id is required."

        if relation and relation.strip():
            links = _get_links(entity_id.strip(), relation.strip())
        else:
            links = _get_links(entity_id.strip())

        if not links:
            return f"No links found for {entity_id.strip()}."

        return _format_links(entity_id.strip())
    except Exception as e:
        return f"Error in get_entity_links: {str(e)}"


def unlink_entities(link_id: str) -> str:
    """Remove a link by its ID.

    Args:
        link_id: The link ID (shown in get_entity_links results).

    Returns:
        Confirmation.
    """
    try:
        if not link_id or not link_id.strip():
            return "Error: link_id is required."
        deleted = _delete_link(link_id.strip())
        if deleted:
            return f"Link {link_id.strip()} removed."
        return f"No link found with id: {link_id.strip()}"
    except Exception as e:
        return f"Error in unlink_entities: {str(e)}"
