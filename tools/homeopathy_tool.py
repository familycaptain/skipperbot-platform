"""DEPRECATED — Moved to apps/homeopathy/tools.py (app package).
This file is no longer imported. Safe to delete.

Homeopathy Tools — Track homeopathic remedy inventory: medicines, remedies,
bottle sizes, locations, sources, and physical bottles with fullness tracking.
"""

import json
import os
import sys
import uuid
from datetime import date
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import logger
from data_layer import homeopathy as _dl


# ---------------------------------------------------------------------------
# Sources (suppliers)
# ---------------------------------------------------------------------------

def add_homeo_source(
    name: str,
    created_by: str = "",
    website: str = "",
    phone: str = "",
    notes: str = "",
) -> str:
    """Add a homeopathic remedy supplier/source.

    Args:
        name: Supplier name (e.g. "Hahnemann Labs", "Washington Homeopathic").
        created_by: Who is adding this.
        website: Supplier website URL (optional).
        phone: Supplier phone number (optional).
        notes: Additional notes.

    Returns:
        Confirmation with source ID.

    Ack: Adding source...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        src_id = f"hsrc-{uuid.uuid4().hex[:8]}"
        _dl.save_source({
            "id": src_id, "name": name.strip(), "website": website.strip(),
            "phone": phone.strip(), "notes": notes.strip(), "created_by": created_by.strip(),
        })
        logger.info("HOMEO: Created source '%s' (%s)", name.strip(), src_id)
        return f"Source added: '{name.strip()}' ({src_id})"
    except Exception as e:
        return f"Error in add_homeo_source: {e}"


def list_homeo_sources() -> str:
    """List all homeopathic remedy suppliers/sources.

    Returns:
        Formatted list of sources.

    Ack: Listing sources...
    """
    try:
        sources = _dl.get_all_sources()
        if not sources:
            return "No sources defined yet."
        lines = [f"Sources ({len(sources)}):\n"]
        for s in sources:
            web = f" | {s['website']}" if s.get("website") else ""
            lines.append(f"- {s['name']} ({s['id']}){web}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_homeo_sources: {e}"


# ---------------------------------------------------------------------------
# Medicines (name + description)
# ---------------------------------------------------------------------------

def add_homeo_medicine(
    name: str,
    created_by: str = "",
    description: str = "",
    notes: str = "",
) -> str:
    """Add a homeopathic medicine definition (name + what it's used for).

    Args:
        name: Medicine name (e.g. "Arnica Montana", "Belladonna", "Nux Vomica").
        created_by: Who is adding this.
        description: Short description of what the medicine is used for.
        notes: Additional notes.

    Returns:
        Confirmation with medicine ID.

    Ack: Adding medicine...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        existing = _dl.get_medicine_by_name(name.strip())
        if existing:
            return f"Medicine '{name.strip()}' already exists ({existing['id']}). Use update instead."
        med_id = f"hmed-{uuid.uuid4().hex[:8]}"
        _dl.save_medicine({
            "id": med_id, "name": name.strip(), "description": description.strip(),
            "notes": notes.strip(), "created_by": created_by.strip(),
        })
        logger.info("HOMEO: Created medicine '%s' (%s)", name.strip(), med_id)
        return f"Medicine added: '{name.strip()}' ({med_id})"
    except Exception as e:
        return f"Error in add_homeo_medicine: {e}"


def list_homeo_medicines() -> str:
    """List all homeopathic medicine definitions.

    Returns:
        Formatted list of medicines with descriptions.

    Ack: Listing medicines...
    """
    try:
        meds = _dl.get_all_medicines()
        if not meds:
            return "No medicines defined yet."
        lines = [f"Medicines ({len(meds)}):\n"]
        for m in meds:
            desc = f" — {m['description']}" if m.get("description") else ""
            lines.append(f"- {m['name']} ({m['id']}){desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_homeo_medicines: {e}"


# ---------------------------------------------------------------------------
# Remedies (medicine + strength)
# ---------------------------------------------------------------------------

def add_homeo_remedy(
    medicine_name: str,
    strength: str,
    created_by: str = "",
    source_name: str = "",
    notes: str = "",
) -> str:
    """Add a remedy — a specific medicine at a specific strength/potency.

    The medicine must already exist (use add_homeo_medicine first).
    Strength is freeform: "6C", "30C", "200C", "1M", "10M", "tincture", etc.

    Args:
        medicine_name: Name of the medicine (must already exist).
        strength: Potency/strength (e.g. "30C", "200C", "1M", "tincture").
        created_by: Who is adding this.
        source_name: Name of the supplier (optional, must already exist if provided).
        notes: Additional notes.

    Returns:
        Confirmation with remedy ID.

    Ack: Adding remedy...
    """
    try:
        if not medicine_name or not strength:
            return "Error: medicine_name and strength are required."
        med = _dl.get_medicine_by_name(medicine_name.strip())
        if not med:
            return f"Error: Medicine '{medicine_name}' not found. Add it first with add_homeo_medicine."
        existing = _dl.get_remedy_by_name_strength(medicine_name.strip(), strength.strip())
        if existing:
            return f"Remedy '{medicine_name} {strength}' already exists ({existing['id']})."
        source_id = None
        if source_name and source_name.strip():
            sources = _dl.get_all_sources()
            match = next((s for s in sources if s["name"].lower() == source_name.strip().lower()), None)
            if not match:
                return f"Error: Source '{source_name}' not found. Add it first with add_homeo_source."
            source_id = match["id"]
        rem_id = f"hrem-{uuid.uuid4().hex[:8]}"
        _dl.save_remedy({
            "id": rem_id, "medicine_id": med["id"], "strength": strength.strip(),
            "source_id": source_id, "notes": notes.strip(), "created_by": created_by.strip(),
        })
        logger.info("HOMEO: Created remedy '%s %s' (%s)", medicine_name.strip(), strength.strip(), rem_id)
        return f"Remedy added: '{medicine_name.strip()} {strength.strip()}' ({rem_id})"
    except Exception as e:
        return f"Error in add_homeo_remedy: {e}"


# ---------------------------------------------------------------------------
# Bottle Sizes
# ---------------------------------------------------------------------------

def add_homeo_bottle_size(
    name: str,
    created_by: str = "",
    sort_order: int = 0,
) -> str:
    """Add a bottle size definition.

    Args:
        name: Size name (e.g. "1 dram", "2 dram", "4 dram", "half oz", "1 oz", "28g", "mini").
        created_by: Who is adding this.
        sort_order: Display order (0 = default, lower = first).

    Returns:
        Confirmation with size ID.

    Ack: Adding bottle size...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        size_id = f"hsize-{uuid.uuid4().hex[:8]}"
        _dl.save_bottle_size({
            "id": size_id, "name": name.strip(), "sort_order": sort_order,
            "created_by": created_by.strip(),
        })
        logger.info("HOMEO: Created bottle size '%s' (%s)", name.strip(), size_id)
        return f"Bottle size added: '{name.strip()}' ({size_id})"
    except Exception as e:
        return f"Error in add_homeo_bottle_size: {e}"


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def add_homeo_location(
    name: str,
    created_by: str = "",
    sort_order: int = 0,
) -> str:
    """Add a storage location for bottles.

    Args:
        name: Location name (e.g. "Drawer 6", "Drawer 10", "purse", "red box").
        created_by: Who is adding this.
        sort_order: Display order (0 = default, lower = first).

    Returns:
        Confirmation with location ID.

    Ack: Adding location...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."
        loc_id = f"hloc-{uuid.uuid4().hex[:8]}"
        _dl.save_location({
            "id": loc_id, "name": name.strip(), "sort_order": sort_order,
            "created_by": created_by.strip(),
        })
        logger.info("HOMEO: Created location '%s' (%s)", name.strip(), loc_id)
        return f"Location added: '{name.strip()}' ({loc_id})"
    except Exception as e:
        return f"Error in add_homeo_location: {e}"


# ---------------------------------------------------------------------------
# Bottles (inventory)
# ---------------------------------------------------------------------------

def add_homeo_bottle(
    remedy_name: str,
    strength: str,
    created_by: str = "",
    size_name: str = "",
    location_name: str = "",
    fullness: int = 100,
    notes: str = "",
) -> str:
    """Add a physical bottle to the inventory.

    The remedy (medicine + strength) must already exist.
    Size and location are looked up by name.

    Args:
        remedy_name: Medicine name (e.g. "Arnica Montana").
        strength: Potency (e.g. "200C").
        created_by: Who is adding this.
        size_name: Bottle size (e.g. "2 dram"). Empty = unspecified.
        location_name: Where the bottle is stored (e.g. "Drawer 6"). Empty = unspecified.
        fullness: How full the bottle is (0, 25, 33, 50, 67, 75, or 100). Default 100.
        notes: Additional notes.

    Returns:
        Confirmation with bottle ID.

    Ack: Adding bottle...
    """
    try:
        if not remedy_name or not strength:
            return "Error: remedy_name and strength are required."
        remedy = _dl.get_remedy_by_name_strength(remedy_name.strip(), strength.strip())
        if not remedy:
            return f"Error: Remedy '{remedy_name} {strength}' not found. Add it first."
        size_id = None
        if size_name and size_name.strip():
            sizes = _dl.get_all_bottle_sizes()
            match = next((s for s in sizes if s["name"].lower() == size_name.strip().lower()), None)
            if not match:
                return f"Error: Bottle size '{size_name}' not found. Add it first with add_homeo_bottle_size."
            size_id = match["id"]
        location_id = None
        if location_name and location_name.strip():
            locs = _dl.get_all_locations()
            match = next((l for l in locs if l["name"].lower() == location_name.strip().lower()), None)
            if not match:
                return f"Error: Location '{location_name}' not found. Add it first with add_homeo_location."
            location_id = match["id"]
        bot_id = f"hbot-{uuid.uuid4().hex[:8]}"
        _dl.save_bottle({
            "id": bot_id, "remedy_id": remedy["id"], "size_id": size_id,
            "location_id": location_id, "fullness": fullness,
            "last_checked": date.today().isoformat(),
            "notes": notes.strip(), "created_by": created_by.strip(),
        })
        logger.info("HOMEO: Added bottle '%s %s' (%s)", remedy_name.strip(), strength.strip(), bot_id)
        size_str = f" [{size_name.strip()}]" if size_name else ""
        loc_str = f" in {location_name.strip()}" if location_name else ""
        return f"Bottle added: {remedy_name.strip()} {strength.strip()}{size_str}{loc_str} — {_fullness_label(fullness)} ({bot_id})"
    except Exception as e:
        return f"Error in add_homeo_bottle: {e}"


def update_homeo_bottle(
    bottle_id: str,
    fullness: int = -1,
    location_name: str = "",
    size_name: str = "",
    notes: str = "",
) -> str:
    """Update a bottle's fullness, location, size, or notes.

    Args:
        bottle_id: The bottle ID (e.g. "hbot-abc12345").
        fullness: New fullness level (0/25/33/50/67/75/100). -1 = don't change.
        location_name: New location name. Empty = don't change.
        size_name: New size name. Empty = don't change.
        notes: New notes. Empty = don't change.

    Returns:
        Confirmation of update.

    Ack: Updating bottle...
    """
    try:
        if not bottle_id:
            return "Error: bottle_id is required."
        updates = {}
        if fullness >= 0:
            updates["fullness"] = fullness
            updates["last_checked"] = date.today().isoformat()
        if location_name and location_name.strip():
            locs = _dl.get_all_locations()
            match = next((l for l in locs if l["name"].lower() == location_name.strip().lower()), None)
            if not match:
                return f"Error: Location '{location_name}' not found."
            updates["location_id"] = match["id"]
        if size_name and size_name.strip():
            sizes = _dl.get_all_bottle_sizes()
            match = next((s for s in sizes if s["name"].lower() == size_name.strip().lower()), None)
            if not match:
                return f"Error: Size '{size_name}' not found."
            updates["size_id"] = match["id"]
        if notes:
            updates["notes"] = notes.strip()
        if not updates:
            return "No fields to update."
        ok = _dl.update_bottle(bottle_id.strip(), updates)
        if ok:
            return f"Bottle {bottle_id} updated."
        return f"Error: Bottle '{bottle_id}' not found."
    except Exception as e:
        return f"Error in update_homeo_bottle: {e}"


def list_homeo_bottles(
    location_name: str = "",
    low_only: bool = False,
    remedy_name: str = "",
    strength: str = "",
) -> str:
    """List bottles in the inventory, optionally filtered.

    Args:
        location_name: Filter by location name. Empty = all locations.
        low_only: If true, only show bottles with fullness <= 25%.
        remedy_name: Filter by medicine name (partial match via search). Empty = all.
        strength: Filter by strength (e.g. "200C"). Empty = all.

    Returns:
        Formatted inventory list grouped by strength.

    Ack: Listing bottles...
    """
    try:
        if remedy_name and remedy_name.strip():
            bottles = _dl.search_bottles(remedy_name.strip())
            if low_only:
                bottles = [b for b in bottles if b["fullness"] <= 25]
            if strength:
                bottles = [b for b in bottles if b["strength"].lower() == strength.strip().lower()]
        else:
            location_id = None
            if location_name and location_name.strip():
                locs = _dl.get_all_locations()
                match = next((l for l in locs if l["name"].lower() == location_name.strip().lower()), None)
                if match:
                    location_id = match["id"]
            bottles = _dl.get_all_bottles(
                location_id=location_id, low_only=low_only, strength=strength.strip() if strength else None,
            )
        if not bottles:
            return "No bottles found matching your criteria."
        return _format_bottles(bottles)
    except Exception as e:
        return f"Error in list_homeo_bottles: {e}"


def get_homeo_reorder_list() -> str:
    """Get bottles that need reordering (fullness <= 25%), grouped by supplier.

    Returns:
        Shopping list grouped by source/supplier.

    Ack: Getting reorder list...
    """
    try:
        bottles = _dl.get_reorder_list()
        if not bottles:
            return "No bottles need reordering — everything is above 25% full."
        by_source = {}
        for b in bottles:
            src = b.get("source_name") or "Unknown Source"
            if src not in by_source:
                by_source[src] = []
            by_source[src].append(b)
        lines = [f"Reorder List ({len(bottles)} bottles):\n"]
        for src, bots in sorted(by_source.items()):
            lines.append(f"── {src} ──")
            for b in bots:
                size = f" [{b['size_name']}]" if b.get("size_name") else ""
                loc = f" ({b['location_name']})" if b.get("location_name") else ""
                lines.append(f"  {b['medicine_name']} {b['strength']}{size}{loc} — {_fullness_label(b['fullness'])}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_homeo_reorder_list: {e}"


def search_homeo(query: str) -> str:
    """Search across medicines, remedies, bottles, locations, and notes.

    Args:
        query: Search text (partial match).

    Returns:
        Matching bottles with details.

    Ack: Searching...
    """
    try:
        if not query or not query.strip():
            return "Error: query is required."
        bottles = _dl.search_bottles(query.strip())
        if not bottles:
            return f"No results for '{query}'."
        return _format_bottles(bottles)
    except Exception as e:
        return f"Error in search_homeo: {e}"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_FULLNESS_LABELS = {
    0: "Empty", 25: "1/4", 33: "1/3", 50: "1/2", 67: "2/3", 75: "3/4", 100: "Full",
}


def _fullness_label(val: int) -> str:
    return _FULLNESS_LABELS.get(val, f"{val}%")


def _format_bottles(bottles: list[dict]) -> str:
    """Format bottles grouped by strength."""
    groups = {}
    for b in bottles:
        strength = b.get("strength", "?")
        if strength not in groups:
            groups[strength] = {}
        med = b.get("medicine_name", "?")
        if med not in groups[strength]:
            groups[strength][med] = []
        groups[strength][med].append(b)

    lines = [f"Inventory ({len(bottles)} bottles):\n"]
    for strength in sorted(groups.keys(), key=_strength_sort_key):
        lines.append(f"══ {strength} ══")
        for med_name in sorted(groups[strength].keys()):
            bots = groups[strength][med_name]
            parts = []
            for b in bots:
                size = b.get("size_name") or "?"
                loc = b.get("location_name") or "?"
                full = _fullness_label(b["fullness"])
                parts.append(f"{size} ({loc}) — {full}")
            lines.append(f"  {med_name}: {'; '.join(parts)}")
        lines.append("")
    return "\n".join(lines)


def _strength_sort_key(strength: str) -> tuple:
    s = strength.upper().strip()
    if s.endswith("M"):
        try:
            return (0, -int(s[:-1]))
        except ValueError:
            pass
    if s.endswith("C"):
        try:
            return (1, -int(s[:-1]))
        except ValueError:
            pass
    if s.endswith("X"):
        try:
            return (2, -int(s[:-1]))
        except ValueError:
            pass
    return (3, 0)
