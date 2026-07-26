# Findings — locator

Survey only; nothing fixed. Corpus 12 → 51 records. `tests: []` everywhere — no test file anywhere
touches locator (the four `*location*` tests cover the platform geo service, unrelated).

**Answers to the audit probes:** a loose spoken description is matched as **one literal substring**,
not keyword-by-keyword, so multi-word paraphrases fail; **similar names are never disambiguated** —
all matches come back and the person picks, and item names are not unique; **nothing expires or goes
stale** — no re-verify prompt, no confidence decay, `updated_at` is the only age signal. The app stores
objects, not people, so the people-privacy question does not bite — but see finding 1.

## Privacy / access control

1. **No authorization on any route beyond being signed in.** `routes.py` does no role check and no
   per-person scoping: any member — including a child account, and any service-token principal — can
   read, edit and delete every item and every place. `has_any_role` / `scope_user` exist and are used
   elsewhere; locator uses neither. `help.md` actively encourages storing exactly the things this
   matters for: "the passports are in the fireproof box", "the spare key is under the third
   flowerpot". Specced explicitly (`locator.access.the-record-is-the-households`) so it is at least
   visible, but the unguarded model is the most significant finding in the app. Expected: at minimum a
   documented decision; more likely a sensitive-item flag or a role gate on read.
2. **`routes.py::_actor` is used on create only.** Update, delete, location-create and location-delete
   record nothing about who acted and check nothing. `created_by` is preserved, so after someone else
   moves a thing the record still names the original recorder with no trace of the editor. `data.py`'s
   `by=` parameter exists and is never supplied (see 7).
3. **`help.md` privacy claim vs. memory extraction.** It says item data "stays within your household",
   but `data.py::save_item` → `digest_record` enqueues the full record for LLM fact extraction, which
   on a cloud-model install sends item names, locations and notes to a third party. Per the operator's
   PHI ruling that trust decision belongs to the key holder — but the help text must not tell them the
   opposite.
4. **`tools.py::create_located_item` trusts `created_by` from the model,** so an item can be attributed
   to a member who did not record it. The HTTP route correctly overrides the client value.

## Bugs

5. **Skipper's memory is never updated when an item MOVES.** `data.py::update_item` does not call
   `digest_record` — only `save_item` (create) and `delete_item` do. So "the camping gear moved to the
   attic" updates the table and the item page, while Skipper's long-term memory still holds "camping
   gear is in the garage" — and `help.md`'s promise that asking months later works is answered from the
   stale memory. **The sharpest correctness bug in the app: the whole point is the answer being right.**
   Expected: digest the updated record with `action="updated"`, which `digest_record` already supports.
6. **`ui/LocatorDetailApp.jsx::handleSave` cannot clear a field.** Every field is sent as
   `form.x || null` and `routes.py::api_update_located_item` drops `None` as "unchanged". Clearing
   Notes, Description, Category, Sub-location or Location silently restores the old value on next
   load. Same for tags (`length > 0 ? tags : null`) and quantity. Expected: send `""` / `[]` / `0`,
   all of which the route and data layer handle correctly.
7. **`tools.py::update_located_item` cannot express "clear this".** Every text field uses `if name:`
   truthiness, so a blank means unchanged and no value means empty. A person cannot ask Skipper to
   remove a stale note. (Quantity is the exception: `0` clears.) Related asymmetry: unreadable `tags`
   JSON is silently dropped on create but rejects the whole edit on update.
8. **A duplicate location name raises a raw database error.** `data.py::create_location` uses
   `execute_returning_in_schema`, which does not catch `UniqueViolation` from the
   `item_locations.name` UNIQUE constraint — so `tools.py::create_item_location`'s intended
   "may already exist" message is **unreachable** and chat shows
   `duplicate key value violates unique constraint "item_locations_name_key"`.
   `routes.py`'s `HTTPException(400, …)` is likewise unreachable and the request 500s. The pooled
   connection is safe (`get_conn` rolls back). Aggravating: the UI's `handleCreateLocation` ignores the
   response, so the user sees the input clear and nothing happen.
