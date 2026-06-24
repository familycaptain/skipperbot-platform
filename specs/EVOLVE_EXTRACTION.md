# Evolve — Extraction into a standalone, reusable project (analysis + design)

> **Status:** analysis / design. The north-star from [`EVOLVE_MULTIREPO.md`](./EVOLVE_MULTIREPO.md) §11.
> Goal: make Evolve its own installable project — a **generic** SDLC engine any team points at their
> own set of GitHub repos — while running for Skipper **exactly as it does now**, with the only visible
> difference being that the Skipper in-platform "Evolve app" is replaced by Evolve's **own local web
> dashboard** (plus a repo-switcher). Built from a four-part codebase analysis (prompts+charter,
> platform coupling, orchestration+scripts, engine+runner).

## 1. Headline finding — the engine is a *playbook*, not a Python program
The canonical `/loop` engine **is `.claude/skills/evolve/SKILL.md`** — a markdown playbook executed by a
Claude Code *subscription session* on the brain box. It drives agents by *being* Claude Code and reading
the role prompts (`apps/evolve/agents/prompts/*.md`) + their output schemas (`registry.py`). It never
instantiates the Python orchestrator. The Python orchestration (`orchestrator.py`, `pipeline.py`,
`engine/*`, `runner.py`, `sdk_backend.py`, `lead_sdk.py`, `concierge.py`, `tooluse.py`) is the
**DEPRECATED** SDK/API engine (explicit `DEPRECATED` headers; gated behind `EVOLVE_SDK_ENABLE`).

So "the engine" = (a) the **playbook**, (b) the **agents-as-data** (prompts + registry/schemas), (c) the
**charter mechanism**, (d) a small set of **live helper modules** (`workspace`, `github_connector`,
`platform_bridge`, `cost`, `spec_index`, `variance`, `base`, `charter`, `store`/`gate_queue`/`activity`),
(e) the **human-side skills** (`evolve-pm`, `chat-ev`) + CLI scripts.

**What this forces — extraction is only viable as a real PROGRAM, not a playbook.** A playbook run by an
interactive Claude-Code session is not something you can clone and run; it's tied to the Claude Code CLI
+ a hands-on session. For Evolve to be a shareable, installable system, it must be a **program**: you
clone it, configure your fleet (VMs) + your charter + your repo registry, and run it — it executes the
loop **autonomously**, parking only at the human gates. So the target is a **coded engine**, full stop.
- **This is NOT about LLM "providers"** (that earlier framing was wrong). The only external integration
  is **GitHub**; the LLM stays **Claude**. The relevant cross-cutting requirement is that the engine and
  its scripts are **cross-platform (Windows / Mac / Linux)** — Python, not bash-only; remote VM control
  via cross-platform tooling, not unix-only ssh assumptions — because adopters configure their own VMs.
- **The runtime is the Claude Agent SDK** (`claude_agent_sdk` — the same SDK that powers Claude Code and
  that the old `sdk_backend.py` already used): a packaged Python program that runs the agentic loop in
  code while keeping the agentic capabilities (real Read/Edit/Bash tools, structured output, prompt
  caching). The LLM credential (an Anthropic key or a Claude subscription) is just config, not a
  "provider abstraction."
- **The playbook (`SKILL.md`) becomes the authoritative SPEC** the coded engine implements; the 21
  prompts + registry + charter carry over verbatim as agents-as-data. This is a real build: we previously
  shelved a coded engine in favor of the subscription playbook, so re-building a coded engine that is **as
  good as today's playbook logic** (now the best version) is the core effort — and the core risk.

## 2. Already decoupled (the good news)
- The SDLC substrate (`schema`, `store`, `engine` model, `agents`) is declared dependency-free +
  unit-testable standalone (`apps/evolve/__init__.py:14-20`).
- **The charter is already externalized:** `charter.py` reads `specs/CHARTER.md` by `## ` section keys;
  each agent declares the keys it needs (`registry.py`). Swap the charter file → swap the domain. This
  is the heart of the domain-pack design and it already exists.
- The scripts/bridge already speak a small REST contract (~6 endpoints) against a **configurable base
  URL** (`EVOLVE_PLATFORM_URL`/`EVOLVE_PI_URL`, default `localhost:8000`). Only the default + naming are
  Skipper-flavored.
