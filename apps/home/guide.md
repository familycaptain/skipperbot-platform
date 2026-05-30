# Home — Tool Guide

## Overview
Home management hub for the household.

- **Maintenance** — Recurring and one-time home maintenance tasks (A/C filter, septic, gutters, etc.)
- **Locator** — Find where physical items are stored in the house
- Appliances, Insurance, Contractors — planned

## Maintenance Tasks

Track routine home maintenance. Items integrate with the Prioritize app (due/overdue tasks show up automatically).

### Tools

- `create_home_task` — Add a recurring or one-time task
- `list_home_tasks` — List all tasks with due status (overdue 🔴, due soon 🟡, on schedule 🟢)
- `get_home_task` — Get full details including completion history
- `update_home_task` — Edit a task (name, interval, due date, activate/deactivate)
- `delete_home_task` — Remove a task and its completion history permanently
- `complete_home_task` — Mark a task done; recurring tasks auto-advance their next due date
- `get_overdue_home_tasks` — Quick summary of overdue/upcoming tasks
- `get_recent_maintenance_log` — Recent completions across all tasks (log entries with IDs)
- `delete_maintenance_log_entry` — Remove a specific completion record

### Task Categories

- `list_task_categories` — List all configured categories with IDs
- `create_task_category` — Add a new category (e.g. "Pool", "Roofing", "Landscaping")
- `update_task_category` — Rename or recolor a category
- `delete_task_category` — Remove a category

### Key rules

1. **Recurring vs. ad-hoc**: Recurring tasks auto-reset next_due when completed. Ad-hoc tasks disappear once done.
2. **interval_days**: 30=monthly, 90=quarterly, 180=every 6 months, 365=yearly.
3. **next_due_at**: Required if you want a task to show as due. Set to today or a future date.
4. **Completion notes**: Ask for notes when relevant (e.g. "Used MERV-13 filter" for A/C; "Added 1 packet" for septic).
5. **Overdue check**: When user asks "what's due around the house?" or "what maintenance is overdue?", use `get_overdue_home_tasks`.
6. **CRITICAL — Check before creating**: Before calling `create_home_task`, ALWAYS call `list_home_tasks` first. If an existing task already matches what the user did (same action, even if phrased differently — e.g. "Changed the A/C filter" = "replaced HVAC filter"), complete THAT task with `complete_home_task` instead of creating a new one. Never create a duplicate task for something already tracked.

### Common categories
HVAC, Plumbing, Exterior, Electrical, Pest Control, General

## Home Issues

Track problems, repairs, and things that need attention around the house.

### Tools

- `list_home_issues` — List all issues, optionally filtered by status or location
- `create_home_issue` — Log a new problem (e.g. "Leaky faucet in kitchen", "Crack in drywall")
- `get_home_issue` — Get full details of an issue
- `update_home_issue` — Update status, add fix details, record cost. To resolve: set status="resolved", date_fixed, fix_description
- `delete_home_issue` — Remove an issue permanently

### Severity levels
`minor` (cosmetic, not urgent), `moderate` (needs attention), `major` (affects function), `critical` (safety/structural)

### Status values
`open` → `in_progress` → `resolved`

## Locator

Track where physical items are stored around the household. This is the go-to system whenever someone mentions the physical location of an item — whether they're TELLING you where something is or ASKING you where something is.

### Detecting location intent

If the user says something that sounds like they're telling you where a physical item is — even casually — you should record it in the Locator. Examples:
- "The camping gear is in the garage on the top shelf"
- "I put the drill back in the shed"
- "The Christmas decorations are in the attic, in the blue bins"
- "The spare keys are on the hook by the front door"
- "We keep the suitcases in the guest room closet"

Do NOT just save this as a memory. Create (or update) a located item so it's searchable and structured.

### Workflow: Recording an item location

1. **Check existing items first** — Call `search_located_items` with the item name to see if it's already tracked. If found, use `update_located_item` to update the location instead of creating a duplicate.
2. **Check available locations** — Call `list_item_locations` to see what locations already exist. Match what the user said to an existing location name if possible (e.g., if they say "the garage" and "Garage" exists, use "Garage").
3. **Create a new location if needed** — If the location they mention doesn't match any existing one, call `create_item_location` to add it first. Use title case (e.g., "Guest Room", "Storage Shed", "Front Porch").
4. **Create or update the item** — Call `create_located_item` or `update_located_item` with:
   - **location** (REQUIRED): The broad area/room (e.g., "Garage", "Kitchen", "Master Bedroom"). This must match an existing location name.
   - **sub_location** (optional but encouraged): The specific spot within the location (e.g., "Top shelf", "Under the workbench", "Left cabinet, second drawer", "On the hook by the door"). Be as specific as the user was.
   - **category**: Infer a sensible category from context (e.g., "Tools", "Seasonal", "Sports", "Kitchen", "Office", "Electronics", "Cleaning").
   - **tags**: Add relevant searchable tags as a JSON array.
5. **Confirm briefly** — Tell the user you've recorded it. Don't be verbose.

### Workflow: Finding an item

When someone asks "where is the ___?" or "can you find the ___?":

1. Call `search_located_items` with the item name or partial name.
2. If found, report the location AND sub-location so they can actually find it physically.
3. If not found, say you don't have it tracked and offer to add it if they know where it is.

### Tools

- `create_located_item` — Add a new item with its location
- `search_located_items` — Find items by name, description, location, or tags
- `list_located_items` — List all items or filter by location/category
- `update_located_item` — Move or update an existing item's location
- `delete_located_item` — Remove an item from tracking
- `list_item_locations` — List all defined storage locations (rooms/areas)
- `create_item_location` — Add a new storage location
- `delete_item_location` — Remove a location definition
- `get_located_item` — Get full details of a specific item
