# Findings — To-Do app (`apps/todo/`)

Survey only. No code, test, or migration was modified. Where I am unsure I say so.

---

## A. User-visible defects

### A1. The "clear" links under the completed sections never clear anything — and one of them moves older completions back into "Completed Today"

`apps/todo/ui/TodoApp.jsx::TodoColumn.handleClearCompleted` sends
`DELETE /api/apps/lists/{list_id}/items/{item_id}` for each already-completed item. That route
(`agent.py::api_remove_list_item` -> `apps/lists/store.py::remove_item`) only sets
`archived = true, archived_at = now()`. For an item that is already archived this is a no-op **except**
that it refreshes `archived_at` to the current moment. So:

- "clear" under *Completed Today* leaves the items exactly where they were;
- "clear" under *Recently (N)* re-stamps those items as completed today, i.e. it **moves them into
  "Completed Today"** — the opposite of clearing.

A hard-delete path exists and is unused: `apps/lists/data.py::remove_item` (a real `DELETE`).
Expected: clearing removes the completed items from the person's view.

### A2. "Remove" does not remove — it records the item as completed

`TodoColumn.handleRemove` (the red X on the row) and the red "Remove" entry on the context menu call
the same endpoint as the check-off circle (`handleCheckOff`); the only difference is a 400 ms
animation. An item a person discards therefore reappears under "Completed Today" as though they had
done it, and the entity-change/activity log records it identically. Expected: a discard
distinguishable from a completion (delete, or an abandoned marker).

### A3. `get_todo_list`'s completed-item footer is unreachable

`apps/todo/tools.py::get_todo_list` calls `get_todo_items(uid)` **without** `include_archived=True`,
so `result["items"]` never contains an archived item. The `archived = [...]` branch and the
`"N completed items"` footer are dead code. Either request archived items or drop the branch.

### A4. Clearing the To-Do list choice in Settings silently provisions a new list and orphans the old one

`SettingsPanel.handleSave` sends `default_list_id: selectedList || null`; `default_list_id` is in
`apps/todo/data.py::upsert_config`'s `nullable` set, so choosing "— Select a list —" writes NULL. The
next `GET /config` or `GET /items` calls `ensure_default_list`, which creates a fresh
`"<Name>'s To-Do"` and points at it. The backlog side has `backlog_bootstrapped` (ev-84) precisely so
a deliberate disconnect is respected; the to-do side has no equivalent. A person who clears the
picker to "start over" ends up with a second empty list, their items reachable only through the Lists
app. Expected: respect the disconnect, or do not offer the empty option for the to-do side.

### A5. Every failed board action fails silently

Each `fetch` in `TodoApp.jsx` is wrapped in `try { ... } catch {}` with an empty handler, and only the
add path checks `res.ok`. A refused check-off, edit, reorder, or cross-list move (400/404/500) just
triggers a reload with no message. The clearest case: adding to the backlog column when the person has
deliberately disconnected their backlog returns 400 ("No backlog list configured") and the board shows
nothing at all.

### A6. `handlePrint` builds HTML by string interpolation, unescaped

`TodoColumn.handlePrint` pushes `${item.text}` and `${listName}` straight into a document it then
`document.write`s. Item text containing markup breaks or executes in the print window. The text is
household-authored, but Trello-synced card titles also arrive through this path. Separately,
`window.open("", "_blank")` returns `null` when a popup blocker intervenes and the next line throws an
unhandled `TypeError`, so the print button appears inert.

---

## B. Authorization and privacy

### B1. IDOR — the item-level operations the To-Do board relies on are not scoped to a person

Every **todo-owned** route applies `app_platform/auth.py::scope_user` (`agent.py:3203-3434`), so
config, items, backlog, move, reorder and the list picker are correctly self-or-parent/admin. But the
board performs check-off, remove, wording edits and single-item repositioning against the **Lists**
routes — `agent.py::api_remove_list_item`, `api_update_list_item`, `api_reorder_list_item` — which take
no user argument and perform no ownership check. Authentication is global (`agent.py::auth_gate`), so
this is not anonymous, but **any signed-in household member, including a child, who has a list id and
an item id can complete, reword, reposition or archive another person's to-do items.** The ids are not
secret: the board prints `{listId}` in its own column footer and `get_todo_list` prints "List ID:" into
chat (see B3). Expected: the same ownership check the todo routes apply.

