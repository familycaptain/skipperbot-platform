# Findings — folders

Survey only; nothing fixed. Corpus 13 → 58 records.

## Data loss / correctness

1. **`store.py::move_item` loses the item when the destination is bad.** It calls
   `remove_item(from_folder, entity_id)` first, deletes the source folder's knowledge, and only then
   calls `add_item(to_folder, …)`. `add_item` never checks the destination exists (the FK violation is
   swallowed by a bare `except Exception: return None`), so a mistyped destination leaves the item filed
   **nowhere**, its extracted knowledge deleted, returning only "Error: Could not add …". Reachable from
   chat (`move_to_folder`); the REST layer has no move endpoint. Expected: validate the destination
   first, or do remove+add in one transaction.

2. **`data.py::get_content_hash` is not folder-scoped — an item in two folders is only ever indexed
   once.** It selects the most recent `content_hash` for an `entity_id` across *all* folders, and
   `intelligence.py::process_folder_item` then returns `skipped:unchanged`. Consequences:
   filing the same document into a second folder produces **zero** `folder_knowledge` rows for it, so
   searching inside that folder returns nothing; `reprocess_folder_item` refreshes only whichever
   folder is processed first, leaving every other folder holding **stale facts from the old version**
   indefinitely; and because `process_folder_item` *deletes* the folder-scoped rows before the hash
   check can help, a same-folder "move" (`from == to`) **permanently destroys that folder's knowledge**
   for the item. Expected: scope the hash to `(entity_id, folder_id)`, and delete only after deciding to
   re-process.

3. **Nothing cleans up after the owning app deletes an item.** `apps/documents/store.py::delete_doc`
   hard-deletes the row and calls `delete_links_for_entity`, but never touches `app_folders.folder_items`
   or `folder_knowledge`; `data_layer/artifacts.py::delete_artifact` is the same. There is no FK
   (cross-schema FKs are forbidden) and no event subscription (`subscribes: []`). Results: a dangling
   `folder_items` row shows as a bare id with no title while `get_item_count` still counts it — and
   **the deleted document's extracted facts stay in `folder_knowledge` and keep being injected into
   every user's chat prompt** via `chat_domain.py` → `get_relevant_folder_knowledge`. Skipper keeps
   confidently answering from a document the user deleted. **Most serious finding in the app.** Note
   `data.py::delete_knowledge_for_entity(entity_id)` — the unscoped branch that would do exactly this —
   has **no callers**.

4. **Restoring a soft-deleted child of a later-deleted parent orphans it invisibly.**
   `delete_folder` promotes children with `WHERE parent_folder_id = %s AND deleted_at IS NULL`, so an
   already-soft-deleted child keeps pointing at the now-deleted parent. `restore_folder` clears only its
   own `deleted_at`, so the restored folder appears in neither the root list nor any reachable parent's
   children. Live and unreachable.

5. **No cycle guard when re-parenting.** `PATCH /api/apps/folders/{id}` passes `parent_folder_id`
   straight to `update_folder`, whose `allowed` set includes it. A folder can be made its own parent or
   the child of its own descendant. `get_breadcrumbs` has a `seen` guard so it will not hang, but the
   subtree vanishes from the root listing permanently.

6. **Renaming bypasses the sibling-uniqueness rule that creating enforces.** `create_folder` raises
   `ValueError` on a duplicate name at the same level; `update_folder` performs no such check, so a
   rename or re-parent can produce two identically named siblings. Separately the duplicate check filters
   `deleted_at IS NULL`, so a name can be reused while the original is soft-deleted and **restoring the
   original then yields two identical siblings.**

7. **`tools.py::create_folder` only catches `ValueError`.** A non-existent `parent_folder_id` trips the
   FK inside `create_folder`, which raises a psycopg error — so the chat tool raises instead of returning
   a message, and `api_create_folder` (which only maps `ValueError` → 409) 500s.

8. **`data.py::add_item` validates nothing.** No check that `entity_id` is non-empty, resolves to a real
   record, or has a prefix Folders can read. So a folder can hold `"banana"`, `""`, or **its own id**
   (`_entity_type_from_id` only knows `d-` and `a-`). Each such row also spawns a `folder_intelligence`
   job that fails with "No content found for <id>" — the dispatcher's retry policy was not traced, so
   whether that failure repeats is uncertain.

