# Findings — finder

Survey only; nothing fixed. Corpus 3 → 39 records. Finder reaches into every app, so it accumulates their
drift — most of what follows is other apps' breakage made visible here.

**1. The "Items" source queries an app that does not own the data.** `ui/FinderApp.jsx` (~137) fetches
`/api/apps/home?q=…` for **locator** items, and its `loc-` id lookup (~244) fetches
`/api/apps/home/{id}`. `apps/home/routes.py` has neither a root `GET ""` nor a bare `/{id}`. Correct
endpoints are `/api/apps/locator?q=` and `/api/apps/locator/{id}` — both already return shapes matching
Finder's mappers exactly, so this is a straight route swap. **Cross-app search has never found a located
item.**

**2. Ideas are registered under a prefix that does not exist.** `FinderApp.jsx:238` registers brainstorming
under `bi-`; real idea ids are `bs-{hex8}`. Pasting a real idea id resolves nothing.

**3. The schedules deep link goes nowhere.** `FinderApp.jsx:127` (and the `sch-` lookup at 236) open
`onOpenApp("schedules", { scheduleId: s.id })`, but `SchedulesApp.jsx` never reads `context` — the click
lands on the list.

**4. Missing records answer HTTP 200, so Finder renders phantom results.** Finder's only existence check is
`res.ok`, and these "not found" paths never produce a non-2xx:
- `agent.py::goal_detail`, `::task_detail`, `::project_detail`, `::api_get_document` —
  `return {"error": …}, 404`, which FastAPI encodes as a **200** with an array body. Finder then reads
  `.id`/`.name` off an array → `undefined` → **a clickable card with a blank title that opens the Goals app
  at nothing.**
- `agent.py::api_get_schedule` → 200 `{"error": "Schedule X not found"}` → a card titled `undefined`.
- `apps/issues/routes.py::api_get_issue` → 200 → a card subtitled "undefined · undefined".

Expected: a 404, as `api_get_idea` and `apps/locator/routes.py::api_get_located_item` already do — then
Finder's existing guard reports "No results".

**5. Any unknown `/api/...` path returns the SPA shell with 200, not 404.** `agent.py::spa_fallback`
(`@app.get("/{filename:path}")`) is moved to the end of the route table at startup and catches everything
unmatched, **including `/api/...`**. So `res.ok` is not a valid existence test anywhere in the UI.
Consequence for §1: the bad locator request returns *HTML* with 200, `res.json()` throws,
`Promise.allSettled` swallows the rejection, and the Items category is permanently empty with nothing
logged or shown.

**6. Ordinary text starting with `t-`, `p-`, `g-`, `d-` is hijacked into an id lookup.**
`detectIdLookup` matches on prefix and length only, so `"t-shirt"` → `GET /api/apps/goals/tasks/t-shirt` →
(per §4) a phantom blank card instead of a text search. Same for `"p-trap"`, `"d-day"`, `"g-force"`.

**7. Most ids Finder prints cannot be pasted back in.** Every result row displays its id, but
`ID_PREFIXES` covers only `g- p- t- d- sch- bi-(wrong) loc-(broken) iss-`. Not covered: recipes (`re-`),
vehicles (`veh-`), reminders (`r-`), to-do items, schedule events (`sc-`), locator sub-locations (`iloc-`).

**8. Vehicle results are titled from a field that does not exist.** The auto source (~161) uses
`v.nickname || \`${v.year} ${v.make} ${v.model}\``; `data_layer/auto.py::_vehicle_row` returns no
`nickname` — it returns `name`. So the fallback always runs, and a vehicle with no year renders literally
`"null Toyota Camry"`. The tab title passed on open is `v.nickname || v.make` → the bare make.

**9. The Documents source returns results for queries that match nothing — the biggest search-quality
problem here.** `apps/documents/data.py::search_documents_hybrid` has **no relevance floor**: the semantic
arm takes the top `max_results*3` rows by cosine distance regardless of similarity, and when nothing scores
it explicitly falls back to "most recently updated documents". `store.py::search_docs` calls it with
`max_results=30` and the default `search_hybrid_weight` is `0.5`, so the semantic arm is always on. In
practice Finder's Documents section is populated for almost any 2-character query, with up to 30 unrelated
documents that look identical to real hits.

