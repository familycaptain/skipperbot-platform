# Findings — brainstorming

Survey only; nothing fixed. Corpus 6 → 62 records. The app ships **no Python of its own** —
`apps/brainstorming/` contains only `manifest.yaml`, `help.md`, one migration and two `.jsx` files. Its
data layer is `data_layer/brainstorming.py`, its tools `tools/brainstorming_tool.py`, and its 11 REST
routes live in `agent.py:3475-3568` — `CROSS-CUTTING.md` §8 in its most extreme form: there is not even a
`routes.py` scaffold to mislead you.

## Already known — recorded, not re-derived

**1. Model output is rendered as raw HTML in the main window.** `ui/BrainstormDetailApp.jsx:730` passes
`markdownToHtml(content)` to `dangerouslySetInnerHTML`. The private `markdownToHtml` (756) calls
`escapeHtml` exactly once, on fenced-code-block contents (777); headings, paragraphs, list items, links,
emphasis and table cells are interpolated raw. Document bodies are written by the model
(`revise_idea_document`, `append_to_idea_document`). See `CROSS-CUTTING.md` §4.

## Data loss

**2. A revision longer than the output cap is silently truncated, and Accept saves the truncation.**
`tools/brainstorming_tool.py:459-467` asks the model to "Output the FULL document" with
`max_completion_tokens=8000`. If the document is long enough that the reply is cut off, the tail arrives
as a *deletion* in the diff, `countChanges` reports it as one removal among many, and `handleAcceptEdit`
writes `reviewData.revised` — the truncated text — over the document. Combined with finding 4 (no
history), **the tail is unrecoverable.** Nothing checks the response for a finish reason and nothing
compares lengths.

**3. Partial fence-stripping can leave markup in the document.** `tools/brainstorming_tool.py:471-473`
strips the first and last lines only when `revised` both starts *and* ends with a fence. A reply that
opens with a fence and never closes one keeps the fence in the saved document.

**4. There is no version history and no undo.** `data_layer/brainstorming.py::update_part` increments
`version` and overwrites `content` in place; no prior text is retained anywhere. The counter is reported
to the user ("version 3") and **looks like something that could be restored.**

**5. Closing an idea's window discards unsaved text with no prompt.** `selectPart` guards *tab* switches
with a `confirm()` and `dirty` shows an "unsaved" marker — but the back arrow
(`onOpenApp("brainstorming")`, line 412) and closing the window instance are unguarded. Documents do not
autosave.

## Authorization and attribution

**6. All 11 brainstorming routes are unscoped** (`agent.py:3475-3568`). Only `api_create_idea` touches
identity, and only to stamp `created_by` via `_actor_name` — attribution, not authorization.
`api_get_idea`, `api_update_idea`, `api_delete_idea`, `api_graduate_idea`, `api_add_part`,
`api_update_part`, `api_delete_part` and `api_accept_edit` take a bare id and no `Request`. Any signed-in
member, including a child's account, can read, rewrite or delete any idea.

**7. Three part routes ignore the `idea_id` in their own path.** `api_update_part` (3539),
`api_delete_part` (3549) and `api_accept_edit` (3562) accept `idea_id` and never use it — they call
`update_part(part_id, …)` / `delete_part(part_id)` directly. **A part belonging to idea B is editable and
deletable through idea A's URL.** The path segment reads as a scope and is not one.

**8. `created_by` is a model-supplied argument on the chat path.**
`tools/brainstorming_tool.py::create_idea(… created_by: str = "")`, and
`prompts/guides/brainstorming.md:66` instructs the model to pass it. The REST path does this correctly
(`_actor_name`); the two disagree. See `CROSS-CUTTING.md` §2.

**9. Updates and deletions lose the actor entirely.** `data_layer/brainstorming.py:137` and `:147` call
`digest_record(..., by="")`. Two consequences: `activity.py::log_activity` returns early on an empty `by`,
so **no idea change after creation ever reaches anyone's activity feed**; and the memory written for a
change or deletion has no author.

## Broken paths

**10. Skipper cannot deep-link an idea.** `getOpenableApps` (`web/src/apps/registry.js:129`)
intentionally includes sub-views, so `open_app` advertises `brainstorm` (the idea detail view).
`local_tools.py` forwards the id as `context.entity_id`, and every other detail app has a legacy key
(`recipeId`, `docId`, `folderId`, …). `BrainstormDetailApp.jsx:57` reads `context.ideaId` **and nothing
else** — so `open_app(app_type="brainstorm", entity_id="bs-…")` opens a window rendering "Idea not
found." Expected: add `ideaId`/`entity_id` to the mapping in `local_tools.py`, or read `entity_id` in the
component.

