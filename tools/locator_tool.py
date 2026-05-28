"""DEPRECATED — Moved to apps/home/tools.py (app package).
This file is no longer imported. Safe to delete.

Original: Item Locator Tools — Track where things are in the household.
All located items are stored as loc-* entities with location, sub-location, and tags.
"""

import json
import os
import sys
import uuid
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app_platform.memory import digest_record
from config import logger
from data_layer import locator as _dl


def create_located_item(
    name: str,
    created_by: str,
    location: str = "",
    sub_location: str = "",
    category: str = "",
    description: str = "",
    tags: str = "[]",
    quantity: int = 0,
    notes: str = "",
) -> str:
    """Create a new located item to track where something is stored.

    Use this when the user says things like "remember that the camping gear is in the garage"
    or "add the Christmas decorations to the attic". After creating, ALWAYS call
    open_app(app_type="locator-item", locatorItemId="<the_id>") to open the item.

    Args:
        name: Item name (e.g. "Camping Gear", "Christmas Decorations", "Power Drill").
        created_by: Who is creating it (e.g. "alice").
        location: Where the item is (e.g. "Garage", "Attic", "Master Closet").
        sub_location: More specific spot (e.g. "Top shelf", "Bin #3", "Under workbench").
        category: Item category (e.g. "Seasonal", "Tools", "Sports", "Kitchen").
        description: Details about the item or contents of a bin/box.
        tags: JSON array of tag strings (e.g. '["camping", "outdoor"]').
        quantity: Number of items (0 = not specified, e.g. "3 boxes").
        notes: Additional notes.

    Returns:
        Confirmation with item ID.

    Ack: Adding "{name}" to item locator...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        if not created_by or not created_by.strip():
            return "Error: created_by is required."

        try:
            tag_list = json.loads(tags) if isinstance(tags, str) else tags
        except (json.JSONDecodeError, TypeError):
            tag_list = []

        item_id = f"loc-{uuid.uuid4().hex[:8]}"
        item = {
            "id": item_id,
            "name": name.strip(),
            "description": description.strip() if description else "",
            "location": location.strip() if location else "",
            "sub_location": sub_location.strip() if sub_location else "",
            "category": category.strip() if category else "",
            "tags": tag_list,
            "quantity": quantity if quantity > 0 else None,
            "notes": notes.strip() if notes else "",
            "created_by": created_by.strip(),
        }

        _dl.save_item(item)
        logger.info("LOCATOR: Created '%s' (%s) at %s by %s",
                     name.strip(), item_id, location, created_by.strip())
        try:
            digest_record("locator", "located item", "created", item_id, item, by=created_by.strip())
        except Exception:
            pass

        loc_display = f" at {location.strip()}" if location else ""
        sub_display = f" ({sub_location.strip()})" if sub_location else ""
        return (
            f"Item tracked: '{name.strip()}' ({item_id}){loc_display}{sub_display}\n"
            f"Now call open_app(app_type=\"locator-item\", locatorItemId=\"{item_id}\") to open it."
        )

    except Exception as e:
        return f"Error in create_located_item: {str(e)}"


def get_located_item(item_id: str) -> str:
    """Get full details of a located item.

    Args:
        item_id: The item ID (e.g. "loc-abc12345").

    Returns:
        Formatted item details.

    Ack: Loading item...
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."

        item = _dl.get_item(item_id.strip())
        if not item:
            return f"Error: Item '{item_id}' not found."

        return _format_item(item)

    except Exception as e:
        return f"Error in get_located_item: {str(e)}"


