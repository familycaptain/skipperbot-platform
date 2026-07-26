# Findings — prioritize

Survey only; nothing fixed. Corpus 8 → 40 records. No bound tests exist for this app.

## Broken / wrong

1. **`tools.py::_resolve_title` queries tables that do not exist.** For `goal`/`project`/`task` it runs
   `SELECT name FROM public.<goals|projects|tasks>`. Those tables live in `app_goals`; there is no
   `public.goals`/`projects`/`tasks` anywhere in the repo, and `data.py::_source_is_active` correctly
   reads `app_goals.*`. The helper is wrapped in `except Exception: pass` and falls through to
   `return source_id`, so `list_focus` and `get_family_focus` **silently answer with raw ids**
   ("1. [task] t-abc12345") instead of titles. Expected: `apps.goals.data.load_entity`, as
   `agent.py::_resolve_source_item` already does. The module docstring ("Goals/projects/tasks still in
   public.*") is stale for the same reason.

2. **`_resolve_title` has no branch for `schedule`, `todo`, or any registered provider type.** Focus on a
   schedule, to-do item, home task or medication refill is reported in chat by its bare id.
   `register_activity_checker` lets provider apps report staleness, but there is **no matching title
   registry** — an app can put work into the backlog and cannot make it nameable in chat.

3. **`agent.py::_resolve_source_item` also omits `schedule` and every provider type** (`home_task`,
   `med_refill`, `med_treatment`, `med_followup`, `med_lab_missing`, `med_appointment`,
   `med_equip_task`). It returns `{}`, and both `PrioritizeApp.jsx::FocusCard` and the console focus
   strip fall back to `slot.source_id` — so promoting an overdue schedule yields a focus card reading
   `sch-1a2b3c4d`. This is the only enrichment path for `/focus` and `/family`.

4. **The chat backlog summary omits half the backlog.** `tools.py::get_backlog_summary` renders only
   `goals_tree`, `reminders`, `nags`, `auto_issues`. `schedules`, `todo` and every provider key
   (`home_tasks`, `med_*`) are gathered by `get_backlog` and shown in the UI but never printed — so
   "what should I work on?" can answer "no actionable backlog items. Nice work! 🎉" while the app shows a
   dozen overdue schedules. Expected: iterate the result dict, not four hard-coded keys.

5. **`agent.py::api_get_backlog` marks `in_focus` on only five hard-coded keys.** `home_tasks` and every
   `med_*` item never gets the flag, so they render undimmed with a live promote button even when they
   already hold a focus position.

6. **Two shipped backlog providers ignore the person they were asked about.** All six providers in
   `apps/medical/__init__.py` take `user_id` and never use it, calling household-wide reads;
   `apps/home/hooks.py::_home_maintenance_backlog` does the same with `get_due_tasks(days_ahead=7)`. So
   every member's *own* backlog lists every other member's medication refills, lab results and
   appointments, plus all household maintenance. `data.py::register_backlog_provider` documents the
   contract as `fn(user_id) -> list[dict]`, so the defect is provider-side — but Prioritize is the surface
   it shows through, and it directly contradicts `prioritize.backlog.only-your-own-work`. (Adult-to-adult
   visibility is now decided as intended; this is still wrong as "your backlog", and reaches child
   accounts too.)

7. **Failure isolation covers only registered providers, not the built-ins.** `data.py::get_backlog`
   wraps each `_backlog_providers[key]` call in `try/except`, but `_backlog_goals_tree`,
   `_backlog_reminders`, `_backlog_nags` and `_backlog_schedules` are called bare. One raise from the
   goals or schedules read fails the whole aggregate → 500 → `PrioritizeApp.jsx`'s `catch {}` leaves the
   panel reading "Nothing in your backlog. All clear!". Only `_backlog_todo` has its own guard.

8. **`data.py::reorder_focus` can raise a UNIQUE violation on a partial reorder.** It parks listed ids at
   negative slot numbers then renumbers `1..n`, but unlisted ids keep their old numbers. With
   `1=A, 2=B, 3=C`, a call with `["B","C"]` sets B→1 while A still holds 1 →
   `priority_focus_user_id_slot_number_key` violation → 500. The UI always sends every id, but this is a
   documented cross-app contract via `app_platform.prioritize`. It also hard-codes `[:3]`, silently
   discarding the 4th+ id.

9. **`reorder_focus` always returns `True`** — unconditionally, after `conn.commit()`. `api_reorder_focus`
   reports `{"ok": true}` even when no row matched.

10. **`POST /focus` with an explicit `slot_number` bypasses the cap and validates nothing.**
    `api_promote_focus` calls `set_focus` directly, which inserts whatever integer it is given —
    `slot_number: 47` or `-2` both create a focus row outside `1..max`. `slot_number: 0` is falsy, so it
    silently falls through to `promote_to_focus`.

11. **`max_focus_slots` is only half-wired.** `data.py::_max_focus_slots` is consulted by
    `promote_to_focus` alone. Everything else hard-codes 3: `tools.py::promote_focus`, `tools.py::list_focus`
    (`{len(slots)}/3`), `reorder_focus` (`[:3]`), `PrioritizeApp.jsx`, `web/src/components/Shell.jsx`, and
    `apps/goals/pm_runner.py::_append_focus_nags`. Raising the setting to 5 gives an app that lets chat
    pin 5 but shows "3/3", disables its own promote buttons at 3, reorders only 3, and nudges about "-2
    empty slots".

12. **The daily focus nudge silently does not exist without the Scrum app.** `_append_focus_nags` is
    called only from `apps/goals/pm_runner.py::check_and_run_pm`, which returns immediately if
    `import apps.scrum.data` fails. `skipperbot-app-scrum` is optional. On any install without it the
    Prioritize toolbar still shows "Nag on / Nag off", the household view shows a "nag on" badge,
    `help.md` promises "a daily nudge", and `guide.md` tells the agent to point people at the toggle —
    but nothing ever fires. `PM_QUIET_MODE` suppresses it too. Expected: Prioritize owns its own nudge, or
    the toggle is hidden when nothing can deliver it.

13. **The nudge is sent to non-person accounts.** `_append_focus_nags` iterates `get_all_users()`, which
    includes bots — `get_human_users()` exists precisely to exclude them. Skipper's own account receives
    "⭐ **Focus Check** — You haven't set any focus priorities!". Same root cause makes
    `get_family_focus` and `api_get_family_focus` list bot accounts as members.

14. **`GET /family` applies no user scoping.** Every other prioritize endpoint calls `scope_user`; this one
    takes no `Request` and returns every user's slots, enriched titles and nudge state. Auth is still
    required, so this is not unauthenticated — but it is the only prioritize route with no
    `resolve_target` while the rest of the app refuses cross-user reads. The UI implies the household view
    is intentionally open; the asymmetry reads as accidental.

15. **A promote that will not stick still reports success.** `promote_to_focus` inserts before anything
    checks the item exists. With an unrecognised `source_type` or a wrong id, `_source_is_active` returns
    `False`, so `cleanup_stale_focus` — which runs at the top of `list_focus`, `get_family_focus`,
    `api_get_focus` and `api_get_family_focus` — deletes the row on the very next read. Observable:
    "Promoted **t-typo** to focus slot #1 for alice." immediately followed by "alice has no focus items
    set."

16. **`tools.py::promote_focus` reports a promotion when nothing happened.** When the item is already in
    focus, `promote_to_focus` returns the *existing* slot and the tool prints "Promoted X to focus slot
    #2" — indistinguishable from a real promotion.

17. **`_resolve_title` reads the wrong column for vehicle issues** — `description` from
    `app_auto.vehicle_issues`, while `apps/auto/hooks.py`, `apps/auto/data.py::get_issue` and
    `agent.py::_resolve_source_item` all use `title`. A focused vehicle issue is labelled with its long
    description in chat and its title everywhere else.

18. **The console focus strip cannot open half of what it displays.** `Shell.jsx`'s local `openSource`
    handles only `goal`, `project`, `task`, `nag`, `reminder`, `auto_issue`; clicking a focused schedule,
    to-do item, home task or medical item does nothing. `PrioritizeApp.jsx`'s own `openSource` handles
    more, and its `FamilyView.openSource` is a third, shorter copy that drops `todo` and `home_task`.
    **Three divergent copies of one routing table.**

19. **The UI has no group for two registered medical providers.** `apps/medical/__init__.py` registers
    `med_appointments` and `med_equipment`; `FLAT_BACKLOG_GROUPS` lists neither, and
    `SOURCE_LABELS`/`ICONS`/`COLORS` have no entry. Those items are gathered, rendered nowhere, and
    excluded from the "N items" total — yet promotable via the API, after which they render in focus with a
    fallback icon and the raw source_type as their label.

20. **Manifest declares four events that nothing emits** (`prioritize.focus_set / focus_cleared /
    focus_reordered / focus_nag_toggled`). Nothing subscribes either.

21. **Manifest declares an unused `memory` dep, and two documents claim behaviour that does not exist.**
    `SPEC.md`: "Emits … (via `digest_record`)". `help.md`: "Your focus selections are saved and pulled
    into Skipper's memory". No `digest_record` call exists anywhere in the app. Focus changes are invisible
    to memory.

22. **Undeclared app dependency on `lists`.** `data.py::_source_is_active` and
    `agent.py::_resolve_source_item` both import `apps.lists.data.get_item`, but `manifest.yaml` has
    `app_deps: []` and lists `todo` (not `lists`) under `platform_deps`. `_backlog_todo` also imports
    `apps.todo.store` directly rather than through a shim, contradicting the module docstring.

23. **`_backlog_reminders` and `_backlog_nags` each fetch the same rows** — both call
    `get_user_reminders(user_id)` and filter opposite ways. Two identical queries per backlog read, on a
    path the UI polls.

24. **`cleanup_stale_focus` makes reads mutating, and `api_get_family_focus` runs it for every user.** A
    household-view refresh performs N users × M slots of cross-app lookups plus deletes on a polled GET.
    Not incorrect, but unbounded in household size.

## Stale / dead

25. **`apps/prioritize/routes.py` is an empty stub** — an `APIRouter` with no routes, existing only to
    satisfy the loader's `has_routes` check; the real endpoints are in `agent.py`. `handlers.py` is
    likewise comment-only for `has_handlers`. Both are documented as deliberate, which means **those
    loader checks certify nothing.**

26. **Further `SPEC.md` drift:** schedules are said to be read by "a qualified read against
    `app_schedules.schedules`" (they now go through `app_platform.schedules.get_due_schedules`), and
    goals/tasks/users are "still in `public.*`" (true only of `users`).

27. **`help.md` promises drag-and-drop** ("drag/pick items into focus"). There is no drag handling in
    `PrioritizeApp.jsx` — promotion is a button, ordering is four chevrons.

28. **`guide.md` lists a stale `source_type` set** — `goal, project, task, reminder, nag, auto_issue` —
    omitting `schedule`, `todo`, `home_task` and the six `med_*` types the app accepts and displays.

29. **Stale comment in `web/src/apps/emptyStateHero.js`** (~line 69) naming `chores` as excluded; it is no
    longer in `EXCLUDE`.

## Boundary / naming

30. **"My backlog" is claimed by two apps, and the platform prompt routes it to the wrong one.**
    `prompts/BEHAVIOR.md` §"'My to-do' and 'my backlog' are reserved" and `apps/todo/guide.md` both state
    that an unqualified "my backlog" ALWAYS means the To-Do app's backlog list, explicitly saying "not
    Prioritize". `chat_domain.py::_build_system_prompt` contradicts that **in the same assembled prompt**:
    `- 'show my backlog' → open_app(app_type='prioritize') AND get_backlog_summary(user)`. Worse,
    `apps/prioritize/manifest.yaml`'s `tool_category.keywords` claim `backlog`, `show my backlog` and
    `what should I do`, while `apps/todo/manifest.yaml`'s keywords **do not include `backlog` at all** — so
    the keyword router loads Prioritize's tools for that phrasing and `get_backlog_list` may not even be in
    the allowed set for the turn. **The model is instructed to use a tool it has not been given, and
    offered one it has been told not to use.** Expected: drop `backlog`/`show my backlog` from Prioritize's
    keywords, add them to To-Do's, and delete the contradicting line from `chat_domain.py`.

31. **"Ranked list" is a fiction repeated in three places.** `manifest.yaml`, `SPEC.md` and the old
    `_capability.yaml` all describe the result as a "single ranked list". There is no ranking:
    `get_backlog` returns a dict of groups, each in its source app's own order, and the person does the
    ranking by promoting three things. The wording is what keeps sending readers looking for a scorer.

## Small

32. `data.py::set_focus` returns a hand-built dict rather than the inserted row, so `created_at` is absent
    for a freshly promoted item and present for every other.
33. `set_focus` calls `ensure_edge(pf_id, source_id, "pinned_to", "pinned_by")` on every pin. Nothing reads
    those edges, and neither `clear_focus` nor `clear_focus_by_source` removes them — the link graph
    accumulates edges pointing at deleted `pf-` ids indefinitely.
34. `migrations/README.md` and `SPEC.md` reference `private/data_migrations/prioritize/`, outside the public
    repo. Worth confirming it is not load-bearing for a fresh install.
35. `FocusCard` displays `index + 1` while the remove control posts `slot.slot_number`. After clearing slot
    2 of 3 the remaining items display "1, 2" but are stored as 1 and 3, and `promote_to_focus` then fills
    the gap at 2 — so a newly promoted item appears second, not third.
36. `AppPanel.jsx` passes no `refreshKey` for `prioritize` (every other refreshing app gets one), so focus
    set through chat does not update an already-open Prioritize panel. The console focus strip *does*
    update, so the strip and the open app can disagree.
37. `tools.py::list_focus`'s empty state speaks about the person in the third person ("They should pick up
    to 3 priorities!") even when the asker is that person.
38. **No bound tests exist for this app** — no `apps/prioritize/tests/`, and no test references a
    `prioritize.*` spec id.