**11. Finder looks up ideas under the wrong prefix.** `apps/finder/ui/FinderApp.jsx:238` registers
`{ prefix: "bi-", key: "brainstorming", … }` then fetches `/api/apps/brainstorming/${id}`. Idea ids are
`bs-{hex8}`. Pasting a real idea id into Finder never resolves by id. (Finder's *text* search of
brainstorming, line 173, works.)

**12. A revision proposed when the idea is not open is lost, while chat reports success.**
`chat_domain.py:398-416` replaces the tool result with `proposal["summary"]` unconditionally, and only
emits the `idea_edit_proposal` websocket event `if req.send_event`. On Discord (`send_event is None`) the
user is told "Proposed 4 addition(s) and 2 deletion(s)" and there is no editor to accept it in. On web
with the idea closed, or open on a different tab, `BrainstormDetailApp.jsx:74-96` drops it on the
`idea_id`/`part_id` guards. **Proposals are not persisted** — there is no pending-proposal list.

**13. After an automatic refresh, the reported active part can be the wrong one.** `loadIdea` (138)
always reports `partId: mainPart?.id` in `onContextChange`, while `documentContent` is the *active* part's
text (134). Sitting on a second document tab when a `brainstorm_updated` refresh fires, Skipper is told
the active part is the main doc and shown another tab's text. A proposal generated from that context
targets the main document and is then rejected by the `part_id` guard — or, if the main doc happens to be
active in another window, **applied to the wrong document.** `selectPart` (164) gets this right; only
`loadIdea` does not.

**14. `api_add_part`'s 404 branch is unreachable; an unknown idea produces a 500.** `agent.py:3528`
checks `if not result` and raises 404, but `add_part` inserts against
`idea_parts.idea_id REFERENCES ideas(id)` first, so an unknown idea raises a foreign-key violation out of
`execute()` before `get_part` is reached.

**15. `delete_part` signals errors as prose, and the route pattern-matches it.** It returns
`"Error: Part not found."` / `"Error: Cannot delete the main document."` / `"Part deleted."`;
`agent.py:3553` does `if "error" in result.lower()` and raises 400. A missing part is therefore a 400, not
a 404, and any future message containing the word "error" becomes a failure.

**16. Accepting a revision emits no refresh event.** `api_accept_edit` writes the part and returns;
nothing sends `brainstorm_updated`, so a second window (or another member) viewing the same idea keeps
showing pre-revision text until manually refreshed. `revise_idea_document` is also — correctly — absent
from `BRAINSTORM_MUTATING_TOOLS` (`chat_domain.py:57`), so the proposal itself triggers no refresh either;
that part looks deliberate.

## Promised vs. running

**17. Graduation promises a Goal and delivers a status label.** `help.md:34-35` — *"graduate the garden
idea into a goal" → it becomes a Goal in the Goals app with its content carried over.*
`api_graduate_idea` and `tools/brainstorming_tool.py::graduate_idea` both do exactly
`update_idea(idea_id, status="graduated")`. **No goal is created, no content is copied, no link is made.**

**18. The `ideas.project_id` column is dead.** Declared in `migrations/001_initial.sql:20` as "FK to
goals if graduated", listed in `update_idea`'s allowed set, returned by `_idea_row` — and never written by
anything in the repo. It is the column the graduation feature was going to use.

**19. `_IDEA_HINT` names a status vocabulary that does not exist.** `data_layer/brainstorming.py:16-19`
tells the memory digester the statuses are `idea/active/on_hold/done/archived`. The real set is
`idea/exploring/developing/parked/graduated` (migration, both UI files, `help.md:54-62`). **Every memory
written about an idea is digested against the wrong vocabulary**, so recall about an idea's stage is being
steered by a stale hint.

**20. The prompt tells the model two opposite things in the same message.** `chat_domain.py:754`
(entity-type branch): *"ALWAYS USE revise_idea_document for ALL document changes… NEVER use… doc tools"*,
with *"append… (avoid)"* and *"update… (avoid)"*. Then `chat_domain.py:828` (document-content branch, same
request, `entity_type == "idea"`): *"actually add it using append_to_idea_document or
update_idea_document"*. Both are appended to the same system prompt. **Which one wins decides whether a
person gets a diff to review or a silent overwrite.**

**21. Statuses and priorities are never validated.** `update_idea` writes whatever string arrives;
`UpdateIdeaRequest` types them as bare `str | None`; the columns are plain `TEXT` with no `CHECK`.
`STATUS_COLORS[idea.status] || STATUS_COLORS.idea` in both `.jsx` files quietly renders an unknown status
as a raw idea. A typo in a chat request (`status="explore"`) is accepted and **makes the idea invisible to
every status tab.**

