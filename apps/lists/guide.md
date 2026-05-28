# Lists & Trello Guide

## Two kinds of lists

1. **Local lists** — standalone, stored as `l-*.json` files in `lists/`
2. **Trello-linked lists** — local `l-*.json` file linked to a Trello board/list.
   Trello is source of truth. Adds/removes write through to Trello automatically.

## Connecting a Trello board

When the user says "connect to my shopping board" or "link my project-alpha board":

### Already-configured board (exists in trello_boards.json)
- `connect_trello_board("shopping", "alice")` — scans all lists, creates l-* files, syncs cards

### New board (not yet configured)
- Need the Trello board ID (from the board URL: `https://trello.com/b/BOARD_ID/...`)
- `connect_trello_board("myboard", "alice", board_id="abc123")` — registers in
  trello_boards.json, then scans and connects
- Account auto-detection: "bob" for project-alpha boards, "your-family" for everything else
- If unclear which account, ASK the user before calling

### What connect does
1. Registers the board in `data/trello_boards.json` (if new)
2. Calls Trello API to get all lists on the board
3. Creates a local `l-*` file for each list, linked to Trello
4. Syncs existing cards as items
5. After connecting, every list on that board is available by name

**Example:** "Connect to my shopping trello board" →
`connect_trello_board("shopping", "alice")` → creates l-* files for Hobby Lobby,
Aldi, Costco, etc. — all with cards synced.

After that, "add screws to hobby lobby" → `add_list_item("Hobby Lobby", "screws", "alice")`
→ finds the local l-* file → writes through to Trello automatically.

## Disconnecting a board

`disconnect_trello_board("shopping")` removes:
1. All local l-* list files linked to that board
2. The board entry from trello_boards.json

Does NOT delete anything on Trello. The board can be re-connected later.

**CRITICAL: NEVER delete a Trello board.** There is no tool for it and you must never
attempt to create one. Trello boards are the user's real data. Disconnect only removes
local tracking — the board, its lists, and all cards remain safe on Trello.

## Local lists

- `create_list("Weekend To-Do", "alice")` → creates standalone l-* file
- `add_list_item("Weekend To-Do", "mow the lawn", "alice")`
- `show_list("Weekend To-Do")`
- Local lists have no Trello connection — they're purely local

## Working with Trello-linked lists

Once connected, use the same tools as local lists:
- `add_list_item("Hobby Lobby", "screws", "alice")` → adds locally + creates Trello card
- `remove_list_item("Hobby Lobby", "li-abc123")` → removes locally + archives Trello card
- `show_list("Hobby Lobby")` → shows local cache (synced from Trello)
- `sync_list("Hobby Lobby")` → force re-sync from Trello

## Direct Trello tools (advanced)

These bypass local lists and talk to Trello directly:
- `trello_show_board("shopping")` → shows all lists and cards on the board
- `trello_add_card("shopping", "Hobby Lobby", "screws")` → adds card directly
- `trello_move_card("shopping", "screws", "Hobby Lobby", "Done")` → moves card
- `trello_archive_card("shopping", "screws")` → archives card

Prefer `add_list_item` over `trello_add_card` when the board is connected — it keeps
the local cache in sync.

## Card details tools

Full read/write access to card details beyond just the title:

### View full card details
`trello_get_card("project-alpha", "Fix login bug")` → returns description, checklists, labels,
comments, attachments, due date, URL — everything on the card.

**Prefer card_id when available** — `trello_show_board` includes card IDs in output.
Use `trello_get_card("project-alpha", card_id="abc123")` for reliable direct lookup.
All card detail tools accept `card_id` as an alternative to `title`.

### Update card fields
`trello_update_card("project-alpha", "Fix login bug", desc="Updated description here")`
- **new_title**: rename the card
- **desc**: set/replace description (use `" "` to clear)
- **due**: set due date (ISO format like "2025-03-15")

### Checklists
- **View**: `trello_card_checklist("project-alpha", "Fix login bug")` → shows all checklists + items
- **Set**: `trello_card_checklist("project-alpha", "Fix login bug", "Steps to Reproduce", "Step 1\nStep 2\nStep 3")`
  - Replaces existing checklist with the same name if one exists
  - Items are newline-separated

### Comments
`trello_add_comment("project-alpha", "Fix login bug", "Reproduced on staging — looks like a null pointer")`

### Labels
- **View**: `trello_card_labels("project-alpha", "Fix login bug")` → shows current labels
- **Add**: `trello_card_labels("project-alpha", "Fix login bug", "add", "Bug", "red")`
  - Creates the label on the board if it doesn't exist yet
  - Colors: green, yellow, orange, red, purple, blue, sky, lime, pink, black
