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

**The first fork this forces:** the canonical engine is currently inseparable from "a Claude-Code-style
coding-agent subscription as the provider." A clean extraction must pick:
- **(A) Ship the playbook as the engine.** Generic Evolve = playbook + prompts + helpers + a charter,
  run by a coding-agent subscription. Closest to what we run today; lowest risk; but ties adopters to a
  Claude-Code-style runner.
- **(B) Build a coded, multi-provider engine.** Resurrect/genericize the token-walker + a provider
  abstraction so it's self-contained and LLM-agnostic. A true standalone product; much bigger build.
- **Recommendation:** **A first**, with the provider seam (§6) designed so B is possible later.

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
- The ported **playbook** + the human-side skills (`evolve-pm`, `chat-ev`), templated against
  config/charter.
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
| **Provider/Model** | Anthropic-only (`runner` Messages, the SDK, or the subscription) | provider abstraction | `(spec,payload,system,model)->AgentResult` w/ structured output + usage/cost |

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
1. **Playbook engine (A) vs coded engine (B)** — the fundamental product fork (§1). *Rec: A first, design for B.*
2. **The acceptance oracle.** Today: drive the live chat-agent web app + judge on captured tool-calls /
   DB / screenshots. This doesn't generalize to a CLI/library target. → a **tiered acceptance model**
   (unit-only | live-acceptance) per TargetAdapter. How generic now vs Skipper-only?
3. **`new_app.py`** is a *target* scaffolder (Skipper app contract), not engine — confirm it moves to the
   Skipper adapter (the engine keeps only an optional "scaffold a unit of work" hook).
4. **Where the engine/Skipper line falls.** You've said Skipper drops its in-platform Evolve app in favor
   of the local dashboard — confirm we **retire** `apps/evolve/ui/` + `routes.py` for Skipper once the
   standalone dashboard exists (vs Skipper keeping both).
5. **Provider:** stay Claude-Code-subscription-only (simplest) or build the multi-provider seam now?

## 9. Roadmap (phasing)
- **Phase 0** — this spec + the multi-repo registry (`EVOLVE_MULTIREPO.md` Phase 1). The repo-set is the
  unit that defines an Evolve instance.
- **Phase 1 — extract the domain pack** in place: add the charter sections (surfaces/external-contracts/
  repo-layout/stack), the config (product name/models/fleet/branches/paths), template the prompts +
  skills. Skipper still runs in-platform; prove the engine reads *everything* domain from the pack.
- **Phase 2 — the generic store + local dashboard:** reimplement the REST contract + port the SPA + the
  two-token auth; repoint the scripts/bridge (env rename); add the repo-switcher.
- **Phase 3 — the TargetAdapter boundary:** move the Skipper recipes (`skipper update`, box-2,
  `ui_harness`, seed, `new_app`) behind the adapter; define the tiered acceptance model.
- **Phase 4 — split the repo:** the generic engine becomes its own repo; Skipper consumes it + supplies
  its pack; retire the in-platform Evolve app.
- **Phase 5 (optional)** — the coded multi-provider engine (fork B).

## 10. Risks / unknowns
- **The engine-is-prose inversion** is the biggest conceptual lift: much of the "engine" is the playbook
  + 21 prompts, not code. Templating them without losing hard-won behavior (fail-closed validation,
  operator-items-never-rejected, reproduce-before-grounding, the two-token safety) is the highest-risk
  task.
- **The acceptance oracle** assumes an introspectable chat-agent web app; it may not generalize.
- **The `repo_set` dimension touches everything** (schema + every query + the bridge + GitHub).
- **Provider/structured-output variance** (forced-tool vs json_schema vs response_format) and
  **shared-session prompt-caching economics** ("1 issue = 1 conversation forever") are a portability risk
  for fork B.
- **Tests pin the deprecated path** — the existing `tests/` exercise the soft-deprecated SDK engine; they
  are an oracle for behavior but not proof the live (playbook) engine works.