**10. Choosing a category does not re-run the current search.** `setActiveFilter` only sets state;
`runSearch` is invoked from `handleChange`. With results on screen, clicking a category leaves the old
results in place until another character is typed.

**11. "Search all categories instead" repeats the narrow search.** `FinderApp.jsx:411`:
`onClick={() => { setActiveFilter("all"); setTimeout(() => runSearch(query), 50); }}`. `runSearch` is a
`useCallback` whose deps include `activeFilter`; the closure this handler captured still carries the **old**
filter, and 50 ms is not a re-render guarantee anyway. The button re-runs the identical narrowed search and
reports "no results" again.

**12. `iss-` results are inert and mislabelled.** The issues entry in `ID_PREFIXES` sets `open: () => {}`,
so clicking does nothing although an issues UI is registered. Because `issues` is not in `SEARCH_SOURCES`,
the result renders through the `extraKeys` path with the raw key `"issues"` as its heading. Issues are also
unreachable by text search — `api_list_issues` takes only `status`/`reported_by`, no `q`.

**13. Reminder and to-do results drop the record on click.** `open: (onOpenApp) => onOpenApp("reminders")`
and `onOpenApp("todo")` pass no context, so you land on the default view and have to find the row again.
`RemindersApp` does read `context.tab`, so at minimum the right tab could be selected.

**14. Category bubbles are hardcoded regardless of what is installed.** `SEARCH_SOURCES` is a static array
of ten; nothing consults the app registry or `GET /api/apps/disabled`. On an install without Recipes, Auto,
Locator or Brainstorming (none are in `REQUIRED_APPS`), Finder still offers those categories, still fires
their requests on every search, and each yields a permanent "No results".

**15. A failing source is indistinguishable from an empty one.** `runSearch` drops non-ok responses and
rejected promises alike, and there is no per-source error state. "The Documents app is down" and "no
documents match" look identical. Worse, the whole fan-out is wrapped in `catch { setResults({}) }`, so an
exception thrown while mapping *any* single source is presented as "No results for …" — **a wrong answer
rather than an error.**

**16. Three sources have no server-side search and download everything per search.** Reminders, schedules
and to-do return the full list, which Finder filters in the browser and truncates to 10. On a household
with a long schedule list this re-transfers the whole list on every debounced search, and those three match
one field each while the server-backed sources match much more.

**17. Per-app result caps are inconsistent.** Reminders/schedules/to-do/vehicles: 10 (client-side). Goals:
30. Documents: 30. Recipes, located items and ideas: **uncapped** — a two-character query can return every
recipe in the household and push everything else off the screen.

**18. `context` is accepted and never read.** `FinderApp({ appId, userId, context = {}, … })` destructures
it and no code uses it, so `open_app(app_type="finder", …)` can only open an empty search box — **Skipper
cannot hand Finder a query to run.** Same class as §3.

**19. Ideas of every status are returned.** `api_list_ideas` → `list_ideas` with `status=""` returns parked
and graduated ideas alongside live ones, whereas the reminders/schedules/to-do sources deliberately exclude
cancelled/paused/archived. Ideas also match on `title`/`summary` only, not on their parts' content.

**20. `help.md` promises a chat path Finder does not provide** — "you can also just ask Skipper 'find
anything about the beach trip' — same idea, conversationally". `manifest.yaml` declares
`tool_category: ~`, there is no `tools.py`, and there is no cross-app search tool anywhere.

**21. `specs/SPEC.md` duplicates the endpoint list** that `FinderApp.jsx` already carries — and,
unsurprisingly, does not mention the locator/home mistake.

## Verified clean

`manifest.yaml`'s `entity_types: []`, `emits: []`, `subscribes: []`, `job_types: []`, `config: []` and
`platform_deps: []` are all accurate — Finder really does own no schema, tables, migrations, routes, tools
or events. `core: true` matches `REQUIRED_APPS` and `uninstall_app` blocks removal. Per-user scoping on the
two personal sources is enforced server-side by `scope_user` (403 on another user's data), and Finder
always passes the signed-in user.