**22. Rename can blank a title that creation refuses to leave blank.** `create_idea` rejects an empty
title (`tools/brainstorming_tool.py:59`), but `handleUpdateMeta({title: titleDraft})` with an empty draft
sends `{"title": ""}`; `api_update_idea` filters only on `is not None` and `update_idea` only on
`v is not None`. The idea is then listed with no title at all.

**23. Tag case is normalised in one path only.** `BrainstormDetailApp.jsx:217` lower-cases what a person
types; `tools/brainstorming_tool.py:214` and `:62` do not. The tag filter is `%s = ANY(tags)` — exact and
case-sensitive. So `create_idea(tags="Garden")` produces **a tag no UI click can ever match.**

**24. Several fields cannot be cleared through chat.** `update_idea` uses truthiness (`if title:`,
`if summary:`, `if tags:`), so `summary=""` and `tags=""` are dropped as "not provided". "Remove all the
tags from that idea" and "clear the summary" cannot be done in conversation; the app can do both.

**25. Search has no debounce.** `BrainstormListApp.jsx:33-46` — `fetchIdeas` is a `useCallback` keyed on
`searchQuery` and the effect re-runs on every keystroke, so typing "backyard" issues eight
`GET /api/apps/brainstorming` requests, each doing an `ILIKE` scan plus one `COUNT(*)` per row returned
(`list_ideas` calls `_count_parts` per idea — an N+1).

**26. Native blocking dialogs in three places** — `prompt()` for a part title
(`BrainstormDetailApp.jsx:287`), `prompt()` for an edge label (`FlowchartEditor.jsx:267`), `confirm()` in
`selectPart`. The only modal patterns in the app, and suppressible by the browser.

**27. A window-scoped Ctrl+S listener per open idea.** `BrainstormDetailApp.jsx:99-108` registers
`keydown` on `window`, so with three ideas open three listeners each `preventDefault()` and each call
their own `handleSavePart` — including when focus is in the chat box. Only dirty instances actually save,
so benign today, but the browser's Save is captured from anywhere on the page.

## Documentation and coverage

**28. `read_feature_spec` advertises a spec that does not exist.** `local_tools.py:211` lists
`BRAINSTORMING` among available specs; `:456` resolves `specs/BRAINSTORMING.md`, and `specs/` contains no
such file. Asked to announce the app, Skipper's first tool call fails and returns a directory listing.
The same list also names `SCRUM`, `PRIORITIZE` and `INVESTMENT_ANALYST` — not checked.

**29. `help.md` claims filters the list does not have** — "filtered by status, priority, or tags"
(`help.md:16`). The list UI offers status tabs and a text box only; `list_ideas` supports a `tag` filter
no UI ever passes, and there is no priority filter anywhere. `help.md:9` also calls flowcharts "optional"
while `manifest.yaml:4` and the tool docstrings describe image and link parts that have no editor
(`BrainstormDetailApp.jsx:744` — "editor not yet available").

**30. No test anywhere covers brainstorming behaviour.** The only two tests mentioning it are platform
tests that happen to include it in a list: `tests/platform/test_app_help_route.py:37` (bound to
`platform.app-help.route-precedence`) and `tests/providers/test_oneshot_params.py:46`
(`test_brainstorming_sends_temperature`, which asserts the provider shim forwards `temperature=0.7`). All
56 specs carry `tests: []`.

## Fragility worth a decision

**31. The tables live in `public` on purpose, and the reason is a mismatch.**
`migrations/001_initial.sql:1-11` and `manifest.yaml:7-10` both explain that
`data_layer/brainstorming.py` uses **unqualified** table names against the agent DB pool, so `ideas` and
`idea_parts` must be created in `public` rather than in `app_brainstorming` like every other app package.
Two generically-named tables sit in the shared schema; `ensure_edge`'s `links` table and `_type_from_id`
are the only things keeping `bs-`/`bp-` ids distinguishable. **Any future app wanting a table called
`ideas` collides.**

**32. Structural links are written and never read.** `data_layer/brainstorming.py:62` and `:191` call
`ensure_edge(part_id, idea_id, "child_of", "parent_of")` on every part creation. Nothing in the app, its
routes, its tools or its UI ever queries those edges — parts are found by `idea_parts.idea_id`.

**33. Unused surface.** `api_list_ideas` exposes a `user` query parameter that filters by creator; no
caller passes it. `AddPartRequest.content` is never populated by the UI.
`tools/brainstorming_tool.py:17-26` imports `add_part as _add_part` and never uses it — there is no chat
tool for adding a part, so an idea can only grow tabs from the desktop.