- **Remove**: `trello_card_labels("project-alpha", "Fix login bug", "remove", "Bug")`

### Common user phrases → card detail tool calls

| User says | Tool call |
|-----------|-----------|
| "show me the details on that card" | `trello_get_card(board, title)` |
| "what's on the login bug card?" | `trello_get_card("project-alpha", "login bug")` |
| "update the description on X" | `trello_update_card(board, title, desc="...")` |
| "rename that card to Y" | `trello_update_card(board, title, new_title="Y")` |
| "add a checklist to X" | `trello_card_checklist(board, title, "Checklist", "item1\nitem2")` |
| "add a comment on X" | `trello_add_comment(board, title, "comment text")` |
| "label X as a bug" | `trello_card_labels(board, title, "add", "Bug", "red")` |
| "what labels are on X?" | `trello_card_labels(board, title)` |

## Item history (sticky items)

Trello-linked lists with `track_items` enabled automatically record every card
title and its board/list location during sync. This builds up a history so the
agent can suggest the right board + list when re-adding items.

### Enable tracking on a list
`set_item_tracking("Vegetable Aisle")` → enables item history on that list.
`set_item_tracking("Vegetable Aisle", enabled=False)` → disables it.

Tracking is per-list. Enable it on shopping/grocery lists where items recur.
No extra API calls — recording happens inside the existing sync cycle.

### Suggest where to add an item
`trello_suggest_list("lettuce")` → checks item history and returns:
- Best match: "lettuce" was last on **walmart / Vegetable Aisle**
- Suggested: `board="walmart", list="Vegetable Aisle"`

**When to call this**: Before `trello_add_card` or `add_list_item`, when the user
asks to add something that might have been on a board before. Especially useful for
recurring shopping items.

### How it works
- Each sync (every 5 min), tracked lists record their card titles locally
- Card titles are stored in `data/trello_item_history.json`
- Lookup uses exact match → substring → word overlap, ranked by quality
- No API calls at lookup time — it's all local

### Common user phrases → suggest_list
| User says | Action |
|-----------|--------|
| "we need more lettuce" | `trello_suggest_list("lettuce")` → get board/list → `add_list_item(...)` |
| "put dog food back on the list" | `trello_suggest_list("dog food")` → use suggested board/list |
| "where did I have light bulbs?" | `trello_suggest_list("light bulbs")` → show result |

## Show all lists

`show_all_lists` → shows all local lists (both standalone and Trello-linked)

## Board accounts

Each board in `data/trello_boards.json` is linked to an account with API keys:
- **your-family** account → Shopping, Walmart boards (Alice's keys)
- **bob** account → Project-Alpha board (Bob's keys)

The correct keys are used automatically based on the board.

## Common user phrases → tool calls

Users often speak naturally. Map these patterns to the right tool call:

| User says | Means | Tool call |
|-----------|-------|-----------|
| "momma needs butter from walmart" | Add butter to Momma's List (walmart board) | `add_list_item("Momma's List", "butter", "alice")` |
| "add milk to momma's list" | Same list | `add_list_item("Momma's List", "milk", "alice")` |
| "put lettuce on the veg list" | Vegetable Aisle (walmart board) | `add_list_item("Vegetable Aisle", "lettuce", "alice")` |
| "we need screws from hobby lobby" | Hobby Lobby list (shopping board) | `add_list_item("Hobby Lobby", "screws", "alice")` |
| "add X to aldi" | Aldi list (shopping board) | `add_list_item("Aldi", "X", "alice")` |
| "pick up tofu at walmart" | Vegetable or Non-Veg Aisle — ask if unclear | `add_list_item(...)` |

**Key patterns:**
- "[person] needs [item] from [store/list]" → add item to that person's list on that board
- "put [item] on [list]" → add item
- "pick up [item] at [store]" → add item to the right list on that store's board
- "we need [item]" → ask which list if ambiguous

Lists also support **aliases** (e.g. "momma" → "Momma's List"). The name matching
is fuzzy: "walmart momma's list", "momma", and "Momma's List" all resolve to the same list.
Use `set_list_aliases` to add nicknames to any list.

## Combination patterns

### Shopping workflow
1. Connect board: `connect_trello_board("shopping", "alice")`
2. Add items: `add_list_item("Hobby Lobby", "screws", "alice")`
3. Set reminder to go shopping (r-*)
4. Link reminder to list: `link_entities("r-*", "l-*", relation="shopping_list")`
5. Reminder fires → notification via Discord
6. User checks list on phone via Trello app

### Link a list to a project
- `link_entities("l-*", "p-*", relation="shopping_for")` → materials list for a home project
