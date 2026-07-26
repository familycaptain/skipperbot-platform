# Findings — `lists` app

Survey only. Nothing below was fixed. Ordered roughly worst-first within each section.
"Uncertain" is marked where I could not settle it from the code alone.

---

## Correctness / data loss

### 1. Crossing an item off a Trello-linked list is silently undone by the next poll
`apps/lists/store.py::remove_item` marks the item `archived = True` and (when a card id
exists) closes the Trello card. But `apps/lists/store.py::sync_from_trello` rebuilds
`lst["items"]` **only** from the cards Trello returns, and
`apps/lists/data.py::replace_items` then `DELETE`s every row for the list before
re-inserting. Consequence: **archived items do not survive a sync of a linked list** — the
"Archived (N)" section on a board-backed list empties itself within one poll interval
(default 300s). Worse, if the write-through to Trello failed (it is caught and only
logged, see #3), the card is still open, so the item **comes back to the live list** and
the person's cross-off is reverted with no message.

Expected: either archived rows are preserved across `replace_items` (they carry
`archived_at` and are excluded from the signature already), or the app states plainly that
a board-backed list keeps no cross-off history.

### 2. Moving an item between lists on *different* boards leaves the card behind
`apps/lists/store.py::move_item` only writes the move through to Trello when
`from_lst["trello"]["board"] == to_lst["trello"]["board"]`. Across boards (and when the
item has no `trello_card_id`) the local item moves but the card stays where it was. The
next sync of the **source** list re-pulls that card, so the item reappears on the source;
the next sync of the **target** list replaces its items with the target board's cards, so
the moved item disappears from the target. Net effect of a cross-board move: it silently
reverts, having reported success. The comment at `store.py:440` acknowledges the gap
("Trello write-through for moves is complex") but the tool still reports a plain success.

### 3. Every Trello write-through failure is swallowed, and the operation reports success
`store.py::add_item`, `update_item_text`, `remove_item`, `reorder_item` and `move_item` all
wrap the Trello call in `try/except Exception` -> `logger.error(...)` and carry on. The
tool then returns `"Added to 'X': milk"` etc. Because Trello is the source of truth for
that list, the change is guaranteed to be discarded at the next poll. A person is told
"added" for something that will vanish. Expected: the reply distinguishes "added, and it
reached the board" from "added locally only — it will not survive".

### 4. `POST /api/apps/lists/{list_id}/items` trusts client-supplied `added_by`
`agent.py::api_add_list_item` uses `req.added_by` directly, while the sibling
`agent.py::api_create_list` deliberately overwrites the body with
`_actor_name(http_request)` ("the client-supplied value is never trusted",
`agent.py:1886`). So any authenticated caller can attribute a list item to any household
member, and that name is what the UI and the printed list display
(`ListItemRow`, `printList`). Same gap, less serious, on
`api_update_list_item` / `api_remove_list_item` / `api_reorder_list_item`, which record no
actor at all. Expected: `added_by` derived from the verified principal, as
`api_create_list` does.

### 5. `sync_all_trello_lists` makes one Trello round trip per list per cycle
`sync_all_trello_lists` loops over every Trello-linked list and calls `sync_from_trello`,
which calls `get_cards(board, list_name)` — one HTTP request per list, per cycle, with no
batching, even though `trello_client.get_all_cards_on_board` exists and is used by
`trello_show_board`. With a board of 15 lists that is 15 requests every 5 minutes per
board. Not a bug, but worth knowing before the interval is lowered (the code comment at
`store.py:662` refers to a "~30s poller", which the current default of 300s contradicts —
see #26).

---

## Unreachable features / dead code

### 6. A board's `list_aliases` map can never be populated by the product
`app_lists.trello_boards.list_aliases` (JSONB) is read in two places —
`tools.py::_try_trello_match` (natural-language board+list matching) and
`tools.py::connect_trello_board` (seeding per-list nicknames at connect time). The only
writer is `apps/lists/trello_config.py::set_list_aliases`, which **has no callers**: no
route in `routes.py`, no tool in `tools.py`, no control in `TrelloSettings.jsx`. So the
column is always `{}` on a real install and both features that depend on it are dead by
construction. Expected: either a route/tool/UI to edit the map, or remove the column and
the two code paths that read it.

### 7. `trello_boards.default_list` is stored and displayed but never used
Written by `trello_config.save_board`, returned by `get_board`/`list_boards`, shown in
`TrelloSettings.jsx::BoardRow` and in `tools.py::trello_list_boards`. Nothing anywhere
*reads* it to choose a list — `add_card`, `_find_card`, `_try_trello_match` all require an
explicit list name. A column nothing reads, presented to the user as if it configured
something.

### 8. `apps/lists/data.py::add_item` and `apps/lists/data.py::remove_item` are dead
`store.py` persists exclusively through `save_list` + `replace_items`. Repo-wide grep
finds no caller for either function (`apps/todo` imports `archive_item` and `get_list`
only). `data.py::add_item` is the only place a `list_item` digest fires with
`action="created"`, so its being dead also means the item-level `digest_record` calls in
`data.py` never run — item recall relies entirely on `auto_memory.log_entity_change` from
`store.py`. Uncertain whether that was the intent or an artefact of the port.

### 9. `PATCH /api/apps/lists/{list_id}/aliases` has no caller
`agent.py::api_update_list_aliases` exists; `ListsApp.jsx` only *displays* `lst.aliases`
and offers no way to edit them. Nicknames — the mechanism the whole conversational
addressing story depends on — are settable only via the `set_list_aliases` chat tool.
Either the route is dead or the UI is missing an affordance.

### 10. Unused imports in `apps/lists/tools.py`
`show_all_lists as _show_all_lists`, `reorder_item as _reorder_item` and
`move_item as _move_item` are imported at `tools.py:17-32` and never called. Notably
`_show_all_lists` is unused because `tools.py::show_all_lists` re-implements the listing
against Trello directly — see #12.

### 11. No tool exposes reordering, editing item text, or un-crossing-off
The store supports `reorder_item`, `update_item_text` and (in `data.py`) archive, and the
REST API exposes reorder + edit, but **no MCP tool does**. So "move eggs to the top of the
list", "that should say oat milk", and "put milk back on the list" cannot be done through
chat at all — only in the app. There is no unarchive path anywhere, in tool, route or UI.
`specs/SPEC.md` claims tools `reorder_list`, `unarchive_list_item`, `rename_list` exist;
they do not (see #16).

### 12. `show_all_lists(user_id=...)` documents a filter it does not apply
`tools.py::show_all_lists` takes `user_id` with the docstring "Optional. Filter to lists
created by this person" and then never references it — the parameter is dropped on the
floor. (`store.py::show_all_lists`, which *does* honour it, is the unused import from
#10.) The tool also lists board lists straight from Trello plus local **standalone** lists,
so a Trello-linked local list is deliberately not listed twice — but the count line
"Available lists (N)" therefore counts board lists, not the household's lists, and a board
that cannot be fetched contributes the literal line `(could not fetch)` to that count.

---

## Manifest / documentation drift

### 13. `manifest.yaml` declares seven events that nothing emits
`emits: [list.created, list.updated, list.deleted, list_item.added, list_item.archived,
list_item.removed, list.reordered]` and `platform_deps: [... events ...]`. There is no
`emit(` call anywhere in `apps/lists/` — `handlers.py` is an explicit no-op scaffold and
`SPEC.md` documents payload shapes for all seven. Any app subscribing to these would never
fire. Expected: emit them, or drop them from the manifest and SPEC.md.

### 14. `manifest.yaml` claims `platform.time` is used for `archived_at`; it is not
`store.py::remove_item` uses `from datetime import datetime, timezone` /
`datetime.now(timezone.utc)`, not the platform timezone helper (`_now_iso()` in the same
file *does* use it). So `added_at` is household-local time and `archived_at` is UTC — two
different clocks in the same row. `data.py::archive_item` uses SQL `now()`, a third.

### 15. `migrations/README.md` and `SPEC.md` both state "No `002` migration"
`apps/lists/migrations/002_trello_config.sql` exists and is the migration that creates
`trello_accounts` / `trello_boards`. Both documents also say `003+` is where additive
changes go. Straightforward drift from when the Trello config moved out of JSON.

### 16. `specs/SPEC.md` documents a tool surface and a route surface that do not exist
- **Tools claimed, absent:** `list_lists`, `get_list`, `rename_list`, `delete_list`,
  `archive_list_item`, `unarchive_list_item`, `reorder_list`, `move_item_between_lists`,
  `find_list`, `link_list_to_trello`, `sync_list_to_trello`, `unlink_list_from_trello`.
- **Tools that exist, undocumented:** the entire `trello_*` card/label/checklist surface
  (11 tools), `connect_trello_board`, `disconnect_trello_board`, `set_item_tracking`,
  `trello_suggest_list`, `move_list_items`, `show_all_lists`, `show_list`.
- **Routes:** SPEC.md documents them at `/api/apps/lists/lists...` with `PUT` verbs and a
  `POST /lists/{id}/reorder` batch endpoint. Reality: `apps/lists/routes.py` contains
  **only** the Trello account/board endpoints, and all list/item CRUD lives in the monolith
  at `agent.py:2976-3179` under `/api/apps/lists/...` using `PATCH`, with per-item
  `PATCH .../items/{id}/position` rather than a batch reorder. `data.py::batch_reorder`
  exists but is called only by the **Todo** app (`agent.py:3378`).
- Also: SPEC.md says the Trello tools "register only if
  `platform.capabilities.is_enabled('trello')`". They are registered unconditionally; the
  gate is per-call, via `trello_config.get_account_creds` raising.

### 17. "Drag-to-reorder" is claimed in four places and implemented nowhere
`SPEC.md` ("Drag-to-reorder items"), `help.md` ("Items in drag-reorderable order"),
`manifest.yaml` description ("drag-reorderable order") and the old `_capability.yaml`
scope. `ListsApp.jsx::ListItemRow` implements up/down chevron buttons only; there is no
drag handler and no drag-and-drop import. I wrote the corpus against the buttons.

### 18. `help.md` describes a check-off gesture the UI does not have
"*In the app:* tap an item to check it." There is no checkbox and no tap-to-check: the row
offers edit (pencil / double-click), move up, move down, and remove (X, which archives).
The distinction matters because "check off" and "remove" are the same action here.

### 19. `guide.md` is substantially stale
- Describes lists as `l-*.json` files in `lists/` and the board registry as
  `data/trello_boards.json`; both moved to Postgres (`app_lists` schema) in migrations
  001/002. Item history likewise ("stored in `data/trello_item_history.json`" — now
  `public.trello_item_history`).
- States account auto-detection is `"bob" for project-alpha boards, "your-family" for
  everything else`. The code (`tools.py::connect_trello_board`) picks `accounts[0]`. This is
  also **one household's data as intent** — the guide is full of named boards (`walmart`,
  `shopping`, `project-alpha`), a named person's list (`Momma's List`) and named accounts.
  The same applies to the docstring examples throughout `tools.py`.
- `remove_list_item("Hobby Lobby", "li-abc123")` — the tool's second parameter is
  `item_text` and it fuzzy-matches text only. Passing an item id will not match, and the
  reply will list the items instead.
- Claims "Each sync (every 5 min), tracked lists record their card titles **locally**" —
  they are written to Postgres.
- `link_entities("r-*", "l-*", ...)` workflows reference a tool outside this app;
  unverified whether `link_entities` still exists.

### 20. `ListsApp.jsx` reads `getAppManifest("lists")?.blurb`; `manifest.yaml` has no `blurb`
It is passed to `PristineEmpty` as the first-run copy. Uncertain — the web registry may
supply `blurb` separately from the app manifest; worth confirming the pristine-empty state
is not blank on a fresh install.

---

## Smaller / lower confidence

### 21. `printList` writes item text into a new window as raw HTML
`ListsApp.jsx::printList` interpolates `${item.text}` and `${listName}` into a
`document.write` template with no escaping. Item text is household-authored, so this is
self-inflicted at worst — but an item arriving from a **Trello card title** is text from
outside the household's own UI, and a card titled `<img onerror=...>` would execute in the
print window. Low severity, trivially fixed with `textContent`.

### 22. `_try_trello_match` swallows every exception and returns `None`
`tools.py:92` — a bare `except Exception: return None` wrapping the whole body, plus a
nested one around `get_lists`. A credentials error, a network failure and "no such list"
are indistinguishable, and all three surface as `List 'x' not found (checked local lists
and Trello boards)`.

### 23. `create_list` with a Trello link never checks the Trello list exists
`tools.py::create_list` accepts `trello_board` + `trello_list_name`, saves the link, then
calls `_sync_from_trello`. If the named list is not on that board, the list is created
linked to a list that does not exist and the reply is
`Initial sync: Error syncing from Trello: ...`. The broken link persists. Also: neither
`create_list` (the tool) nor `POST /api/apps/lists` can set aliases at creation time, even
though `store.create_list` accepts them (only `connect_trello_board` passes them).

### 24. `find_list_by_name` pass 4 matches aliases as a substring in either direction
`store.py:169-172`: `if alias == norm or alias in norm or norm in alias`. A one- or
two-character alias (nothing prevents one) will match nearly any phrase, and
`norm in alias` means the phrase "mo" matches the alias "momma". Combined with the ordering
(a partial *name* match at pass 3 beats any alias), alias resolution is hard to predict.
Uncertain whether it misbehaves in practice on a real household's data.

### 25. `sync_from_trello` attributes every pulled card to `trello_sync`, with the wrong time
Each card pulled in gets `added_by: "trello_sync"` (special-cased in the UI and in
`printList` to display nothing) and `added_at: card["dateLastActivity"]` — Trello's *last
activity* timestamp, not when the card was added. So a card edited today reads as having
been added today. Minor, but "when did this go on the list" is not answerable for linked
lists.

### 26. `trello_sync.SYNC_INTERVAL` is resolved at import
`trello_sync.py:26` — module-level, so changing the setting needs a restart. The manifest
description does say "Restart to apply", so this is documented behaviour, not a defect.
Noted only because the in-code comment at `store.py:662` refers to a "~30s poller" that no
longer matches the 300s default.

### 27. Perishable build narrative in permanent files
`store.py` ("Ported from `list_store.py` for sub-chunk 4c-part-2. Functionally
identical..."), `data.py` ("Ported ... for sub-chunk 4c"), `handlers.py` ("**Sub-chunk
4a:** scaffold only") and `migrations/README.md` ("**Sub-chunk 4b.**").

### 28. `update_check_item` exists in `trello_client.py` and no lists tool reaches it
A checklist can be created and read, and its tick state displayed, but nothing can tick an
item. Adjacent gap to #11.

---

## Notes on the corpus I wrote

- `lists.trello-boards.sync-list` was **kept at its existing id** because
  `apps/lists/tests/test_sync_idempotent.py` names it in its docstring; its behaviour was
  rewritten from mechanism ("`sync_from_trello` returns without calling `_save_list`") into
  observable terms, and the bound test and rubric were retained. It is the corpus's only
  bound test.
- Five `collections/*` specs were deleted rather than rewritten because their subject moved
  to the new `items` and `naming` features (`add-item`, `remove-item`, `move-items`,
  `set-aliases`, `show-list`). Two `trello-cards` specs were deleted as too coarse to be
  checkable (`annotate-card`, `manage-card` each covered four unrelated operations).
- Nothing in the corpus asserts findings #1, #2 or #3 as intent: the cross-off/archive spec
  is written for the standalone case, cross-board moves are not specced, and
  `write-through-on-add` states the silent half-success plainly with a note saying it is
  current behaviour rather than a goal.
- No spec references the declared-but-unemitted events (#13), the board `list_aliases` map
  (#6) or `default_list` (#7), since none of them is observable on a real install.
