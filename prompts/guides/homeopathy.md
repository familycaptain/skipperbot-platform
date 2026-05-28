> **DEPRECATED** — Moved to `apps/homeopathy/guide.md` (app package).
> This file is no longer loaded. Safe to delete.

# Homeopathy — Tool Guide

## Overview
Track Carol's homeopathic remedy inventory — medicines, remedies (medicine + strength),
bottle sizes, storage locations, and physical bottles with fullness tracking.
The goal is knowing what she has, how full each bottle is, and where it lives so she
can identify what needs reordering.

## Available Tools

### Reference Data (set up first)
- `add_homeo_source` — add a supplier (e.g. "Hahnemann Labs", "Washington Homeopathic")
- `list_homeo_sources` — list all suppliers
- `add_homeo_medicine` — add a medicine definition (name + what it's used for)
- `list_homeo_medicines` — list all medicines
- `add_homeo_remedy` — add a remedy (medicine + strength + supplier). Medicine must exist first.
- `add_homeo_bottle_size` — add a bottle size (e.g. "1 dram", "4 dram", "28g", "mini")
- `add_homeo_location` — add a storage location (e.g. "Drawer 6", "Drawer 10", "purse")

### Inventory
- `add_homeo_bottle` — add a physical bottle (remedy + size + location + fullness)
- `update_homeo_bottle` — update a bottle's fullness, location, size, or notes
- `list_homeo_bottles` — list inventory, optionally filtered by location, strength, or low-only
- `search_homeo` — search across medicines, remedies, locations, notes
- `get_homeo_reorder_list` — show everything at 25% or below, grouped by supplier

## Important Rules

1. **Creation order matters** — source → medicine → remedy → bottle. Each depends on the previous.
2. **Fullness values** — use 0, 25, 33, 50, 67, 75, or 100 (quarter + third increments).
   Display as: Empty, 1/4, 1/3, 1/2, 2/3, 3/4, Full.
3. **Strength is freeform** — "6C", "30C", "200C", "1M", "10M", "tincture", "Q", "MT" are all valid.
4. **Lookup by name** — tools accept names (not IDs) for medicine, source, size, and location.
   They do case-insensitive matching.
5. **Grouped display** — inventory is displayed grouped by strength (highest potency first),
   then alphabetically by medicine name within each strength.
6. **Reorder list** — when asked "what do I need to order?", use `get_homeo_reorder_list`.
7. **Primary user** — Carol is the primary user of this system.

## Natural Language Patterns

| User says | Tool to use |
|-----------|------------|
| "What am I low on?" / "What do I need to order?" | `get_homeo_reorder_list` |
| "Show me my inventory" / "List all bottles" | `list_homeo_bottles` |
| "Show me all the 200C" | `list_homeo_bottles(strength="200C")` |
| "Where is my Arnica?" | `search_homeo(query="Arnica")` |
| "Add a bottle of Belladonna 30C, 2 dram, in Drawer 3, full" | `add_homeo_bottle(...)` |
| "The Arnica 200C in Drawer 10 is half full" | `update_homeo_bottle(...)` |
| "What's in Drawer 6?" | `list_homeo_bottles(location_name="Drawer 6")` |
