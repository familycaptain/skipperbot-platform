# Building a Skipperbot App

This guide is the **human-facing authoring workflow** for creating a new
Skipperbot app from scratch. It covers scaffolding a new app repo, what the
generated files are, and how to test your app in a running platform.

Three documents work together — know which is which:

| Document | Role |
|---|---|
| **docs/BUILDING_APPS.md** (this file) | The step-by-step authoring workflow. **Start here — this is the doc for humans.** |
| [**specs/APP_PACKAGES.md**](../specs/APP_PACKAGES.md) | The **app contract** — the rules every app must satisfy (extension points, the `manifest.yaml` schema, memory digestion on every CRUD, notify via `create_notification`, recurring work via schedules, UI ↔ chat parity). It's written as **prompt guidance for an AI assistant** — point your AI at it rather than reading it cover to cover yourself. |
| [**docs/02-adding-apps.md**](02-adding-apps.md) | How to **install and test** an app (yours or someone else's) into a running platform. |

You're in the right place: **read this guide**, then follow the steps below.
If you're building with an AI assistant, hand it
[specs/APP_PACKAGES.md](../specs/APP_PACKAGES.md) as the contract to code
against — it's the prompt guidance, not a human tutorial.

> **Prefer to automate the whole build-and-review cycle?** See
> [**Expand Skipper with Evolve**](#expand-skipper-with-evolve) below — a
> standalone engine that drives this same authoring → review → test workflow
> from a GitHub issue.

## Where apps live

New apps usually live in their own sibling repo named like
`skipperbot-app-<name>`, **not** inside this platform repo. The platform repo
holds core platform code and the required (`core: true`) apps that ship with
it. You build your optional app in its own repo and install it by dropping the
folder into a platform's `apps/<id>/` directory.

## Step 1 — Scaffold a new app repository

From the platform repo root, run:

```bash
python scripts/new_app.py
```

The script is interactive:

- it asks for the app **display name** (proper-cased, e.g. `Trail Log`);
- it suggests a folder name like `skipperbot-app-<name>` in lowercase, which
  you can override.

It creates a sibling directory (`../skipperbot-app-<name>/`) with a working,
contract-compliant skeleton built around a placeholder `item` entity. The
script prints the derived **app id** (the lowercase identifier used as the
folder under `apps/`, the Postgres schema `app_<id>`, and the Python package
`apps.<id>`), the entity prefix, and your next steps.

## Step 2 — Understand what was generated

```
skipperbot-app-<name>/
  manifest.yaml          # how the platform discovers and wires the app
  __init__.py            # makes apps.<id> an importable package
  data.py                # data layer — calls digest_record on every mutation
  tools.py               # MCP / chat tools (namespaced, UI ↔ chat parity)
  routes.py              # FastAPI router (bare; platform mounts /api/apps/<id>/)
  handlers.py            # optional event subscribers / job handlers
  guide.md               # agent-facing guide (how the agent drives the tools)
  help.md                # user-facing manual (shown in-app via the ? button)
  migrations/
    001_initial.sql      # schema for the app_<id> Postgres schema
  ui/
    index.js             # launcher registry array (NOT a DOM entry point)
    <Name>App.jsx        # starter React component (full-size flex root)
  specs/
    SPEC.md              # this app's spec
    APP_PACKAGES.md      # a copy of the canonical contract (kept in sync)
  README.md  LICENSE  .gitignore  pyproject.toml
  tests/test_smoke.py
```

The platform discovers capabilities by **well-known file names**, so the names
above matter. A couple of optional files the scaffold doesn't create, which you
can add by hand when you need them:

- `hooks.py` — export `register_hooks()` to plug into platform provider slots
  (backlog / activity / nag providers, schedule claims, and prompt-context
  providers via `app_platform.prompt_context.register_prompt_context` to inject
  extra prompt blocks for the `voice`/`chat` surfaces) without the platform
  importing your app.
- `store.py` / `runner.py` — app-internal business logic / background pipeline.
- `think.md` — a thinking-domain prompt, if your manifest declares `thinking`.

**`guide.md` vs `help.md` — they are different and you want both.** `guide.md`
is for *the agent* (tool names, arguments, edge cases). `help.md` is a full
*user manual* shown in the app's **?** panel and returned by the `get_app_help`
chat tool. See [docs/app-help-authoring.md](app-help-authoring.md) for the
expected `help.md` structure.

The scaffold is deliberately wired the way the loader expects:

- `data.py` imports and calls `digest_record(...)` after create/update/delete —
  this is **required**, not optional. An app that skips it is invisible to chat
  recall. See the "Memory digestion" section of the contract.
- `tools.py` functions are namespaced (`create_<id>_item`, `list_<id>_items`)
  so they don't collide with other apps' tools, and they mirror what the UI can
  do (UI ↔ chat parity).
- `routes.py` uses a bare `APIRouter()` — the platform mounts it at
  `/api/apps/<id>/`. Do not add your own prefix.
- `ui/index.js` **default-exports an array** of launcher registrations; the web
  build discovers it via `import.meta.glob`. It is not a `createRoot(...)`
  bootstrap.

## Step 3 — Make it yours

1. Replace the placeholder `item` entity with your real data model: update
   `entity_types` in `manifest.yaml` (pick a short, **globally unique**
   prefix), the `migrations/001_initial.sql` table(s), the CRUD in `data.py`
   (keep the `digest_record` calls and the `_HINT`), the tools, and the UI.
2. Tune `tool_category.description` and `keywords` so chat routes to your app.
3. Write `guide.md` so the agent knows when and how to use the tools.
4. Honor the rest of the contract as your app grows:
   - Notify users via `create_notification` — never channel-specific senders.
   - Put recurring work in `public.schedules` (a Python migration seeder),
     never directly in `public.jobs`.
   - Keep UI ↔ chat parity: anything a user can click, they can also say.
5. Keep `specs/APP_PACKAGES.md` in sync with the platform's canonical version —
   it is the contract and the prompt guidance for AI tooling.

## Step 4 — Test it in a running platform

Your app lives in its own repo, but it only *runs* when it's inside a
platform's `apps/` directory. To test locally, copy or clone it in as
`apps/<id>/` (the folder name **must** equal the `id:` in `manifest.yaml`) and
restart:

```bash
# from a checkout of skipperbot-platform
cp -r ../skipperbot-app-<name> apps/<id>      # or: git clone <url> apps/<id>
# restart the platform — the web bundle rebuilds automatically
```

Follow [docs/02-adding-apps.md](02-adding-apps.md) for the full install,
restart, verify, and troubleshoot steps. On boot the loader creates the
`app_<id>` schema, runs your migrations, and registers your entity types,
tools, routes, and UI.

## Expand Skipper with Evolve

Skipper is built with a repeatable software process — declarative C/F/S specs,
AI-assisted authoring, independent review, isolated builds, and validation on a
real test host before anything merges. **Evolve** packages that same process as
an autonomous SDLC engine you point at a codebase.

Give Evolve a GitHub issue and it drives the change end to end: it triages the
request, **reproduces** the reported behavior on a live test host (with proof),
writes a C/F/S spec, runs a panel of independent AI reviewers, **builds the
change in an isolated git worktree**, validates it against the running product
on the test host, and walks it through human approval gates — **Gate 1** (the
spec / intent), **Gate 2** (the built *and validated* result), and **Gate 3**
(your own verify on a UAT host) — before it merges.

Because it follows the same patterns Skipper was built with, it's a natural way
to **extend Skipper with the same rigor**: hand-author a quick app with the
steps above, or reach for Evolve when you want issue-driven, reviewed, gated,
tested changes.

**Evolve is a standalone engine you run yourself** — it is *not* a Skipper app,
you don't clone it into `apps/`, and the platform doesn't load it. It lives in
its own repo, separate from this platform:

➡️ **<https://github.com/familycaptain/evolve>** — the full picture of how Evolve
works and how to run it.

## Licensing your app

Your app is your own work. The platform is MIT-licensed, but a separately
distributed app does **not** have to be — you may release it under any license
you choose, including a **proprietary or commercial** one (a paid app with an
EULA is fine). The scaffold drops a placeholder `LICENSE` file telling you to
pick one; replace it with your chosen terms. The only thing that must stay
MIT-compatible is any code you contribute back **into the platform repo
itself** (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

## Publishing

If you want your app to become an officially supported optional app (listed in
the catalog in [docs/02-adding-apps.md](02-adding-apps.md)), or you're building
a new **core** app that should ship inside the platform repo, reach out to the
maintainers first so the design and ownership model can be discussed.
