# Evolve — Multi-Repo Management (design)

> **Status:** design / not yet built. Tracks GitHub **#31** ("Evolve builds optional apps in separate
> repos"). This document captures the full design discussion so it can be resumed easily. Two items
> are still **OPEN** (see the end). The companion north-star — extracting Evolve into its own generic,
> reusable project — is noted at the end and will get its own spec.

## 1. The problem
Today the Evolve loop only really works on **one** repo (`skipperbot-platform`), and the GitHub issues
it watches live there too. We want it to manage **many** repos: the platform, the optional-app repos
(`skipperbot-app-*`), the companion service repos (`skipperbot-voice`, `skipperbot-mobile`), and
eventually model-connector repos (`skipperbot-model-*`). Two hard parts fall out:

1. **Discovery / token economy.** Scanning every issue of ~10 repos on every loop cycle wastes time and
   (worse) tokens. We need a deterministic, internal change-tracker that returns, in **one
   consolidated call, only the issues that changed** (new / edited / reopened / closed) since last poll.
2. **Execution.** The agents must understand how to *work in* a non-platform repo — where it clones,
   that it's an independent git repo with its own branches/release, and how to deploy + test it.

And a capability we want on top: **create a brand-new app that doesn't exist yet** (e.g. a "Wants" app)
— what's the workflow when there's no repo?

## 2. Grounding — how things actually work today
- **Optional apps are gitignored standalone clones, not submodules.** `.gitignore` is `apps/*` minus an
  allow-list of the *bundled* apps (notifications, timeline, goals, …). Each optional app is its own
  independent repo cloned into `apps/<name>`; on a fresh box they're simply absent (cloned per-install).
  No `.gitmodules`.
- **Naming convention:** the app id = repo name minus the `skipperbot-app-` prefix
  (`skipperbot-app-anime` → `anime` → `apps/anime`).
- **Auto-discovery:** the backend `app_platform.loader` scans `apps/`; the frontend
  `web/src/apps/registry.js` uses `import.meta.glob` at build time. So dropping `apps/<id>/` in and
  running `skipper update` (which rebuilds → re-globs) auto-registers an app.
- **`scripts/new_app.py`** scaffolds the app folder (router / data / migration / web component / help,
  semantic-CSS-correct) but does **not** `git init` or create a remote.
- **`apps/evolve/github_connector.py`** today: a single repo, `state=open`, full list, **no**
  `since`/ETag. Change-tracking is greenfield.
- **`skipper update`** = git pull + `docker compose up -d --build` (full rebuild incl. Tailwind
  re-scan + `npm ci`). There is no `skipper rebuild`. (See [[deploy-with-skipper-update]].)

**Key consequence:** because optional apps are gitignored *independent clones* (not submodules),
"work on app X" is cleanly just *operate git inside its own repo* — no submodule entanglement. The
`apps/<id>/` copy is a **deployment artifact**, NOT the canonical source.

## 3. Decisions (locked)
- **Canonical = the source repo; `apps/<id>/` is deployment only.** The agent works the source repo;
  the runtime re-clones/pulls into `apps/<id>`.
- **Issue intake: centralized** (for now). All issues filed in the platform repo, routed by
  `belongs_to: <repo>`. Federated per-app trackers can be added later (the poller supports both).
