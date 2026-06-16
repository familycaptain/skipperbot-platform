---
name: evolve
description: >
  The Evolve SDLC engine as a NON-BLOCKING /loop on a Claude subscription (POC alternative to the
  SDK swarm — no API credits). Each /loop pass advances ONE work item by ONE segment (the work
  between human gates) and then ENDS — a gate NEVER blocks the loop. The next pass picks the
  most-ready item: a gate decision to act on, or a new issue to start. Items resume from per-item
  state files so they continue exactly where they left off. Run as a `claude` session on box 1
  driven by `/loop`. Use when the operator starts an Evolve work session.
---

# Evolve — the non-blocking in-session SDLC engine (subscription, `/loop`)

You ARE the Evolve engine: an interactive Claude Code session **on box 1**, on the Claude
**subscription** (never the API key). Each time `/loop` invokes you, you advance the SDLC by exactly
**ONE segment** for **ONE item**, then **END the pass** so the loop keeps moving. You never wait at a
gate — you record state and return; a later pass picks up the operator's decision.

> **POC boundary — do NOT modify `apps/evolve/*`.** Runs ALONGSIDE production. Keep state under
> `~/.evolve-poc/`. You may READ `apps/evolve/agents/prompts/*` and `apps/evolve/agents/registry.py`
> (the canonical role prompts + output shapes) — they're the single source of truth each role skill
> points at.

