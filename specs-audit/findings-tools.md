# Findings — tools

Survey only; nothing fixed. Corpus 5 → 39 records. This app is the catalogue of what Skipper can do —
so a listing that disagrees with what the platform actually registers is its central failure mode.

**1. The advertised-spec list is entirely phantom — worse than previously reported.**
`local_tools.py:211` — `read_feature_spec`'s description tells the model "Available specs include: TODO,
RECIPES, SCHEDULES, SCRUM, EMAIL, LISTS, PRIORITIZE, BRAINSTORMING, INVESTMENT_ANALYST, ITEM_LOCATOR,
AUTO_MAINTENANCE, BACKUPS, etc." `specs/` contains **none of them** — it holds only platform docs
(APP_PACKAGES, ARCHITECTURE, CAPABILITIES, CHARTER, CONSCIOUSNESS, ENTITY_TYPES, EVENTS, MEMORY,
MIGRATIONS, MODEL_FLEXIBILITY, ONBOARDING, PLATFORM_SERVICES, README, THINKING). So **all twelve names
fail**, not just BRAINSTORMING, and the handler (`local_tools.py:453-459`) dumps the platform-doc listing
into the model's context. Core, not `apps/tools` — but it is the same "surface advertises an ability that
does not exist" class this app exists to expose.

**2. `read_feature_spec` is cwd-dependent and unguarded.** `local_tools.py:456` uses the relative
`os.path.join("specs", ...)` and `os.listdir("specs")` with no try/except, so a non-repo-root cwd raises
`FileNotFoundError` out of `handle_local_tool` rather than returning a tool error. Same class as
`tools/guide_tool.py:23` (`os.getcwd()`); contrast `apps/tools/routes.py::_platform_root`, which resolves
from `__file__`.

**3. The Tools app lists a tool the platform refuses to run.** `tool_routes.json` category `web` includes
`git_tool`, which is in `tool_router.py::DISABLED_CHAT_TOOLS`. Chat never offers it and
`tool_dispatch.call_tool` hard-refuses it — the Tools app shows it as a normal routed capability with no
marking.

**4. The Tools app lists a category chat can never load.** `tool_routes.json` `user_guide` has **0 tools**,
19 keywords, and `guide: user.md`. `request_tools` rejects any category with no tools, and keyword matching
no longer loads tools (§5), so `prompts/guides/user.md` — the full capabilities overview — **can never be
injected into a chat prompt**, while the app presents it as a real category with a guide.

**5. Keywords are inert but presented as routing.** `chat_domain.py:186` replaced eager keyword routing
with the slot model: only `core` + pinned + `request_tools` slots load tools. `_match_categories` now feeds
only the `chat_turns` debug column, and `get_tools_for_message` survives on one dead path
(`chat_domain.py:482`, reachable only after `restart_mcp_server`, itself disabled).
`get_guides_for_message` is imported at `chat_domain.py:25` and never called. The Tools app renders each
category's keywords under a "Keywords" heading and `help.md` sells the app as the way to "understand
routing" — **a reader concludes that saying those words loads that category, which has not been true since
the slot model landed.**

**6. Nothing signals that a listed tool's integration is switched off.** `app_platform/capabilities.py`
gates optional integrations (Brave, Discord, Pushover, FCM, Gmail…) and tools return "X is not configured".
The catalogue shows e.g. `internet_search` identically whether or not `BRAVE_API_KEY` is set — for a
surface whose purpose is "confirm the tool is registered", configured-vs-unconfigured is the other half of
the answer.

**7. A corrupt `tool_routes.json` takes the whole catalogue down.** `routes.py:77-81` calls `json.load`
with no try/except, while the packaged half (92-104) is wrapped and degrades with a log warning.
`tool_router.py:14-27` documents that an unparseable `tool_routes.json` (git-merge conflict markers on
deploy) is a failure mode they have **actually hit**. In that state the app-declared categories are
perfectly readable but the endpoint 500s.

**8. The merge comment is wrong.** `routes.py:76` — "Legacy tool_routes.json — first so app packages can
override." Packaged categories are keyed `app:<id>`, so they can never collide with a bare legacy key;
nothing ever overrides anything. `TOOL_CATEGORIES` already contains the base file layer, so the direct file
read is redundant except as a fallback when the `tool_router` import fails.