- **Remote/repo creation: operator-gated.** The loop never creates GitHub repos; that's a deliberate,
  outward-facing action the operator (or the PM on the operator's say-so) performs after Gate-1.
- **No app catalog exists** and we're not building one yet. To install an app today you just need its
  GitHub URL. (A catalog may come later.)
- **Uniform branch model: `release → main` for every repo**, same as the platform.
- **Portability / multi-tenancy is a first-class requirement.** Our Evolve instance manages *our*
  repos; another operator's instance manages *theirs* (their app repo, their GitHub account). So the
  repo list must be **per-instance local config**, never hardcoded in the shared/public code — the same
  rule as `.env` and [[public-distribution-no-embedded-secrets]].

## 4. The repo registry — per-instance config
A **gitignored config file** (the `.env` pattern, but structured), e.g. `evolve.repos.yaml` in the
platform root, with a tracked **`evolve.repos.example.yaml`** that ships neutral (documents the schema,
names none of our repos). Each Evolve operator fills in their own repos locally; the public repo
carries only the example. Standing up Evolve elsewhere = edit the local file, point at a repo URL — no
code change, nothing of ours leaks.

**Per-entry schema (approx):**
```yaml
- url: github.com/<owner>/skipperbot-app-wants
  type: app                 # platform | app | model | companion
  clone_path: apps/wants    # derived from type + name; overridable
  branch_model: release->main
  token_env: GITHUB_TOKEN   # override for a repo in another GitHub account
```
`token_env` is what makes "someone else's repo in their account" work — most entries use the default
token; a foreign repo points at its own.

**Config vs. state split:** the registry (the repo *list*) is operator-authored config in that file;
the poll **cursors / ETags** are loop-managed state under `~/.evolve-poc/` (alongside `seen.json`).
Operator edits config; the loop owns state. (A Settings-app UI to edit the registry is a fine *later*
addition — file first.)

A small `evolve_repos.py` loader reads the registry; the change-poller and the build/validate segments
both consult it.

## 5. Repo types — the per-type playbook
Type drives the convention; the agent grounds on this table:

| type | canonical | runtime / deploy | Evolve can auto-validate? |
|---|---|---|---|
| **platform** | in place | `skipper update` | yes |
| **app** (`skipperbot-app-*`) | source repo | clone → `apps/<name>` + `skipper update` | yes |
| **model** (`skipperbot-model-*`) | source repo | clone → `models/<name>` + `skipper update` | yes (connector loader scans `models/`) |
| **companion** (voice, mobile) | source repo | its **own** build / run / test | **not yet — no harness** |

Apps and model-connectors both fit "clone into a known subfolder + `skipper update`," so they're easy.
**Companion repos are the hard case:** voice and mobile are separate services with their own build/test,
they consume platform contracts, and per [[companion-repos-share-contracts]] platform changes have
silently broken them before with no validation harness. **Proposed (OPEN):** Evolve manages their
issues end-to-end *except execution* — discover, triage, spec, even draft the code — then **hands
build/test to the operator** until a per-repo harness exists. Honest about the limit; still gets the
requirements + a patch ready.

## 6. Multi-repo issue discovery — the change-tracker
Don't scan full issue lists. Use GitHub's deltas:
- Per repo: `GET /issues?state=all&sort=updated&since=<cursor>` returns **only** issues created / edited
  / closed since the cursor — usually empty.
- Cheaper still: **ETag conditional requests** (`If-None-Match`) → `304 Not Modified` returns nothing
  **and doesn't count against the rate limit**. An unchanged repo ≈ one free 304.

A new helper `poll_changes()` walks the registry, conditional-GETs each repo since its cursor, returns
**one consolidated delta** — `[{repo, number, action: new|edited|reopened|closed}]`, projected (no
bodies) — and advances each cursor. Bodies are fetched only when an item is actually worked, so the
discovery scan stays tiny. This replaces the loop's `list_open_issues` pass-1c; it's O(changes), not
O(issues × repos), and strictly better than the open-only poll (it also catches **edited** requirements
and **externally-closed** issues to reconcile). Builds on the same context-economy work as the
`pending` / `stranded` scans.

## 7. Repo-aware execution
The work item carries its `repo` (promote `belongs_to` from a flag to the registry key). Each segment
becomes repo-aware via the repo profile:
- **Build:** branch / commit / push *inside* the app's own repo. Platform git untouched (apps/* is
  gitignored → zero cross-contamination).
- **Validate / Gate-3:** `scripts/box2_live.py` gains a repo-aware mode — ensure the app is cloned at
  the feature branch into `apps/<id>` (or the type's clone path), then `skipper update`, then test.
- **Agent grounding** gains the per-type playbook **and hard cd-discipline**: always know which repo's
  git you're touching (the main new failure mode). Extends [[verify-live-state-not-memory]].

## 8. New-app workflow (e.g. the "Wants" app)
1. **Issue in the platform repo** (the app repo doesn't exist yet, so intake must be central): "New
   app: Wants — <what it does>."
2. **Triage / Vision** → "new optional app," vision-fit check.
3. **Gate-1:** Design specs the app (capability, C/F/S, data model, UI) + the scaffold plan; the
   operator approves — **including approving repo creation**.
4. **Build:** `new_app.py wants` → scaffold (semantic-correct); `git init` the source repo at
   `~/repos/skipperbot-app-wants`; implement features on a branch.
5. **Remote creation (operator-gated):** the operator (or the PM on say-so) runs
   `gh repo create <owner>/skipperbot-app-wants` and pushes. The loop never does this.
6. **Validate** on box 2 (loader auto-discovers it; frontend glob picks it up on rebuild) →
   **Gate-3** on uat → **publish** the app repo's `main`.

## 9. Phasing (it's big — don't do it in one shot)
- **Phase 1 — discovery:** the **registry file** + the **ETag/since change-poller** that walks it
  (inseparable). Self-contained, zero execution risk, immediate token-economy win. The "smart Python"
  the operator described.
- **Phase 2 — repo-aware build/validate for *existing* repos.** Unblocks fixing the optional apps
  (incl. the semantic-CSS migration) and general app bugs. The CSS migration is its first customer.
- **Phase 3 — new-app creation** (scaffold → operator-gated remote → full flow). Most complex; build
  on 1 + 2. Companion-repo execution harnesses are a later, per-repo effort.

## 10. OPEN items (to finalize before Phase 1 is fully specified)
1. **Companion repos (voice/mobile):** accept "Evolve specs + drafts, hands build/test to the operator"
   for now (§5)? Or keep them out of the registry entirely until they have a harness?
2. **Registry file location:** gitignored `evolve.repos.yaml` in the platform root next to `.env`
   (recommended), or under `~/.evolve-poc/` with the rest of the instance-local state?

## 11. North star — extract Evolve into its own generic project
Evolve's value (the agent swarm, the gates, the PM role, the loop architecture, the multi-repo
management above) is **domain-generic and reusable**; only the *charter* (what "Skipper" is and its
domain values) is project-specific. The intent is to **extract Evolve into its own repo/project** that
any team can install and point at their own set of GitHub repos — Skipper-specific knowledge isolated
into a swappable charter, everything else generic. The multi-repo design here is a prerequisite (an
Evolve instance is *defined* by the set of repos it manages). This extraction will get its own spec.