9. **Location uniqueness is case-sensitive; everything consuming locations is not.** The UNIQUE
   constraint is on raw `TEXT`, so "Garage" and "garage" can both exist and both show as filter chips;
   `filter_by_location` uses `ILIKE` so both return the identical set, and `get_all_locations_merged`
   dedupes case-insensitively. Expected: a case-insensitive unique index, or normalise on create.
10. **`routes.py::api_create_located_item` blocks the event loop.** `save_item` is correctly wrapped in
    `asyncio.to_thread`, but the return is `return _dl.get_item(item_id)` — a synchronous DB round trip
    on an async handler. Every other route in the file is consistent.
11. **`data.py::save_item` is an upsert used as an insert.** `ON CONFLICT (id) DO UPDATE` in the create
    path means an id collision silently overwrites an existing item rather than failing. Unlikely with
    8 hex chars, but the failure mode is silent data loss.
12. **`search_items` / `filter_by_location` / `filter_by_category` do not escape LIKE metacharacters.**
    Not injectable (parameterised), but a query containing `%` or `_` acts as a wildcard: searching
    `100%` matches "100" plus anything.

## Dead code / drift

13. **`tools/locator_tool.py` and `data_layer/locator.py` are dead duplicates with wrong signposts.**
    Both are headed "DEPRECATED — Moved to **apps/home**" — wrong, it moved to `apps/locator`. Neither
    is imported, but `tools/locator_tool.py` still imports `data_layer.locator`, which writes to
    **unqualified** `located_items` — i.e. `public.located_items`, a different, empty table. Delete both.
14. **`apps/finder/ui/FinderApp.jsx` queries the wrong app for locator items.** Its "Items" source
    fetches `/api/apps/home?q=…` and its `loc-` lookup fetches `/api/apps/home/{id}`; `apps/home` has
    neither a root list route nor a `/{id}` route. Cross-app search **never finds a located item** and
    pasting a `loc-` handle resolves to nothing. Expected: `/api/apps/locator?q=` and
    `/api/apps/locator/{id}`, both of which exist and return the right shape.
15. **`chat_domain.py:669` still tells the model the Home app has a `locator` tab.** `HomeApp.jsx::TABS`
    is maintenance/issues/appliances/insurance/contractors, so
    `open_app(app_type='home', tab='locator')` silently falls back to maintenance instead of opening
    Locator.
16. **Photos are promised on three surfaces and reachable from none.** `manifest.yaml`, `help.md`
    ("Attach a photo so the item and its spot is unmistakable") and the `images` platform dep all
    advertise photos; the routes (`api_get_item_images`, `api_link_image`, `api_unlink_image`) and data
    layer are fully implemented — but **no UI component and no chat tool calls any of them**. The
    feature exists only for a direct API caller.
17. **`help.md` overstates filtering** — it claims the Items screen can filter by location, category
    or tag; `LocatorListApp.jsx` offers only a location chip bar plus free-text search.
18. **`manifest.yaml` declares `platform_deps: events` and `time`, neither used.** No emit call and no
    time-service call anywhere in the app.
19. **`locator_images` holds a soft reference to `public.images` with no reaper.** Deleting a picture
    leaves a dangling link row; the INNER JOIN just omits it, so rows accumulate invisibly forever.
    Deliberate per the migration comments, but nothing cleans up.
20. **`get_all_locations_merged` synthesises ids of the form `_inline_<name>`,** detected by string
    prefix in one JSX file to hide the delete button. Safe today (real ids are `iloc-…`) but it is an
    unasserted contract between the data layer and one component. Related inconsistency: the app's
    location list includes inline locations while `list_item_locations` shows only defined ones.
21. **Abandoned "New Item" placeholders.** `LocatorListApp.jsx::handleCreateItem` POSTs an item literally
    named "New Item" before the user types anything, so closing the editor without saving leaves a junk
    record — and, because create digests immediately, a junk **memory** too.
22. **Trivial:** unused imports (`Tag` in `LocatorListApp.jsx`; `Plus`, `Tag` in `LocatorDetailApp.jsx`).
    `routes.py::_actor` lowercases the actor while `tools.py::create_located_item` stores the model's
    casing, so "Created by" reads "alice" for app-created items and "Alice" for chat-created ones.
