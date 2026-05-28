> **DEPRECATED** — Moved to `apps/home/guide.md` (app package).
> This file is no longer loaded. Safe to delete.

# Item Locator Guide

## Overview

The Item Locator app tracks where physical items are stored in the household. Items (`loc-*`) have
a location, sub-location, category, tags, and optional quantity. Use it when someone asks "where is
the ___?" or wants to record where something is kept.

## Available Tools

### Item CRUD (MCP tools)

- `create_located_item(name, created_by, location, sub_location, category, ...)` — track a new item
- `get_located_item(item_id)` — get full item details
- `list_located_items(location?, category?)` — list items, optionally filtered
- `search_located_items(query)` — search by name, description, location, tags
- `update_located_item(item_id, location?, sub_location?, ...)` — partial update (move item, rename, etc.)
- `delete_located_item(item_id)` — remove permanently

### Location Management (MCP tools)

- `list_item_locations()` — list all defined locations
- `create_item_location(name, description?)` — create a new location

### Visual App (local tool)

- `open_app(app_type="locator")` — open the item locator list
- `open_app(app_type="locator-item", locatorItemId="loc-abc123")` — open a specific item

## Retrieving Items

When a user asks "where is the ___?" or "find the ___", **always search first**:

1. Call `search_located_items(query="camping gear")` using the item name or keywords
2. If results come back, tell the user the location
3. If no results, tell the user it's not tracked and offer to add it

**Do NOT ask the user for the item ID.** Just search by name.

## Creating Items via Chat

When a user says "remember that the camping gear is in the garage" or "the Christmas decorations
are in the attic, bin #3", parse it and create:

```
create_located_item(
  name="Camping Gear",
  created_by="alice",
  location="Garage",
  sub_location="Top shelf",
  category="Outdoor",
  tags='["camping", "outdoor"]'
)
```

**After creating, ALWAYS call open_app to show it.**

## Important Rules

1. **Search first, ask later.** When a user asks where something is, call `search_located_items` immediately.
2. **Always open after creating.** Call `open_app` immediately after `create_located_item`.
3. **Parse location details.** If the user says "it's on the top shelf in the garage", set location="Garage" and sub_location="Top shelf".
4. **Infer category.** If not specified, infer from the item (tools → "Tools", holiday items → "Seasonal", etc.).
5. **Tags are flexible.** Use tags for extra searchability (e.g. "camping", "holiday", "power tool").

## Data Model

```
located_item {
  id: "loc-{hex8}"
  name, description
  location: "Garage", "Attic", "Kitchen", etc.
  sub_location: "Top shelf", "Bin #3", "Under workbench"
  category: "Tools", "Seasonal", "Sports", "Kitchen", etc.
  tags: [string]
  quantity: int (for multiples, e.g. "3 boxes")
  notes: string
}
```