def list_located_items(location: str = "", category: str = "") -> str:
    """List all tracked items, optionally filtered by location or category.

    Args:
        location: Filter by location (e.g. "Garage"). Empty = all items.
        category: Filter by category (e.g. "Tools"). Empty = all categories.

    Returns:
        Formatted list of items.

    Ack: Listing located items...
    """
    try:
        if location and location.strip():
            items = _dl.filter_by_location(location.strip())
        elif category and category.strip():
            items = _dl.filter_by_category(category.strip())
        else:
            items = _dl.get_all_items()

        if not items:
            if location:
                return f"No items found at '{location}'."
            if category:
                return f"No items found in category '{category}'."
            return "No items tracked yet."

        lines = [f"Found {len(items)} item(s):\n"]
        for item in items:
            loc = f" 📍 {item['location']}" if item.get("location") else ""
            sub = f" ({item['sub_location']})" if item.get("sub_location") else ""
            cat = f" [{item['category']}]" if item.get("category") else ""
            qty = f" ×{item['quantity']}" if item.get("quantity") else ""
            lines.append(f"- {item['name']} ({item['id']}){loc}{sub}{cat}{qty}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_located_items: {str(e)}"


def search_located_items(query: str) -> str:
    """Search located items by name, description, location, or tags.

    Use this when a user asks "where is the ___?" or "find the ___".

    Args:
        query: Search terms (e.g. "camping", "drill", "christmas").

    Returns:
        Matching items with location details.

    Ack: Searching items for "{query}"...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."

        items = _dl.search_items(query.strip())
        if not items:
            return f"No items match '{query}'."

        lines = [f"Found {len(items)} item(s) matching '{query}':\n"]
        for item in items:
            loc = f" 📍 {item['location']}" if item.get("location") else ""
            sub = f" ({item['sub_location']})" if item.get("sub_location") else ""
            lines.append(f"- {item['name']} ({item['id']}){loc}{sub}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in search_located_items: {str(e)}"


def update_located_item(
    item_id: str,
    name: str = "",
    location: str = "",
    sub_location: str = "",
    category: str = "",
    description: str = "",
    tags: str = "",
    quantity: int = -1,
    notes: str = "",
) -> str:
    """Update a located item. Only provided fields are changed.

    Pass empty string for text fields to leave unchanged. Pass -1 for quantity to leave unchanged.

    Args:
        item_id: The item to update (e.g. "loc-abc12345").
        name: New name (empty = keep current).
        location: New location (empty = keep current).
        sub_location: New sub-location (empty = keep current).
        category: New category (empty = keep current).
        description: New description (empty = keep current).
        tags: New tags as JSON array (empty = keep current).
        quantity: New quantity (-1 = keep current, 0 = clear).
        notes: New notes (empty = keep current).

    Returns:
        Confirmation of update.

    Ack: Updating item {item_id}...
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."

        updates = {}
        if name:
            updates["name"] = name.strip()
        if location:
            updates["location"] = location.strip()
        if sub_location:
            updates["sub_location"] = sub_location.strip()
        if category:
            updates["category"] = category.strip()
        if description:
            updates["description"] = description.strip()
        if tags:
            try:
                updates["tags"] = json.loads(tags) if isinstance(tags, str) else tags
            except json.JSONDecodeError:
                return "Error: tags must be valid JSON."
        if quantity >= 0:
            updates["quantity"] = quantity if quantity > 0 else None
        if notes:
            updates["notes"] = notes.strip()

        if not updates:
            return "No fields to update."

        success = _dl.update_item(item_id.strip(), updates)
        if success:
            try:
                record = _dl.get_item(item_id.strip()) or {"id": item_id.strip(), **updates}
                digest_record("locator", "located item", "updated", item_id.strip(), record, by="")
            except Exception:
                pass
            fields = ", ".join(updates.keys())
            return f"Item {item_id} updated. Changed: {fields}"
        return f"Error: Item '{item_id}' not found."

    except Exception as e:
        return f"Error in update_located_item: {str(e)}"


def delete_located_item(item_id: str) -> str:
    """Delete a located item permanently.

    Args:
        item_id: The item to delete (e.g. "loc-abc12345").

    Returns:
        Confirmation or error.

    Ack: Deleting item {item_id}...
    """
    try:
        if not item_id or not item_id.strip():
            return "Error: item_id is required."

        record = _dl.get_item(item_id.strip()) or {"id": item_id.strip()}
        success = _dl.delete_item(item_id.strip())
        if success:
            try:
                digest_record("locator", "located item", "deleted", item_id.strip(), record, by="")
            except Exception:
                pass
            return f"Item '{item_id}' deleted."
        return f"Error: Item '{item_id}' not found."

    except Exception as e:
        return f"Error in delete_located_item: {str(e)}"


def list_item_locations() -> str:
    """List all defined storage locations.

    Returns:
        Formatted list of locations.

    Ack: Listing locations...
    """
    try:
        locs = _dl.get_all_locations()
        if not locs:
            return "No locations defined yet."

        lines = [f"Locations ({len(locs)}):\n"]
        for loc in locs:
            desc = f" — {loc['description']}" if loc.get("description") else ""
            lines.append(f"- {loc['name']} ({loc['id']}){desc}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error in list_item_locations: {str(e)}"


def create_item_location(name: str, description: str = "") -> str:
    """Create a new storage location (e.g. "Garage", "Attic", "Storage Shed").

    Args:
        name: Location name.
        description: Optional description of the space.

    Returns:
        Confirmation with location ID.

    Ack: Creating location "{name}"...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."

        loc_id = f"iloc-{uuid.uuid4().hex[:8]}"
        loc = _dl.create_location(loc_id, name.strip(), description.strip() if description else "")
        if loc:
            return f"Location created: '{loc['name']}' ({loc['id']})"
        return "Error: Location creation failed (name may already exist)."

    except Exception as e:
        return f"Error in create_item_location: {str(e)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_item(item: dict) -> str:
    """Format a located item for text output."""
    loc = f"📍 Location: {item['location']}" if item.get("location") else "📍 Location: (not set)"
    sub = f" > {item['sub_location']}" if item.get("sub_location") else ""
    cat = f"\nCategory: {item['category']}" if item.get("category") else ""
    tags = f"\nTags: {', '.join(item['tags'])}" if item.get("tags") else ""
    qty = f"\nQuantity: {item['quantity']}" if item.get("quantity") else ""
    desc = f"\n{item['description']}" if item.get("description") else ""
    notes = f"\nNotes: {item['notes']}" if item.get("notes") else ""

    return (
        f"# {item['name']} ({item['id']})\n"
        f"{loc}{sub}{cat}{tags}{qty}{desc}{notes}\n"
        f"By: {item.get('created_by', '?')}"
    ).strip()