### B2. `PUT /api/apps/todo/config` accepts any list id, unvalidated

`agent.py::api_update_todo_config` -> `apps/todo/data.py::upsert_config` writes `default_list_id` /
`backlog_list_id` with no check that the list exists or that the target person owns it. A person can
point their to-do at another member's list and then read and modify it through the To-Do board, which
never shows whose list it is. `GET /api/apps/todo/lists` does filter to the caller's own lists, so the
UI does not expose this — the API does. (A non-existent id is self-healing: the next
`ensure_default_list` replaces it, which is A4 again.)

### B3. `get_todo_list` prints an internal list id into chat

`apps/todo/tools.py::get_todo_list` appends `"List ID: l-xxxxxxxx"` to its reply. The platform
elsewhere treats internal ids as something to keep out of user-facing text (cf.
`notifications.delivery.phone-push-hides-internal-ids`), and it hands out exactly the identifier B1
needs.

### B4. Config writes are not validated, so bad input is a 500 rather than a 400

`api_update_todo_config` does not check `nudge_day` against the seven allowed values or `nudge_time`
against `HH:MM`. An unrecognised day violates `todo_config_nudge_day_check` and an unparsable time
fails the `time` cast — both surface as an unhandled 500. The UI can only send valid values, so this is
API-only. (Note the inconsistency with `todo_nudge_notifier`, which swallows an unparsable `nudge_time`
and nudges anyway.)

---

## C. Declarations nothing honours, and dead code

### C1. The manifest declares four events; nothing emits any of them

`apps/todo/manifest.yaml` `emits: [todo.config.updated, todo.default_list_changed,
todo.backlog_list_changed, todo.nudge_sent]`. A repo-wide grep for each name finds only the manifest.
`handlers.py` is an empty scaffold and `subscribes: []`. Either emit them or drop the declaration — as
it stands another app could subscribe and never hear anything.

### C2. The manifest's four `config:` keys are unreachable

`todo_nudge_notifier._wn_default` consults `weekly_nudge_enabled` / `weekly_nudge_day` /
`weekly_nudge_time` (scope `app:todo`) **only** when the per-user value is `None`. The `todo_config`
columns are `NOT NULL` with defaults and `apps/todo/data.py::_config_row` coerces every one of them,
and every person gets a config row on first open. So the app-level defaults can never apply.
`show_on_calendar` in the manifest is read by nothing at all — `data_layer/calendar.py` reads the
per-user column. The Settings-app cog form for To-Do therefore has no effect.

### C3. `apps/todo/routes.py` is an empty router

All eight endpoints still live in `agent.py:3203-3434`, contradicting the file's own docstring ("will
move here in a follow-up extraction sub-chunk"). The empty `APIRouter` is mounted by the loader.

### C4. `apps/todo/data.py::delete_config` has no callers

Documented as "Used by user cleanup flows"; nothing in the repo calls it. A departed member's
`todo_config` row therefore survives. Harmless for the nudge
(`apps/notifications/store.py::create_notification` drops unknown recipients), but
`data_layer/calendar.py::_events_from_todo` iterates `get_all_configs()` with **no** check that the
person still exists, so a departed member's to-do block can still be produced for a household-wide
calendar query. Not confirmed against a live install.

---

## D. Stale documentation (not rewritten — flagged only)

### D1. `apps/todo/specs/SPEC.md` has drifted in five places

- the `todo_config` table listing omits `backlog_bootstrapped` (added by migration 003);
- "Tools" lists three tools and omits `get_backlog_list`;
- "Migration Notes" states "No `migrations/002` — fresh installs use only `001_initial.sql`", while
  `002_dedupe_default_lists.sql` and `003_backlog_bootstrapped.sql` both exist and run;