- `github_connector.py` is essentially generic (env-driven; only `DEFAULT_REPO` + the `evolve-incidental`
  label are Skipper). `workspace.py` (git worktrees) is host-agnostic by design.

## 3. The coupling inventory — five thin seams
1. **STORE.** Run/gate/event/CFS state lives in the platform's **Postgres** (schema `app_evolve` via
   `app_platform.db`); `gate_queue.py`/`activity.py` call `*_in_schema` directly. `store.py` already has
   a `Backend` Protocol + `InMemory`/`Sqlite` impls (the `PostgresBackend` is unimplemented). → Generic
   store = SQLite; extend the existing Protocol to cover gates/runs/activity (7 Postgres-flavored SQL
   statements to port).
2. **TRANSPORT.** `platform_bridge.py` POSTs runs/gates/events to the Pi's `/api/apps/evolve/*` (service
   token + an offline outbox). → In a single-host local model this collapses to **direct store calls /
   loopback**; keep the interface (`push_gate`/`list_decided`/`resolve`/`report_run`).
3. **DASHBOARD.** `ui/EvolveApp.jsx` is a React app *inside* the Skipper web shell (imports the platform
   roles util, same-origin `/api/apps/evolve`, cookie auth, design-system CSS). → The generic **local web
   server** reimplements the ~6 REST endpoints + ships its **own SPA** (port the JSX, drop platform deps)
   + adds the **repo-switcher** (net-new).
4. **AUTH.** Operator = platform session+role; engine = a service token; deciding = the parent
   **`EVOLVE_DECIDE_TOKEN`** (operator-machine-only). The **two-tier split — service can push but NOT
   decide; only the operator decides** — is the core safety invariant. → Reimplement minimal local login
   + the same two-token split. Carry the parent-token-only-on-evolve-admin pattern verbatim.
5. **GITHUB / INTAKE.** Mostly generic; needs per-repo-set repo/token (ties directly to the multi-repo
   registry in `EVOLVE_MULTIREPO.md`).

## 4. The prompt / charter leaks (domain extraction)
The **process** prompts are already generic (security-screen, vision-fit, prioritize, review-packet,
code-audit, and the judgment logic of lead/triage/design/spec-audit). Leaks concentrate in:
- **Environment-adapter prompts:** `reproduce.md`, `validate.md`, deploy/test halves of
  `implement.md`/`lead.md` (box-2, `skipper update`, `ui_harness`, connector calls, the PWA gotcha).
- **Repo-topology + companion contracts:** `architecture.md`, `interop.md`, `grounding.md`,
  `code-scout.md` (`apps/<id>`, the dep-direction rule, `app_platform`, the `skipperbot-voice`/`mobile`/
  Discord contracts + the poc-7 war story).
- **Scattered:** the surface list (`web/chat/voice/mobile/Discord`), the tech stack (Python/FastAPI/React
  — `design.md:12-13`), the C/F/S path conventions, the **product name** (hardcoded even in
  `charter.py:70`), and the worked examples (weather/ZIP/recipe).

**Extraction targets:**
- **Charter sections:** keep thesis/is/non-goals/scope/autonomy/principles; **add** `surfaces`,
  `external-contracts`, `repo-layout`+dep-rule, `stack`, and an `examples` appendix. Prompts must
  *consume* these (the `charter_keys` mechanism already supports it) instead of restating them.
- **Config:** product name, model tiers+pricing+provider, fleet hostnames, branch model, state/outbox
  paths, run-id prefix, dep-rule prefixes, and **per-repo spec-root glob(s)** — *each managed repo
  declares where its own specs live* (default `specs/`; a repo may declare several, e.g.
  `apps/*/specs` + `specs/platform`), so spec-discovery / grounding resolves the C/F/S corpus **per
  repo** rather than assuming one global layout.
- **Prompt templating:** strip the "Skipper's Evolve engine" openers + hardcoded paths; inject
  `{product_name}` + the relevant charter excerpts; move worked examples into the per-charter appendix.

