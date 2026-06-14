# Evolve — build status & how to run

The self-maintaining SDLC engine (design: `specs/EVOLVE.md`; C/F/S tree:
`specs/evolve/`). This is an overnight first build of the substrate + the agent
swarm. **The deterministic core runs and is unit-tested; the Claude agent swarm is
verified live end-to-end.**

## What's built (and proven)

| Layer | Module | Status |
|---|---|---|
| **cfs-store** | `schema.py`, `store.py`, `variance.py` | ✅ built, 23 tests, **live** specs |
| **process-engine** | `engine/{model,instance,walker,mermaid}.py` | ✅ built, 6 tests, **live** specs |
| **agent framework** | `agents/{base,runner,registry}.py` + `prompts/` (15 curated) | ✅ built, **live-verified** |
| **charter grounding** | `agents/charter.py` + `specs/CHARTER.md` | ✅ curated per-agent, budgeted, **live-verified** |
| **tool-use backend** | `agents/tooluse.py` (code-acting agents run skills + write_file) | ✅ built, sandboxed, **live-verified** |
| **box-1/box-2 mechanics** | `workspace.py` + `build_loop.py` (feature→release loop) | ✅ Stage 1 built + tested on one machine |
| **orchestrator** | `orchestrator.py` (engine ⟷ swarm) | ✅ built, **live-verified** |
| package glue | `manifest.yaml`, `migrations/*.sql` | ✅ written (runs when the platform hosts it) |

**77 unit tests pass with zero installs** (stdlib `unittest`); 2 live tests are gated
(`EVOLVE_LIVE_TESTS=1`) and both have been run green against Claude.

## Where prompts & skills live

- **Agent system prompts** → `apps/evolve/agents/prompts/<agent>.md` (referenced by
  `AgentSpec.prompt_file`). At call time the Runner composes the effective system
  prompt = the role prompt **+ only the curated charter sections the agent declares**
  (`charter_keys`, assembled by `agents/charter.py` from `specs/CHARTER.md`). Budget:
  `SYSTEM_PROMPT_TOKEN_BUDGET` (1600 est. tokens) — over it = trim grounding or split
  the agent. **All 15 agents now have curated prompt files**, each within budget
  (design=1474 is the ceiling).