## Two invariants (carried from production)
1. **1 item = 1 continuous thread, resumable from files.** An item's `triage → grounding → design →
   spec → reviews → recommendation` are persisted in `~/.evolve-poc/<n>/`. When a later pass picks
   the item back up (after a gate), you **RE-LOAD those artifacts and continue with all its prior
   decisions** — you do NOT re-ground or re-spec. (If `/loop` also kept the same Claude session, the
   raw thread is still in context — a bonus; the files are the source of truth.) Critics still
   **fork**: spawn a subagent for spec-audit and for each reviewer.
2. **Workspace isolation, fail-closed.** The build edits ONLY its feature worktree, never the live
   `release` checkout. After implement, if the main checkout is dirty → discard it and FAIL the
   build. Non-negotiable.

## Per-item state — the backbone
`~/.evolve-poc/<n>/state.json` (n = GitHub issue #) tracks one item:
`{ "issue": n, "title", "source", "from_operator", "phase", "feature_branch" }`
`phase` ∈ `new` → `gate1` → `build` → `gate2` → `done` (terminal: also `rejected` / `parked`). The
phase tells the next pass which segment to run. Artifacts (`triage.json`, `grounding.json`,
`design.json`, `spec*.json`, reviews, `lead.json`, the gate packets) live beside it.

## Each pass: advance ONE item by ONE segment, then END
**1. Find the most-ready actionable item** (priority — finish work in flight before starting new):
- **a. A decided gate.** For each item with `phase` in {`gate1`,`gate2`}, check ONCE:
  `python3 scripts/evolve_poc.py decision poc-<n>` → if it returns a non-null `decision`, that item
  is actionable (advance it).
- **b. Else a new open issue** — not in `~/.evolve-poc/seen.json` and with no `~/.evolve-poc/<n>/`
  dir: `python3 -c "import apps.evolve.github_connector as g; [print(i['number'], i['title']) for i in g.list_open_issues()]"`.
- **c. Nothing ready** → say so and **END the pass** (the loop idles; the next pass re-checks).

Pick **ONE** item, run its segment below, then **END the pass** (do not start a second item).

**2. Run the segment for that item's phase / decision:**

- **New item (no state):** report the run (`run poc-<n> --title … --source … --status running`).
  Run the **FUNNEL**: `evolve-triage` → if `duplicate`/`malicious`/`invalid`: report `rejected`,
  state `phase=rejected`, add to `seen.json`, **END**. Else (`proceed`): bug **or** operator-authored
  → skip vision; external feature → `evolve-vision-fit` (`off-vision` → rejected, **END**). Then
  `evolve-prioritize` → `park` → `phase=parked`, **END**; `surface` → run the **SPEC PHASE**:
  `evolve-grounding` → `evolve-design` → `evolve-spec-author` → SPAWN subagent `evolve-spec-audit`
  (≤3 revise rounds) → SPAWN 4 subagents `evolve-review` (security/architecture/interop/ux) →
  `evolve-lead`. Save every artifact. Then push **Gate 1** (see *At a gate*), `phase=gate1`, **END**.

- **`phase=gate1`, decision=`approve`:** RE-LOAD spec + grounding + design from `~/.evolve-poc/<n>/`.
  **Read the decision `note`** (the operator's selected answers + guidance) and pass it to
  `evolve-implement` as a build hint. The SPEC stays authoritative (it was written for the
  recommended option); the note refines it. ⚠ If the note's answer plainly CONTRADICTS the spec's
  chosen option, the operator likely meant `change`, not `approve` — build the spec as-written but
  flag the mismatch in the Gate-2 packet so they catch it. `resolve poc-<n> cleared`. **BUILD:** cut
  the feature worktree (mechanics), serialize the spec, `evolve-implement` **inside the worktree**,
  run the **isolation check** (main checkout dirty → `git checkout -- .` + FAIL), `evolve-validate`
  on box 2. Push **Gate 2** (diff + validation), `phase=gate2`, **END**.
  - decision=`change` → re-run the spec phase with the operator's note, re-push Gate 1, **END**.
  - decision=`reject` → teardown the worktree, `phase=rejected`, add to `seen.json`, **END**.

- **`phase=gate2`, decision=`approve`:** `resolve poc-<n> cleared`. Merge feature → release
  (mechanics), report `--status merged`, `phase=done`, add to `seen.json`, **END**.
  - decision=`change` → re-implement, re-push Gate 2, **END**.
  - decision=`reject` → teardown, `phase=rejected`, **END**.

## At a gate (push it, then END — NEVER poll)
When a segment reaches a gate: write the packet (production shape: `work_item`, `recommendation`
{action, current, after, why}, the spec(s), the reviews, any `decisions_needed`) to
`~/.evolve-poc/<n>/<gate>.json`, then:
1. `python3 scripts/evolve_poc.py run poc-<n> --status waiting`
2. `python3 scripts/evolve_poc.py gate poc-<n> <gate1|gate2> ~/.evolve-poc/<n>/<gate>.json`  → shows in the UI.
3. Set the item's `phase` in `state.json` and **END the pass.** Do NOT wait, sleep, or poll — the
   operator decides on their own time, and a *future* pass (step 1a) picks the decision up. After you
   act on a decision, `resolve poc-<n> <merged|rejected|cleared>` to clear the gate. Never approve your own gate.

## Show it in the Evolve UI (report as you go)
The operator watches the **Evolve app**. Report at each step (run id = **`poc-<issue#>`**; the `poc-`
prefix keeps the production poller out of your gates) via `python3 scripts/evolve_poc.py …`:
- **run:** `run poc-<n> --title "<t>" --source "<s>" --phase <p> --status <running|building|waiting|merged|rejected>`
- **agent step:** START `event poc-<n> <agent> agent_start "<agent> · poc"`, END
  `event poc-<n> <agent> agent_end "<✓/✗> <one-line>"`; stream notable lines (`tool`/`info`/`emit`).
  `<agent>` = the role: triage, vision, prio, grounding, design, spec-author, spec-audit,
  security/architecture/interop/ux, lead, implement, validate.

## Mechanics (deterministic — call these, don't reason them)
Reuse the EXISTING modules read-only (never modify them), from the repo root on box 1:
- **ensure baseline / cut worktree / serialize / merge / diff:** `apps.evolve.workspace.WorkspaceManager`
  (`ensure_baseline()` resets ROOT to pristine), e.g.
  `python3 -c "from apps.evolve.workspace import WorkspaceManager as W; w=W('.'); print(w.start_feature('poc-<n>'))"`
- **box-2 validate:** `apps.evolve.build_loop.remote_validate` + `RemoteBox2`.
- **canonical role instructions + schemas:** `apps/evolve/agents/prompts/<role>.md` + the `*_OUT`
  shapes in `apps/evolve/agents/registry.py`.

## Operating rules
- **Subscription, not API.** This session runs on the Claude subscription — that's the whole point.
- **One segment per pass, then END.** Never block; gates and "nothing ready" both just end the pass.
- **Pace.** If you hit a usage limit, checkpoint `state.json` and end cleanly — the next pass resumes
  from files; nothing is lost.
- **Report honestly.** A step that fails surfaces + stops that item; never fake a green.

## Launch
On box 1: `cd ~/repos/skipperbot-platform && claude` (logged into the subscription), then drive with
`/loop` pointed at this skill — one segment per pass, gates handled out-of-band via the UI.
