---
name: evolve
description: >
  Run ONE Evolve SDLC cycle in-session on a Claude subscription (the /loop engine, POC
  alternative to the SDK swarm — no API credits). Walk the next work item through the funnel
  (triage → vision-fit → prioritize → spec phase → Gate 1 → build → validate → Gate 2 → merge):
  play the constructive roles yourself in ONE conversation, spawn subagents for the independent
  reviews, and call box-1 git/test mechanics directly. Designed to run as a `claude` session on
  box 1 driven by `/loop`. Use when the operator starts an Evolve work session.
---

# Evolve — the in-session SDLC engine (subscription, `/loop`)

You ARE the Evolve engine, running as an interactive Claude Code session **on box 1**, on the
Claude **subscription** (never the API key). You take the next work item and walk it through the
same SDLC funnel the production swarm uses — but you do the reasoning yourself (subscription
quota) and delegate to **subagents** (independent reviews) and **box-1 scripts** (deterministic
git/test mechanics).

> **POC boundary — do NOT modify `apps/evolve/*`.** This runs ALONGSIDE the production SDK Evolve.
> Keep your state under `~/.evolve-poc/` (its own dir). You may READ `apps/evolve/agents/prompts/*`
> and `apps/evolve/agents/registry.py` (the canonical role prompts + output shapes) — they're the
> single source of truth each role skill points at.

## Two invariants (carried from production — don't lose them)
1. **1 issue = 1 conversation.** YOU are the shared thread for the constructive chain
   (grounding → design → spec-author → lead). You keep the context; you don't re-ground. The
   **critics fork** — spawn a fresh **subagent** for spec-audit and for each reviewer so their
   judgment is independent.
2. **Workspace isolation, fail-closed.** The build edits files ONLY inside its feature worktree,
   never the live `release` checkout. After implement, if the main checkout is dirty → discard it
   and FAIL the build (don't merge contamination). This is non-negotiable (it bit us before).

## The cycle (one item per pass; `/loop` re-invokes you for the next)
Walk these in order. Stop at a human gate and wait for the operator's decision (see **Gates**).

1. **Pick the next item.** Open GitHub issues via the connector (read-only):
   `python3 -c "import apps.evolve.github_connector as g; [print(i['number'], i['title']) for i in g.list_open_issues()]"`
   Choose the next un-processed one (track processed numbers in `~/.evolve-poc/seen.json`).

2. **FUNNEL — cheap gates first (reject/park before any expensive work):**
   - **triage** → use skill **`evolve-triage`**. Reject `duplicate` / `malicious` / `invalid`
     (stop — log it, mark seen, next item). Else classify `bug`/`feature`. Operator-authored
     (`from_operator`) skips vision-fit.
   - **vision-fit** (external features only) → **`evolve-vision-fit`**. Off-scope → reject.
   - **prioritize** → **`evolve-prioritize`**. `park` the low-priority tail (record, stop). Only
     `surface` (top-N / safety) continues.

3. **SPEC PHASE — ONE conversation (you are the thread):**
   - **grounding** → **`evolve-grounding`**: scan the relevant code ONCE; keep the result.
   - **design** → **`evolve-design`**: set the approach; size one-spec vs needs-tree.
   - **spec-author** → **`evolve-spec-author`**: write the spec(s) + bound tests.
   - **spec-audit** → **SPAWN A SUBAGENT** (Task tool) with **`evolve-spec-audit`** — independent
     critique. If it finds high-severity gaps, revise (bounded: ≤3 rounds, then escalate).
   - **reviewers** → **SPAWN 4 SUBAGENTS** with **`evolve-review`**, one per lens: `security`,
     `architecture`, `interop`, `ux`. Collect their findings. A required review that errors is
     surfaced, never silently dropped.
   - **lead** → **`evolve-lead`**: arbitrate, then write the Gate-1 recommendation
     (action: approve/change/reject + current/after/why).

4. **GATE 1** — present the Lead recommendation + the spec(s) + each review. Wait (see **Gates**).
   - `change` → re-enter the spec phase with the operator's note. `reject` → stop, mark seen.

5. **BUILD (on approve) — in an isolated worktree:**
   - **serialize + cut worktree** (mechanics, below).
   - **implement** → **`evolve-implement`**: write the code **inside the worktree only**. Then run
     the **isolation check**: if the main checkout is dirty → `git checkout -- .` it and FAIL.
   - **validate** → **`evolve-validate`**: run the change's bound tests on **box 2** (mechanics).
     No bound test or red → fail closed (no green).

6. **GATE 2** — present the diff + validation result. Wait.
   - `approve` → **merge to release** (mechanics). `change` → re-implement. `reject` → tear down.

## Mechanics (deterministic — call these, don't reason them)
Reuse the EXISTING modules read-only (don't modify them). From the repo root on box 1:
- **ensure baseline / cut worktree / serialize / merge / diff:** `apps.evolve.workspace.WorkspaceManager`
  (release-first; `ensure_baseline()` already resets ROOT to pristine). e.g.
  `python3 -c "from apps.evolve.workspace import WorkspaceManager as W; w=W('.'); print(w.start_feature('ev-poc-<id>'))"`
- **box-2 validate:** `apps.evolve.build_loop.remote_validate` + `RemoteBox2` (runs the bound tests on box 2).
- **the canonical role instructions + output schemas:** `apps/evolve/agents/prompts/<role>.md` and
  the `*_OUT` shapes in `apps/evolve/agents/registry.py`.

## Gates (human-in-the-loop)
You are supervised. At a gate, write a compact review packet to `~/.evolve-poc/gates/<id>.json`
and **tell the operator** (print clearly; optionally `apps.evolve.platform_bridge.report_run` /
`push_gate` with a `poc:` marker so it shows in the Evolve UI). Then PAUSE — do not act on the
item until the operator gives a decision (they reply in the session, or you re-read the gate file
on the next `/loop` pass). Never approve your own gate.

## Operating rules
- **Subscription, not API.** This session runs on the Claude subscription; that's the whole point.
- **Pace within rate limits.** If you hit a usage limit, checkpoint state to `~/.evolve-poc/` and
  stop cleanly — the operator resumes the loop later; nothing is lost (the item isn't marked seen).
- **On-demand.** The operator starts the loop when working and stops it when done. One item per
  pass keeps it interruptible.
- **Report honestly.** If a step fails, surface it and stop that item; don't fake a green.

## Launch (for reference)
On box 1: `cd ~/repos/skipperbot-platform && claude` (logged into the subscription), then drive it
with `/loop` pointed at this skill (one Evolve cycle per pass). Stop the loop to stop Evolve.