## Stale link-registry state

9. **`store.py::remove_item` and `::move_item` never delete the link edge they created.** `add_item`
   calls `ensure_edge(folder_id, entity_id, "contains", "filed_in")`, but removal deletes only the
   `folder_items` row and the knowledge rows. Stale edges accumulate for every removal and every move
   (the move also leaves the source edge in place while adding the destination edge).

10. **`store.py::delete_folder` calls `delete_links_for_entity(folder_id)` and `restore_folder`
    recreates nothing.** A restored folder loses its `child_of`/`parent_of` edge to its parent, its
    anchor edge, and every `contains` edge — even though the `folder_items` rows survive. It looks right
    in the app and is wrong in the link graph.

11. **`store.py::move_item` skips the changelog.** `add_item` and `remove_item` both call
    `log_entity_change`; `move_item` calls the data layer directly and logs only to the Python logger, so
    a move never reaches Skipper's memory. Related: `tools.py` digests on create/delete but the REST
    routes do not, so a folder made in the web console gets a weaker memory trace than the same folder
    made by chat, and `restore_folder` digests nothing at all.

## Routes, dead code, drift

12. **`apps/folders/routes.py` is an empty `APIRouter()`.** Every endpoint lives in `agent.py`
    (3964–4078), contradicting its own docstring and the app-package pattern.

13. **`specs/SPEC.md` §Routes describes an API that does not exist.** Claimed vs. actual:
    `GET /list?owner=&include_deleted=` (actual `GET /` with `owner`/`root_only`; **no**
    `include_deleted`), `PUT /{id}` (actual `PATCH`), `POST /{id}/restore` (**does not exist**),
    `POST /move-item` (**does not exist**), `POST /{id}/reorder` (actual `PUT`), and `POST /search`
    searching "folders + folder_knowledge" (actual `GET /search?q=`, name/description only). Undocumented
    but real: `GET /tree`, `GET /containing/{entity_id}`, `POST /{id}/new-doc`.

14. **The UI's "Search documents to add" calls a route that does not exist.**
    `FolderDetailApp.jsx::AddDocForm.handleSearch` fetches `/api/docs?q=…`; the real endpoint is
    `/api/apps/documents/search`, and there is no `/api/docs` anywhere. The `catch {}` and `res.ok` guard
    mean the search silently returns nothing every time — the user must paste a raw id.

15. **No restore path outside chat.** There is no `POST /{id}/restore` route and
    `GET /api/apps/folders` cannot list deleted folders, so a folder deleted in the web console is
    unreachable from it forever. Nothing ever purges `deleted_at` rows, so they accumulate permanently
    and invisibly.

16. **The reorder API is unreachable and its effect invisible.** `PUT /{id}/reorder` has no caller in the
    UI or chat, and `FolderDetailApp.jsx` sorts both subfolders and items alphabetically in JS, ignoring
    `position` and `sort_order` entirely. Both columns are written and never observable.

17. **`GET /tree` (`store.py::get_full_tree`) and `GET /containing/{entity_id}` have no callers.**

18. **`store.py::ensure_folder_for_entity` has no callers,** nor does `get_folder_by_related_entity`
    outside it. `SPEC.md` says "Used by other apps (e.g. Research)" — there is no Research app. It is also
    unsafe as written: `related_entity_id` has no unique constraint, so `fetch_one_in_schema` returns an
    arbitrary one of several matches.

19. **`intelligence.py::reprocess_folder_item` has no callers** — the Documents hook submits one job per
    folder instead — yet it is exported on the platform shim as if it were the entry point.

20. **`manifest.yaml` declares 9 events that nothing emits** (`folder.created/updated/deleted/restored/
    item_added/item_removed/item_moved/reorganized/knowledge_updated`); grep finds nothing but the
    manifest and `SPEC.md`. `platform_deps` also lists `events`, unused.

21. **`manifest.yaml` declares a dead config key.** `intelligence_extraction_model` (default
    `"gpt-5-mini"`) is settable in Settings → Folders and read by nothing: `_extract_facts` calls
    `chat_completion(tier="fast")`, and the file's own comment says the per-app override was retired.
    `facts_per_chunk` is live and correctly read.