- the UI section describes "default list at top + optional backlog below" with "swipe-to-archive" — it
  is two side-by-side columns and there is no swipe gesture anywhere in `TodoApp.jsx`;
- "Optional Dependencies" says the nudge fires from "a cron entry" through
  `platform.notifications.create_notification`; it is a ~30 s poll owned by the reminders scheduler
  (see E1).

### D2. `apps/todo/migrations/README.md` repeats the "No `002` migration" claim

and lists neither 002 nor 003.

### D3. Two of the three deleted spec records were unverifiable as written

`specs/default-list/idempotent-bootstrap.yaml` carried `verified: true` with `tests: []`, which the §4
loader rejects outright ("marked verified but has no bound tests"). `specs/backlog-list/...` wrote its
`implements` as prose (`apps/todo/data.py (claim_backlog_list; backlog_bootstrapped in the ...)`), so
drift detection could never resolve a path or symbol from it. Both have been rewritten; `specs/list/*`
(three one-line tautologies) was replaced.

---

## E. Ownership and topology

### E1. The only proactive behaviour the app has lives outside the app, owned by another app's loop

`todo_nudge_notifier.py` sits at the repo root and is invoked from `apps/reminders/scheduler.py`
(~line 122) on the ~30 s reminder sweep. The todo manifest declares `job_types: []` and `thinking: []`,
and `handlers.py` says the nudge is "installed by the platform's scheduler". Consequences: disabling
the To-Do app does not stop its nudge, and the nudge is invisible to anything that reads the app
package. Also `todo_nudge_notifier._has_nudge_today` raw-SQLs `app_notifications.notifications`
directly instead of going through `app_platform.notifications` — exactly the cross-schema reach the
todo app is otherwise careful to avoid.

### E2. The nudge hard-codes Discord, contradicting the operator's decided surface routing

`check_todo_nudges` sets `channel = "both" if is_pushover_user(user_id) else "discord"`. Per the
operator's standing facts, surface routing is **per-user** (the web console always receives; Discord is
additive — that person's primary surface, or active there in the last 15 minutes). Naming Discord for
everybody is not intent, so it is not written up as a spec.

### E3. The nudge inherits the `delivered` open question

It is recorded `delivered=False` and nothing retries. The once-per-day dedup keys on a `todo_nudge` row
*existing* for that person today, so a nudge that was recorded but never actually delivered blocks any
further attempt that day. Not written up as intent.

### E4. Three undeclared inbound dependencies on the todo app

- `apps/prioritize/manifest.yaml` declares `platform_deps: [... todo]`, but there is no
  `app_platform/todo.py` shim — the dep name resolves to nothing — while `app_deps: []` and
  `apps/prioritize/data.py` imports `apps.todo.store` directly (`_backlog_todo`, `_source_is_active`).
- `data_layer/calendar.py::_events_from_todo` imports `apps.todo.data` / `apps.todo.store`.
- `todo_nudge_notifier.py` likewise.

So the declared dependency graph the loader can see does not describe who actually depends on todo.

### E5. Overlapping ownership: todo / chores / goals / prioritize (the boundary is prose only)

The intended split is stated only in `help.md`, `guide.md` and each manifest's
`tool_category.description` — nothing in code enforces it. As read from the code the intent is:
**To-Do** = one low-ceremony personal list per person; **Chores** = recurring rotating kid duties (its
own `kids` / `zones` / `chores` / `chore_completions` tables, daily 9 am push); **Goals** =
goal->project->task with assignees and due dates; **Prioritize** = focus slots and ranking over *other*
apps' items. Where that breaks down:

**(a) "my backlog" is claimed by two apps, in contradictory instructions inside the same prompt.**
`apps/todo/tools.py::get_backlog_list`'s docstring is emphatic: *"RESERVED REFERENCE: 'my backlog' (and
an unqualified 'backlog') ALWAYS means the speaking user's own to-do-app backlog. Use THIS tool for
it"*, and `guide.md` repeats it. `chat_domain.py::_build_system_prompt` (~line 664) instructs the
opposite: `"'show my backlog' -> open_app(app_type='prioritize') AND get_backlog_summary(user)"`. Which
one wins is left to the model. **This is the one boundary I would resolve first.**