## 5. Target architecture — three layers
**A. The generic engine** (the standalone Evolve repo):
- A **coded orchestrator** (Python, on the Claude Agent SDK) that implements the playbook's logic
  autonomously — `SKILL.md` is the spec it implements — plus the human-side skills (`evolve-pm`,
  `chat-ev`), templated against config/charter. Cross-platform (Win/Mac/Linux).
- **Agents-as-data:** the role prompts (templated) + the registry (roster structure + the SDLC
  output-schema vocabulary).
- **Live helper modules:** `base`, `charter` (mechanism), `cost`, `variance`, `spec_index` (embedding
  dedup), `workspace` (VCS), the generic **store**, the intake adapter, the gate/dashboard server.
- The **local web server + dashboard** (runs/gates/events/decision/archive/reverify + repo-switcher) +
  the two-token auth.
- The **provider seam** (today: a coding-agent subscription; designed to allow a coded multi-provider
  backend later).

**B. The domain pack** (per project; Skipper's reproduces today's behavior):
- `CHARTER.md` (vision + surfaces + external-contracts + repo-layout + stack + examples).
- `config` (product name, models, fleet, branches, paths, dep-rules, intake repo/token).
- The **TargetAdapter** impl (deploy/health/acceptance/seed/scaffold recipes). Skipper's wraps
  `skipper update`, `/api/onboarding/status`, the `ui_harness` Playwright+chat driver, `seed_mock_data`,
  `new_app`.
- The **repo registry** (from `EVOLVE_MULTIREPO.md` — the set of repos this instance manages).

**C. The fleet** (renamed / abstracted topology):
- **evolve-admin** — runs `evolve-pm` + the local dashboard server; the operator's control surface;
  holds the parent decide token. (Replaces "the Pi as control plane.")
- **evolve-brain** — the loop (today box 1).
- **evolve-test** — agents validate (today box 2).
- **evolve-uat** — user verifies (today skipper-uat).

## 6. The adapter interfaces (the clean boundary)
| Seam | Skipper binding (today) | Generic default | Interface |
|---|---|---|---|
| **Store** | Postgres `app_evolve` via `app_platform.db` | SQLite (pattern in `store.py`) | `upsert_gate/list_gates/record_decision/resolve_gate` + `upsert_run/add_events/list_runs/events/cost_summary/set_archived` |
| **Transport** | `platform_bridge` HTTP→Pi + outbox | direct store calls / loopback | `push_gate/list_decided/resolve/report_run` |
| **Dashboard** | React app in the Skipper web shell | Evolve's own server + SPA | the ~6 REST endpoints (the existing contract) + repo-switcher |
| **Auth** | platform session+role; service+parent tokens | local login + the two-token split | principal resolver `{name, role, is_service}`; *service pushes / operator decides* |
| **Intake** | `github_connector` (one global repo) | per-repo-set GitHub | issue source, per active repo-set |
| **TargetAdapter** | `box2_live`+`skipper update`+`ui_harness`+`seed_mock_data`+`new_app` | per-project recipes | `deploy(host,ref)` · `health(host)` · `acceptance(host,spec)->evidence` · `seed(host)?` · `scaffold(unit)?` |
| **RepoLayout** | `apps/<cap>/specs` + `specs/platform`, dep-rule prefixes | **per-repo** config | each managed repo declares its own **spec-root glob(s)** (default `specs/`; e.g. `apps/*/specs`) + dep rules; `specs_root_for` · `spec_relpath` · spec-tree glob resolve **per repo** |
| **Workspace/VCS** | `WorkspaceManager` worktrees | already host-agnostic | `cut/serialize/merge/diff` + branch model + commit identity (config) |
| **Agent runtime** | the `/loop` subscription session (interactive Claude Code) | the **Claude Agent SDK** (`claude_agent_sdk`), packaged as a program | run each agent step in code (tools + structured output + cost). LLM stays Claude — credential is config, NOT a provider abstraction |

## 7. Net-new build (not extraction)
1. The **local web server + dashboard SPA** (port `EvolveApp.jsx`; reimplement the endpoints against the
   generic store; own theme — drop the `--ds-*`/platform-roles deps).