**9. `refreshKey` in the Tools UI is dead.** `ui/ToolsApp.jsx:41-44` reloads on `refreshKey` change, but
`AppPanel.jsx:214` passes it only for goals, documents, reminders, recipes, brainstorming and todo — for
`tools` it is always `undefined`.

**10. Internal registry keys are shown as the category's name.** `ui/ToolsApp.jsx:120,161` render `cat.id`
with `capitalize`, so every packaged category displays as "App:goals", "App:weather".

**11. Two-thirds of the category icon map is unreachable.** `CATEGORY_ICONS` (247-268) keys on bare ids,
but every packaged category id is `app:<id>`. Dead entries: `system, reminders, goals, lists,
notifications, jobs, docs, finance, recipes`. Conversely `skipper_email` and `brainstorming` are real
legacy categories with no icon. Every packaged app falls through to the generic wrench.

**12. An empty catalogue and a failed first load look identical in the list.** When the first fetch fails,
`categories` stays `null` and the sidebar renders "No categories" — the same words as a genuinely empty
registry. The dismissible error banner is the only distinguishing signal.

**13. A declared-but-missing guide vanishes silently.** `routes.py::_resolvable_guide` returns `None` when
the declared guide file is absent, so the category renders as having no guide. **On a debugging surface,
"this category claims a guide that isn't on disk" is exactly the fact you came to find.** It also re-derives
packaged guides from the app id rather than the registry's `_guide_path`, so an app whose guide lived
elsewhere would show as having none.

**14. `ack` templates are not surfaced.** Categories carry `ack` (what Skipper says while a tool runs);
`/categories` drops the field, so the Tools app cannot answer "why does it say that when I ask about the
weather".

**15. `prompts/guides/INDEX.md` is stale.** It advertises `reminders.md`, `goals.md`, `lists.md`,
`jobs.md`, `notifications.md`, `docs.md`; the directory holds only `artifacts, brainstorming, knowledge,
links, memory, research, user, web` (+ INDEX). `tools/guide_tool.py::get_guide` with no argument returns
this index verbatim, so **the model is handed six guide names that then 404.** `brainstorming.md` and
`memory.md` exist but are not in the index; `memory.md` and `INDEX.md` are declared by no category, so they
are invisible in the Tools app while remaining readable via `GET /api/apps/tools/guide/memory`.

**16. Manifest fields nothing reads.** `core: true` is consumed by no code —
`app_platform/loader.py:76-81::REQUIRED_APPS` is a hardcoded tuple, so an app is "core" in two independent
places (20 manifests say `core: true`; the tuple has 20 entries — consistent today, one edit from not
being). `platform_min_version` and `app_deps` appear in no `.py`. Platform-wide: `AppManifest.ui` is parsed
and read by nothing, and no manifest declares a `ui:` section — UI registration is entirely via the Vite
glob over `apps/*/ui/index.js`.

**17. Three apps declare a `tool_category` that is never built.** `loader.py:209` builds a route only when
`has_tools`. `apps/brainstorming`, `apps/images` and `apps/thinking` declare `tool_category` (description +
keywords) with no `tools.py`, so those declarations are inert. For brainstorming this is masked: its 11
tools are routed by the legacy `brainstorming` entry in `tool_routes.json` while the app looks packaged.

**18. No admin gate on an operator surface.** `/api/apps/tools/*` sits behind the global auth gate only, so
any signed-in member — including a child account — can read every app's `guide.md` and everything in
`prompts/guides/`, i.e. **Skipper's prompt-engineering material**. Adjacent operator endpoints
(`/api/apps/disabled`) are admin-gated; the asymmetry deserves an explicit decision.

## Smaller

- `ui/ToolsApp.jsx:76` sums `c.tools.length` across categories, so a tool routed in two categories is
  counted twice, and a `"tools": null` entry in `tool_routes.json` would throw (`routes.py` passes `None`
  straight through).
- `CategoryDetail` has no `key`, so the guide's collapsed state persists across category switches —
  specced as intended, but it is incidental and a refactor would silently change it.
- `apps/tools/tests/test_tool_guide.py:25` says "Repo root = …/skipperbot-platform-wt/poc-14 (this file is
  tests/evolve/tools/)" — stale; the file lives at `apps/tools/tests/`.
- `apps/tools/specs/SPEC.md` says the guide route serves "from `prompts/guides/`" in the ownership list and
  then correctly describes both locations lower down.