22. **`platform_deps: [capabilities]` and `SPEC.md`'s "`is_enabled('openai')` gates intelligence" are
    false.** No folders module references capabilities. With no embedding provider configured,
    `_get_embedding` raises per chunk and per fact and each failure is caught individually — so filing
    succeeds and the item is **silently unindexed** rather than reporting that intelligence is
    unavailable.

23. **The migration hardcodes `vector(1536)` while the code reads a provisioned dimension.**
    `001_initial.sql` declares `embedding public.vector(1536)`; `data.py` and `intelligence.py` both
    compute `EMBEDDING_DIM = provisioned_embedding_dim()`. On an install provisioned to any other
    dimension, every `save_knowledge_row` insert fails. `tests/test_embedding_dim_provision.py` only
    static-checks the Python files, so it passes anyway. Separately `data.py`'s `EMBEDDING_DIM` is
    assigned and never used — only the test's source scan depends on it existing.

24. **`SPEC.md`'s "Cross-schema reads" section is fiction.** It claims folders reads `public.users` to
    validate `owner`/`created_by` and `public.entity_types` to resolve labels. Neither happens: `owner` is
    whatever string the caller supplies, lower-cased. A folder can be owned by a person who does not exist.

25. **Nobody's name is ever recorded.** `agent.py` sets `created_by="web"`, `added_by="web"`,
    `deleted_by="web"`, `updated_by="web"`; the MCP tools set `"skipper"`. The auth middleware has already
    attached `request.state.principal` and `require_user`/`scope_user` exist — none of the folders routes
    use them. "Who filed this?" is unanswerable and those columns are effectively constants.

## Authorization

26. **No authorization beyond authentication on any folders surface.** No route calls `require_user`,
    `scope_user` or `resolve_target`; any signed-in principal, including a child account, can read,
    rename, re-parent, file into, unfile from and delete any folder, and `owner` is never consulted on
    any read path. `chat_domain.py` passes no `user_id` to `get_relevant_folder_knowledge`, so facts from
    any folder are injected into every person's prompt. This is likely the operator's intended "no
    secrets" posture (`guide.md`: "All folders are visible to everyone… `owner` is for filtering, not
    access control") and is specced as such — **but `help.md` promises the opposite to the end user**
    ("own privately or share", "share or keep private per folder"). A user who believes a folder is
    private and files medical or financial paperwork into it is materially misled, and folder
    intelligence then surfaces its contents in other members' conversations. That text should be
    corrected.

27. **`data.py::search_folders` passes user input into an `ILIKE` pattern** — bound, so not injectable,
    but `%` and `_` act as wildcards and the tool reports "Found N folder(s) matching '_'".

## Smaller

28. **`search_folders` does not search tags,** despite the tool docstring, the old spec and the
    tool_category keywords. The `tags` column is written, indexed by nothing, matched by nothing.
29. `store.py` imports `create_link` from `link_registry` and never uses it.
30. `data.py::_item_row_raw`'s tuple branch is dead if the connection always uses a dict cursor, and its
    hardcoded column order is a silent hazard if the table gains a column. *Uncertain — `scoped_conn`'s
    cursor factory was not verified.*
31. **`intelligence.py::process_folder_item` stuffs entity ids into the `tags` column.**
    `all_tags = list(set(tags + llm_related + regex_related))` mixes LLM-supplied `related_entities` and
    regex-scraped ids into the same array as real tags, so any consumer treating them as user-facing tags
    shows raw ids.
32. **`guide.md` claims a debounce that does not exist:** "re-processing after a 5-minute debounce".
    `apps/documents/store.py` calls `_trigger_folder_reprocess` on every content update and append,
    submitting one job per containing folder immediately — so every keystroke-save of a filed document
    queues LLM fact extraction, mitigated only by the hash check that finding 2 shows is itself wrong.
33. **The UI swallows every write failure.** `handleRemoveItem`, `handleAddExistingDoc`, `handleSaveEdit`,
    `handleDelete` and `fetchFolders` use bare `catch {}` and mostly ignore non-ok responses (only 409 on
    create is surfaced via `alert`).
34. **`ItemRow`'s `onOpen` only handles `d-` items** — clicking an attachment (`a-`) or any other filed
    entity does nothing at all, with no message.
35. `intelligence.py::_facts_per_chunk` catches only `TypeError`/`ValueError`; anything else from
    `app_platform.settings` propagates and kills extraction for that item, defeating the `default=4`
    fallback.