- **Claude Skills** → `.claude/skills/<name>/SKILL.md` (clone-portable; see that
  dir's README). Executable capability packages for the **code-acting agents**
  (`implement`/`test-author`/`validate`, `requires_tools=True`) on the Agent SDK
  path — NOT the reasoning agents (Messages API, structured output only, which the
  Messages backend explicitly refuses to run for `requires_tools` agents). Shipped:
  `cfs-validate`, `run-evolve-tests`. The **tool-use backend** (`agents/tooluse.py`)
  that executes them is **built + live-verified** (sandboxed bash: allowlist from the
  skill's `allowed-tools`, no shell metacharacters, writes off by default). Mutation
  (implement writing code) still belongs on box 2, so the full pipeline keeps those
  agents stubbed until box 2 exists.

## What's stubbed / needs you (gaps to fill)

- **Code-acting agents** — the tool-use backend (`agents/tooluse.py`) that runs them
  is **built + live-verified** (e.g. `validate` really runs the test suite). What's
  still gated: **writes are off** and there's **no box 2**, so `implement` can't yet
  safely mutate code — the full pipeline keeps these stubbed (`orchestrator.py`
  `CODE_ACTING`) until box 2 exists. Wiring `tool_backend` into the live pipeline is
  the box-2 step.
- **box-1 / box-2 + git promotion — Stage 1 BUILT** (`workspace.py` + `build_loop.py`):
  the feature→release loop (cut an isolated worktree, write code in it, commit, deploy
  to a box-2 clone, validate, merge to release) runs + is unit-tested on **one
  machine**. **Stage 2 (what you provision):** a real box-2 VM (full Skipper + its own
  Postgres + ssh + a browser) for live Playwright validation + the Pi canary. The
  real adapters (`implement_with_agent`, `validate_with_tests`) are wired; graduating
  box 2 to an ssh remote needs no logic change. Still pending: `implement` with writes
  ON against a real spec (safe in the worktree, but exercised once box 2 is up), and
  `fix-retest-loop`.
- **Platform integration** — `manifest.yaml` + `migrations/` are written but not
  loaded; `PostgresBackend` (store.py) is a stub; the orchestrator isn't yet wired as
  a background loop. Marked `TODO(integration)`.
- **GitHub connector** (intake) and the **Evolve app UI** (work queue) — not started.
- **Charter** — vision-fit invents Skipper's identity without one (the live demo
  showed this). A real charter doc is needed; see EVOLVE.md §11.

## How to run

A throwaway venv with the Anthropic SDK lives at `/tmp/evolve-venv` (system
site-packages, so it has pyyaml). The pure substrate needs only system `python3`.

```bash
# offline test suite (no network, no key) — 45 tests
python3 -m unittest discover -s tests/evolve

# validate + project the C/F/S tree
python3 -m apps.evolve.schema specs/evolve
python3 -m apps.evolve.store  specs/evolve     # projects to SQLite + prints the tree
python3 -m apps.evolve.variance specs/evolve   # 0 variances (fully reconciled)

# load + walk the process model
python3 -m apps.evolve.engine.model specs/evolve/sdlc.yaml

# LIVE: walk a work-item through the swarm (needs ANTHROPIC_API_KEY in .env; ~$0.023 on Haiku)
/tmp/evolve-venv/bin/python -m apps.evolve.orchestrator

# LIVE: the gated agent test
EVOLVE_LIVE_TESTS=1 /tmp/evolve-venv/bin/python -m unittest tests.evolve.agents.test_runner
```

**Cost:** a full pipeline walk is ~$0.023 on Haiku (`fast` tier). Model tiers are
env-overridable (`EVOLVE_MODEL_FAST/SMART/DEEP`) and capped by a runner budget.

## The live demo result (auto "Edit button" issue)

Walked `s_issue → e_done` through real Claude agents: triage classified it (bug, with
a charter), prioritize scored 72/surface, the 5-way review fan-out ran, and
**spec-audit caught ~7 genuine soundness gaps** (missing permission/error/cancel
states, ambiguous resolution, lifecycle preconditions) — the "think outside the box"
behavior working. Reviews → Gate 1 → (stubbed build) → Gate 2 → merge → done.

## Graduating Stage 1 → box 2 (when the VMs are ready)

The mechanics are done; standing up real box 2 is a swap, not a rewrite:

1. **box 1** holds the repo with `main` + a `release` branch (cut `release` off `main`
   once). The brain runs `main`; `WorkspaceManager` cuts feature worktrees off `release`.
2. **box 2** = a VM with a full Skipper install + its own Postgres + ssh from box 1 +
   a headless browser. Point `box2_deploy`/`box2_reset` at it (clone over ssh instead
   of a local path — same git commands).
3. Flip `implement` to run for real: `build_loop.implement_with_agent(...)` with the
   feature worktree as `cwd` and writes ON (already safe — the worktree is isolated).
4. Replace `validate_with_tests` (deterministic unit run) with a box-2 run that also
   drives **Playwright** against the live app for UI specs.
5. Add the `fix-retest-loop` (gw_tests retry within budget) and wire the orchestrator's
   `system` nodes to `WorkspaceManager` so a gated work-item flows end to end.

## Next build steps (in order)

1. **box 2 graduation** (above) → real `implement`/`validate` on a gated work-item.
2. The GitHub connector (intake) so real issues/PRs flow in.
3. Platform integration: load the app, wire `PostgresBackend` + the orchestrator loop.
4. The Evolve app UI (work queue) so gates surface to you.