**(b) The word means two different things to a person.** Prioritize's "backlog" is an aggregate of
goals + reminders + schedules + to-do items (`apps/prioritize/data.py:213`); To-Do's "backlog" is a
literal second list of someday items. Both are user-facing.

**(c) To-Do's keyword routing claims `my list`.** `manifest.yaml` `tool_category.keywords` includes
`my list`, which collides with the Lists app's named lists ("add it to the shopping list"). Only prose
keeps a named-list request out of the todo tools.

**(d) To-Do owns no data, so two apps mutate the same rows.** `entity_types: []`; a to-do item *is* an
`app_lists.list_items` row. Editing or archiving it in the Lists app changes the to-do silently, and a
Trello sync (`apps/lists/data.py::replace_items`) can replace a list's items wholesale underneath the
to-do board. Nothing on the Lists side marks a list as somebody's to-do (deferred per the ev-62
notes), so the Lists UI happily offers to delete it.

**(e) Nothing in code distinguishes "a task" from "a to-do".** `add_todo_item` and the Goals task tools
are both plausible answers to "I need to do X"; the only rule is `guide.md`'s prose. Same for "a chore
I have to do today".

---

## F. Smaller observations

- **F1.** `apps/lists/data.py::batch_reorder` renumbers only the ids it is handed (the active items),
  leaving completed items on their old `position` values, so positions collide after a drag. Harmless
  today because the UI splits active/completed itself; any consumer trusting `ORDER BY position` over a
  mixed set gets an arbitrary interleave.
- **F2.** Every capture rewrites the whole list: `apps/lists/store.py::add_item` -> `_save_list` ->
  `apps/lists/data.py::replace_items`, which `DELETE`s and re-`INSERT`s every row. Ids are preserved
  and `archived_at` round-trips (`item.get("archived_at") or None`), so no data is lost, but it is
  O(list) writes per added item and it bypasses the lists data layer's per-item `digest_record`.
- **F3.** Consequence of F2: **an item captured on the board is not remembered; one captured in chat
  is.** `apps/todo/tools.py::add_todo_item` calls `digest_record` explicitly; the board path
  (`agent.py::api_add_todo_item`) does not. Completion has the same asymmetry — the chat tool digests,
  the board's check-off does not. Skipper's recall of a person's to-dos depends on where they typed
  them. This looks unintended.
- **F4.** `mark_todo_done` calls `apps.lists.data.archive_item` (data layer) rather than
  `apps.lists.store.remove_item`, which is why the Trello card close had to be re-implemented inside
  the tool — the store path already does it. The direct call also skips the `removed_item`
  entity-change log. It also imports the private `trello_client._board_request`.
- **F5.** `data_layer/calendar.py::_events_from_todo` places the weekly block on a person's `nudge_day`
  **even when `nudge_enabled` is false**, so somebody who switched the nudge off still gets a weekly
  "to-do day" on their calendar. The setting label ("Show to-do block on my nudge day") arguably covers
  it; flagging as probably unintended.
- **F6.** `apps/todo/data.py::claim_default_list` can raise a bare
  `RuntimeError("... is contended; retry")` that nothing catches, so a contended bootstrap returns 500
  to the board. The deleted ev-62 spec's notes recorded this (pool exhaustion under a synthetic 10-way
  same-user burst) as a known limitation; recorded here so it does not vanish with the note.
- **F7.** `get_todo_list` builds its empty-list message with an f-string that has no placeholders.
- **F8.** `TodoApp` accepts `context` and `isActive` props and uses neither.
- **F9.** Test coverage: one test file for the whole app,
  `tests/evolve/todo/test_backlog_bootstrap.py`, bound to the backlog bootstrap spec. Every other spec
  in the rewritten corpus is untested. No test is bound to a spec id absent from the corpus.
