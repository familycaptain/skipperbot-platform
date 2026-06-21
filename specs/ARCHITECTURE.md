# Skipperbot — Architecture

> **The system-level overview: how the platform is layered, how app packages
> plug in, and the rules that keep them decoupled.**
>
> This is the high-level map. For the full app-authoring contract (package
> structure, manifest fields, extension points, the memory / notifications /
> schedules / time *rules*), see [APP_PACKAGES.md](APP_PACKAGES.md). For the
> `app_platform.*` service signatures see
> [PLATFORM_SERVICES.md](PLATFORM_SERVICES.md); for entity IDs see
> [ENTITY_TYPES.md](ENTITY_TYPES.md); for the event bus see
> [EVENTS.md](EVENTS.md).

---

## Core principle: agentic desktop

Skipperbot is an **agentic desktop** — every feature is reachable through
**both** the visual desktop UI **and** the chat interface (web, voice, or
Discord). These are equal first-class interaction paths, not a UI with a chatbot
bolted on. When you build a feature, both paths must be fully functional: an
app that only works by clicking is incomplete. This **UI ↔ chat parity** rule is
load-bearing enough that it has its own section in
[APP_PACKAGES.md](APP_PACKAGES.md#core-principle-ui--chat-parity).

The platform is a **host** that loads **app packages**. The platform owns the
agent loop, memory, scheduling, notifications, the desktop shell, and the shared
services every app uses. Each app is a self-contained folder under `apps/<id>/`
that the platform discovers and wires in at runtime. Adding a capability means
dropping a folder in; removing it means deleting the folder.

---

## Core principle: context economy (assemble context just-in-time)

The model's context window is a **finite, contended, expensive** resource, and
stuffing it works *against* quality — it inflates token cost and latency, and it
**dilutes attention** so the one instruction that matters gets buried under
everything that doesn't. So a load-bearing rule across the whole system:

> **Give the agent exactly the guidance, tools, and memories the task in front of
> it needs — assembled at the right time — and nothing more.**

We deliberately do **not** concatenate every prompt, every tool schema, every
`guide.md`, and every memory into one giant always-on system prompt. Instead we
**inject just-in-time, scoped by relevance, with on-demand expansion**:

- **Tools** — the tool router injects only the categories a turn's keywords match,
  not the whole catalog; the LLM pulls more mid-conversation with
  `request_tools(category)`. (See [Keyword routing](#keyword-routing-for-tool-injection).)
- **Behavioral guidance** — a tool's `guide.md` rides *alongside that tool* when it's
  routed in, never globally.
- **Memory** — recall surfaces the *relevant* memories via semantic search
  (`search_memories`), never the entire store.
- **Evolve's own agents** — each role gets *its* lens prompt (the security reviewer
  doesn't carry the UX prompt); the spec phase **grounds once and resumes** rather than
  re-stuffing the codebase into every turn.

This is a **design constraint, not an afterthought.** When you add a capability, wire
its context to load **conditionally / on demand** — do not append it to the always-on
system prompt because it's convenient. Prefer lazy loading, relevance-scoping, and an
explicit "ask for more" path (`request_tools`, `search_memories`) over eager inclusion.

It is a **balance to manage, not a race to the smallest prompt.** "Lazy" here means
*defer and scope*, never *omit* — include everything genuinely required for correct
behavior, just delivered at the right moment to the right agent. The failure modes are
symmetric: a bloated prompt (lazy in the *other* direction — "add everything from
everywhere") is as much a defect as a missing instruction.

---

## Core principle: comprehensive fixes, no lingering debt

When you fix or change something, do it **comprehensively and in one shot** — across the
**entire platform AND every app**, covering **all areas the change touches** — and **validate
all of them**. The default is *thorough*, not *minimal*.

- **A fix covers every instance of its root cause.** If the same defect/pattern exists in N
  places (a native-submit form bug in three components, a missing guard in five handlers, a
  raw color class in every app), the fix is all N — found by enumerating the pattern (grep it),
  not by patching the one reported site. Fixing one and filing the rest "for later" is not a
  tighter scope; it ships the same bug elsewhere and **spawns a duplicate issue for the same
  work**.
- **"Fixed" means fixed everywhere it lives, and proven.** Validate every area the change
  touches — not a spot-check. An instance left unfixed (or unverified) means the issue is **not
  done**: say so and widen the scope; never close it green.
- **No lingering technical debt; no repeat/follow-up issue for the same thing.** A change that
  knowingly leaves the same class of problem behind is incomplete by definition.
- This is **distinct from** an *unrelated* bug tripped over in passing — that genuinely is its
  own issue. The test: **SAME root cause / same fix → do it here; a DIFFERENT fix → separate
  issue.** And it is **not** a license to widen into unrelated work or gold-plate — it is:
  finish the job for the actual root cause, everywhere it manifests, the first time.

Sizing follows from this, never the reverse: an issue is as large as completing its fix
honestly requires — a one-line change or a platform-wide sweep are both valid; a *partial* fix
is not.

---

## Layered architecture

Every feature follows a strict bottom-up layering. The same shape applies
whether the code lives in the platform core or inside an app package — only the
file locations differ.

```
┌─────────────────────────────────────────────────────────────┐
│  UI (React)        web/  +  apps/<id>/ui/*.jsx              │  Consumes REST
├─────────────────────────────────────────────────────────────┤
│  REST API          agent.py  +  apps/<id>/routes.py        │  Returns JSON
├─────────────────────────────────────────────────────────────┤
│  MCP / chat tools  local_tools.py  +  apps/<id>/tools.py   │  Returns strings
├─────────────────────────────────────────────────────────────┤
│  Data layer        data_layer/  +  apps/<id>/data.py       │  Postgres CRUD
└─────────────────────────────────────────────────────────────┘
```

- **UI** — React components. Platform-native screens live in `web/src/`; an
  app's screens live in `apps/<id>/ui/` and are discovered by Vite
  (`web/src/apps/registry.js`) at build time. UI talks to the REST API only.
- **REST API** — FastAPI. The platform's own endpoints are in `agent.py`; an
  app exports a bare `APIRouter` from `routes.py` that the loader mounts at
  `/api/apps/<id>/`. Endpoints return **structured JSON** for React.
- **MCP / chat tools** — the chat-facing layer. An app's public functions in
  `tools.py` become MCP tools (docstring → schema). A small set of runtime-bound
  tools live in the platform's `local_tools.py`. Tools return **formatted
  strings** for the LLM.
- **Data layer** — schema-scoped Postgres CRUD. Platform tables are served by
  `data_layer/`; an app's tables are served by its own `data.py`. This is the
  single source of truth both the REST and tool layers call into.

### Build order

1. **Data layer** — migrations + CRUD. The shared foundation.
2. **Chat tools** — `tools.py` functions wrapping the data layer. Chat is a
   first-class path, not an afterthought.
3. **REST API** — `routes.py` endpoints serving JSON to the UI.
4. **UI** — React components consuming the REST API.

### Why this order matters

- The **data layer** is the single source of truth. Both the tool layer and the
  REST layer call it — there is **no duplicated business logic**.
- **Chat tools come before the UI** because chat is a first-class path. Building
  the UI first tempts you to put logic in the route handler and skip the tool.
- The **REST API** exists to serve structured JSON; MCP tools return formatted
  strings, which aren't suitable for React. Both call the same data-layer
  function — they differ only in response shape (JSON vs. string).

---

## The app-package model

A feature is **not** woven into a dozen central files. It is a vertical slice in
one folder. The platform discovers each app's capabilities by the **presence of
well-known files** — no central registration:

```
apps/recipes/
  manifest.yaml      # REQUIRED — id, entity types, tool_category, ui, jobs…
  __init__.py        # REQUIRED — makes apps.recipes importable
  migrations/*.sql   # app schema (runs inside app_recipes)
  data.py            # data layer (CRUD; calls digest_record)
  tools.py           # chat tools (public fns → MCP tools)
  routes.py          # FastAPI router (mounted at /api/apps/recipes/)
  handlers.py        # @subscribe handlers + job handlers (optional)
  guide.md           # agent guide (how to drive the tools)
  help.md            # user manual (in-app ? button)
  ui/index.js        # default-exports the launcher registry array
```

The app loader (`app_platform/loader.py`) walks `apps/`, reads each
`manifest.yaml`, and runs the discoverers for each extension point: schema
migrator, tool loader, route mounter, entity-type registrar, UI collector, event
bus, job-handler registry, and thinking-domain registrar. A broken app is caught
and disabled per-app — it can't crash the platform. The full structure, manifest
field reference, and all eight extension points are documented in
[APP_PACKAGES.md](APP_PACKAGES.md#app-package-structure).

### Required vs. optional apps

The platform ships a set of **required (core) apps** inside this repo and
**refuses to boot without them** — the loader holds a `REQUIRED_APPS` list and
calls `require_apps(...)` after loading (`app_platform/loader.py`). Optional apps
live in their own repos (`skipperbot-app-<name>`) and are installed by dropping
the folder into `apps/<id>/`. You generally author optional apps; core apps are
platform-owned. Use `scripts/new_app.py` to scaffold a contract-compliant
optional app skeleton.

---

## Tool layer: MCP tools, local tools, and keyword routing

### App tools vs. local tools

**App tools** (`apps/<id>/tools.py`) are the default and the overwhelming
majority. Each public function becomes an MCP tool; its Google-style docstring
(with `Args:` / `Returns:` / `Ack:`) becomes the schema the LLM sees. Helpers
stay underscore-prefixed so the loader skips them. All domain logic goes here.

**Local tools** (`local_tools.py`) are the exception. They exist only for tools
that need **agent runtime state** the tool layer can't reach — the live
WebSocket connection manager, the Discord client, or the tool router itself:

| Local tool | Why it's local |
|---|---|
| `send_message_to_user` | needs the WebSocket connection manager |
| `list_connected_users` | needs the WebSocket connection manager |
| `open_app` | needs the WebSocket connection manager |
| `send_discord_dm` | needs the Discord client |
| `list_all_tools` / `request_tools` | needs tool-router runtime state |
| `restart_agent` | needs process control |

**Rule:** if the tool doesn't need WebSocket, Discord, or tool-router state, it
belongs in an app's `tools.py`. Period.

### Keyword routing for tool injection

The tool router (`tool_router.py`) injects only the relevant tool schemas per
chat turn, to keep token usage low. It does **not** hand the LLM every tool.

The route table is **built dynamically at boot** by merging three layers
(`tool_router.py`):

1. **base** — `tool_routes.json` (git-tracked, read-only at runtime): the
   canonical built-in categories.
2. **local** — `tool_routes.local.json` (gitignored): routes registered at
   runtime; never tracked, so a `git pull` can't corrupt it.
3. **app** — in-memory `app:<id>` categories built from each loaded app's
   `tool_category` block in `manifest.yaml`. The loader calls
   `merge_app_tool_routes(...)` after loading; these are **rebuilt every boot
   and never persisted**.

So an app contributes its routing simply by declaring a `tool_category`
(description + keywords) in its manifest and shipping a `guide.md`. There is no
hand-edit of a central route file.

Per turn:

- **Core tools** (memory, chat history) are always available.
- **Meta tools** (`list_all_tools`, `request_tools`, `open_app`) are always
  available.
- **Domain tools** are injected only when a turn's keywords match a category.
- **Guides** (`guide.md`) are injected alongside their tools for behavioral
  context — when, and when *not*, to use each tool.

If the LLM needs tools that weren't auto-routed, it calls `request_tools(category)`
to load a category mid-conversation.

> **Disambiguation depends on memory.** When keyword routing loads several apps'
> tools and the LLM must pick one, the decisive signal is semantic memory recall
> (`search_memories`). That's why every app's data layer **must** call
> `digest_record` on every mutation — see
> [APP_PACKAGES.md](APP_PACKAGES.md#required-memory-digestion-on-every-crud)
> and [MEMORY.md](MEMORY.md).

---

## REST layer

App REST endpoints live in `apps/<id>/routes.py` as a bare `APIRouter`; the
loader mounts it at `/api/apps/<id>/`. Platform-level endpoints live in
`agent.py`. Both:

- Return **structured JSON** (not the formatted strings MCP tools return).
- Use `asyncio.to_thread()` to call the synchronous data layer.
- Use Pydantic `BaseModel` for request-body validation.
- Raise `HTTPException` for non-200 status codes.

```python
# apps/recipes/routes.py
from fastapi import APIRouter
from apps.recipes import data as _data

router = APIRouter()   # loader mounts at /api/apps/recipes/

@router.get("/")
async def list_recipes(category: str = ""):
    return {"recipes": await asyncio.to_thread(_data.list_recipes, category)}
```

The REST endpoint and the matching chat tool call the **same data-layer
function**. They differ only in response format — JSON for the UI, a formatted
string for the LLM.

---

## Entity ID conventions

Every entity has a prefixed, opaque ID, generated as
`f"{prefix}-{uuid.uuid4().hex[:8]}"` (e.g. `re-1a2b3c4d`). The prefix tells the
platform which app, schema, and table the entity lives in — which is how the
link system resolves a target without the apps knowing about each other.

Prefixes are **declared by the owning app** in its `manifest.yaml` under
`entity_types`, and registered into `public.entity_types` at load time. The
loader fails loudly if two apps claim the same prefix.

| Prefix | Entity | Owner |
|---|---|---|
| `g-` | Goal | app |
| `p-` | Project / task tree | app |
| `t-` | Task | app |
| `re-` | Recipe | app |
| `mp-` | Meal plan | app |
| `r-` | Reminder | app |
| `d-` | Document | platform service |
| `m-` | Memory | platform |
| `k-` / `kc-` | Knowledge source / crawl | platform |
| `a-` | Artifact | platform |
| `i-` | Image | platform |
| `j-` | Job | platform |

This is a representative slice, not the full registry — each app contributes its
own prefixes, and the live set is whatever's installed. See
[ENTITY_TYPES.md](ENTITY_TYPES.md) for the complete model: the
`public.entity_types` table, how `manifest.yaml` declares prefixes, conflict
handling, and how the link system uses a prefix to resolve schema and table.

---

## Platform services (`app_platform.*`)

Shared capabilities are exposed under the stable `app_platform.*` package
namespace. These are **not apps** — they are platform infrastructure with
backward-compatible APIs. App code imports the facade; the platform guarantees
the signature so app code never has to change because an internal moved. (Some
`app_platform.*` modules are thin facades over a core app or a `data_layer/`
module — the facade is the contract.)

| Service | Import | Purpose |
|---|---|---|
| `app_platform.db` | schema-scoped Postgres access | DB CRUD |
| `app_platform.events` | `emit`, `subscribe` | event bus |
| `app_platform.entities` | `query_entities` | read-only cross-app queries |
| `app_platform.memory` | `digest_record` | semantic memory ingestion (required on CRUD) |
| `app_platform.links` | link CRUD + blast radius | entity linking |
| `app_platform.documents` | `create_doc`, `get_doc`, `update_doc` | document store |
| `app_platform.notifications` | `create_notification` | multi-surface notifications |
| `app_platform.schedules` | `create_schedule`, … | recurring schedules |
| `app_platform.jobs` | `submit_job` | background job queue |
| `app_platform.time` | `now`, `utcnow`, `to_local` | timezone-aware clock |
| `app_platform.auth` | principals + authorization | authentication |

This is an index, not the contract. The full signatures, the "forwards to"
owner of each facade, and the non-negotiable usage rules (notify via
`create_notification`, recurring work via `schedules`, never read the naive wall
clock) live in [PLATFORM_SERVICES.md](PLATFORM_SERVICES.md) and
[APP_PACKAGES.md](APP_PACKAGES.md).

---

## The dependency rule (one-directional)

This is the rule the whole architecture rests on:

> **Apps may depend on the platform. The platform may not depend on any app.**

Concretely:

- App code imports from `app_platform.*` and its own package — **never** from
  `apps.<other>.*`.
- Cross-app **reads** go through `app_platform.entities.query_entities`;
  cross-app **writes** go through `app_platform.events`. There is no third
  option, and there are no cross-schema foreign keys (cross-entity references use
  the `links` table, not hard FKs).
- Platform / core code **never** does `import apps.<id>`. A few apps are flagged
  **core** (the platform won't boot without them), but the platform still
  reaches them only through their `app_platform.*` facade, not by importing the
  package.

This is what keeps every app independently installable, removable, and **safe to
fail** — the property that makes it safe for the agent itself to build and modify
apps. The cross-app worked examples (entity queries vs. events) are in
[APP_PACKAGES.md](APP_PACKAGES.md#cross-app-data-access).

---

For everything about building an app — the package structure, the full manifest
reference, the eight extension points, the memory / notification / schedule /
time rules, lifecycle, and the agent-built-app loop — see
[APP_PACKAGES.md](APP_PACKAGES.md).