2. The **repo-switcher** — needs a `repo_set` scoping dimension across `runs`/`gates`/`activity`/`cfs`
   (every projection table is keyed only by `instance_id` today) + per-repo-set GitHub config. The single
   largest net-new design; ties to `EVOLVE_MULTIREPO.md`.
3. The **generic store** (SQLite) replacing the Postgres `app_evolve` schema.
4. **Minimal local auth** (login + the two-token split).
5. The **provider abstraction** (only if pursuing fork B).

## 8. Open decisions (for the operator)
1. **Coded engine on the Claude Agent SDK — DECIDED (§1).** A real installable program is the only
   viable extraction; the playbook is its spec, not the product. The open part is scope/effort + how
   faithfully the coded loop reproduces the playbook's behavior, not *whether*.
2. **The acceptance oracle.** Today: drive the live chat-agent web app + judge on captured tool-calls /
   DB / screenshots. This doesn't generalize to a CLI/library target. → a **tiered acceptance model**
   (unit-only | live-acceptance) per TargetAdapter. How generic now vs Skipper-only?
3. **`new_app.py`** is a *target* scaffolder (Skipper app contract), not engine — confirm it moves to the
   Skipper adapter (the engine keeps only an optional "scaffold a unit of work" hook).
4. **Where the engine/Skipper line falls.** You've said Skipper drops its in-platform Evolve app in favor
   of the local dashboard — confirm we **retire** `apps/evolve/ui/` + `routes.py` for Skipper once the
   standalone dashboard exists (vs Skipper keeping both).
5. **Cross-platform target hosts.** Adopters' VMs may be any OS — how far do we go (Linux-first with
   documented Win/Mac support, vs first-class all three from day one)?

## 9. Roadmap (phasing)
- **Phase 0** — this spec + the multi-repo registry (`EVOLVE_MULTIREPO.md` Phase 1). The repo-set is the
  unit that defines an Evolve instance.
- **Phase 1 — extract the domain pack** in place: add the charter sections (surfaces/external-contracts/
  repo-layout/stack), the config (product name/models/fleet/branches/paths), template the prompts +
  skills. Still running via today's playbook; prove the agents-as-data are fully domain-neutral.
- **Phase 2 — the coded engine (the core build):** a Python orchestrator on the **Claude Agent SDK** that
  runs the loop **autonomously** per `SKILL.md` (the pass model, funnel, gates, segments, reproduce-first,
  the two-token safety), executing the templated prompts/registry. Validate it reproduces the playbook's
  behavior on Skipper. Cross-platform.
- **Phase 3 — the generic store + local dashboard + repo-switcher** + the two-token auth; repoint the
  scripts (env rename). Replaces the in-platform Evolve app.
- **Phase 4 — the TargetAdapter boundary:** move the Skipper recipes (`skipper update`, box-2,
  `ui_harness`, seed, `new_app`) behind a cross-platform adapter; define the tiered acceptance model.
- **Phase 5 — split the repo:** the generic engine becomes its own repo; Skipper consumes it + supplies
  its pack; retire `apps/evolve/ui` + `routes.py`.

## 10. Risks / unknowns
- **The engine-is-prose inversion** is the biggest conceptual lift: much of the "engine" is the playbook
  + 21 prompts, not code. Templating them without losing hard-won behavior (fail-closed validation,
  operator-items-never-rejected, reproduce-before-grounding, the two-token safety) is the highest-risk
  task.
- **The acceptance oracle** assumes an introspectable chat-agent web app; it may not generalize.
- **The `repo_set` dimension touches everything** (schema + every query + the bridge + GitHub).
- **The coded engine must match the playbook.** We deprecated a coded engine once *because* the
  subscription playbook was better; rebuilding one that faithfully reproduces the playbook's behavior
  (fail-closed validation, reproduce-first, gate discipline, the two-token safety) on the Agent SDK is the
  central risk. The Agent SDK's shared-session **prompt-caching** is what makes the "1 issue = 1
  conversation forever" economics work — the coded loop must use it well or costs balloon.
- **Tests pin the deprecated path** — the existing `tests/` exercise the soft-deprecated SDK engine; they
  are an oracle for behavior but not proof the live (playbook) engine works.
