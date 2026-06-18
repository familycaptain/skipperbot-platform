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
`{ "issue": n, "instance_id", "title", "source", "from_operator", "phase", "feature_branch" }`
**The run id is `ev-<issue#>`** — write it as `instance_id` when you create the item and reuse that
EXACT value on every later pass (one item, one id for life). Read the id from `state.json.instance_id`;
do NOT reconstruct it. **Legacy items created before the `poc-`→`ev-` rename keep their `poc-` id** —
their `state.json` either carries it as `instance_id` or, if absent, defaults to `poc-<n>`; honor
whatever they already use so an in-flight item is never orphaned by the rename. (The state dir
`~/.evolve-poc/` and the `scripts/evolve_poc.py` helper keep their names — internal plumbing; only the
operator-visible run id changed.)
`phase` ∈ `new` → `gate1` → `build` → `gate2` → **`verify`** → `done` (terminal: also `rejected` /
`parked`). The phase tells the next pass which segment to run. Artifacts (`triage.json`,
`grounding.json`, `design.json`, `spec*.json`, reviews, `lead.json`, the gate packets) live beside it.
**Merge is NOT done.** A Gate-2 approve merges to release but the item goes to `verify`: the operator
deploys to their Pi, tests it, and only then confirms ✓works (→ done, close the GitHub issue) or
✗broken (→ resume the SAME conversation with their failure note, fix, re-validate, re-merge). The
GitHub issue stays OPEN until verified — an open issue means "not confirmed working yet."

## Each pass: advance ONE item by ONE segment, then END
**1. Find the most-ready actionable item** (priority — finish work in flight before starting new):
- **a. A decided gate.** For **every** item dir under `~/.evolve-poc/*/` — *including `done` ones*, a
  done item can be re-opened at the verify gate from the UI ("Didn't work") — check ONCE using the
  item's stored id: `python3 scripts/evolve_poc.py decision <state.json instance_id>` (an `ev-<n>`, or a
  legacy `poc-<n>`). If it returns a non-null `decision`, that item is
  actionable. **Route on the returned `gate`** (`gate1`/`gate2`/`gate3`), NOT the local phase — the UI
  gate is authoritative; a re-opened `done` item comes back as a decided `gate3`. Reconcile
  `state.json` `phase` to match the gate before running the segment (`gate3` → `verify`).
- **b. Else a new open issue** — not in `~/.evolve-poc/seen.json` and with no `~/.evolve-poc/<n>/`
  dir: `python3 -c "import apps.evolve.github_connector as g; [print(i['number'], i['title']) for i in g.list_open_issues()]"`.
- **c. Nothing ready** → say so and **END the pass** (the loop idles; the next pass re-checks).

Pick **ONE** item, run its segment below, then **END the pass** (do not start a second item).

**2. Run the segment for that item's phase / decision:**

- **New item (no state):** write `state.json` with `instance_id: "ev-<n>"`, then report the run
  (`run ev-<n> --title … --source … --status running`). Run the **FUNNEL**: `evolve-triage`. **Operator-authored items (`from_operator`) are NEVER
  rejected — the operator is the authority.** Even if triage flags `duplicate`/`invalid`/out-of-scope,
  do NOT reject: proceed, and carry triage's `summary`/`rationale` forward as a prominent
  operator-facing note so it surfaces at **Gate 1** for the operator to decide (redirect, accept an
  in-scope reframe, or reject it themselves). Triage rejection applies ONLY to PUBLIC (non-operator)
  items: `duplicate`/`malicious`/`invalid` → report `rejected`, `phase=rejected`, add to `seen.json`,
  **END**. **Check `belongs_to`:** if it is an external app-package (not `platform`), the fix lives in
  another repo Evolve here can't build/validate yet (multi-repo, #31). Do NOT grind the spec phase on
  it — push a Gate-1 packet that states the fix `belongs_to: <repo>`, includes triage's in-scope angle
  (if any), and asks the operator to decide (handle it in that repo, pursue an in-scope **platform**
  reframe instead, or drop it); `phase=gate1`, **END**. Only items whose fix is `platform` continue.
  Proceeding: bug **or** operator-authored → skip vision; external feature →
  `evolve-vision-fit` (`off-vision` → rejected, **END**, *public items only*). Then
  `evolve-prioritize` → `park` → `phase=parked`, **END**; `surface` → run the **SPEC PHASE**:
  `evolve-grounding` → `evolve-design` → `evolve-spec-author` → **`evolve-code-scout`**
  (read-only: sketch WHAT code would change — files/areas, add/modify/rewrite, where new logic lives —
  writing NO code; save as `code_plan.json`) then SPAWN subagent `evolve-spec-audit`
  (≤3 revise rounds) → SPAWN 4 subagents `evolve-review` (security/architecture/interop/ux) —
  **pass the `code_plan` to the architecture reviewer** so it audits the PLANNED placement against the
  one-directional dep rule (catches "rewrite the zip lookup inside `apps/weather`" at the gate, before
  the build) then `evolve-lead` (weigh the `code_plan` + any architecture concern in the recommendation).
  Save every artifact. Then push **Gate 1** (see *At a gate*), `phase=gate1`, **END**.

- **`phase=gate1`, decision=`approve`:** RE-LOAD spec + grounding + design from `~/.evolve-poc/<n>/`.
  **Read the decision `note`** (the operator's selected answers + guidance) and pass it to
  `evolve-implement` as a build hint. The SPEC stays authoritative (it was written for the
  recommended option); the note refines it. ⚠ If the note's answer plainly CONTRADICTS the spec's
  chosen option, the operator likely meant `change`, not `approve` — build the spec as-written but
  flag the mismatch in the Gate-2 packet so they catch it. `resolve ev-<n> cleared`, then
  **IMMEDIATELY** `run ev-<n> --status building --phase build` so the UI shows it ACTIVELY building
  (not stuck on the operator-side "queued/approved" chip) — do this BEFORE any build work. **BUILD:**
  cut the feature worktree (mechanics), serialize the spec, `evolve-implement` **inside the worktree**,
  run the **isolation check** (main checkout dirty → `git checkout -- .` + FAIL). **Then the
  dependency-rule guard:** `python3 scripts/evolve_dep_check.py <worktree-path> release` — if it
  reports violations (the change made the **platform import an app**, or **one app import another**),
  the build introduced a structural break: include the violations PROMINENTLY in the Gate-2 packet as
  an architecture concern and set the Lead recommendation to `change` with the fix (move the shared
  code into the platform) — never hand the operator a clean "approve" over a dependency-rule break.
  `evolve-validate` on box 2. **When validate is GREEN**, set `verified: true` on each spec the change
  proved with a passing bound test (edit the spec YAML in the worktree so it merges with the
  code+test) — that graduates it from unverified baseline to an authoritative, code-governing contract.
  Push **Gate 2** (diff + validation + the dep-check result), `phase=gate2`, **END**.
  - decision=`change` → re-run the spec phase with the operator's note, re-push Gate 1, **END**.
  - decision=`reject` → `resolve ev-<n> rejected` (clears gate + sets run rejected), teardown the
    worktree, `phase=rejected`, add to `seen.json`, **END**.

- **`phase=gate2`, decision=`approve`:** Merge feature → release (mechanics), then
  **`resolve ev-<n> shipped`** (clears the gate + flips the run to **waiting / verify**). Push a
  **Gate 3 (verify)** packet — `recommendation` = {action:`verify`, why: "Merged to release as
  `<sha>`. Deploy to your Pi (`skipper update`) and test issue #<n>: <what to check>", current,
  after} — set `state.json` `phase=verify`, **END**. (The GitHub issue stays OPEN; do NOT mark done
  or seen yet.) **ALWAYS spell out any USER ACTION required to observe the fix** in the `why` — a
  correct change can look broken until the operator does it: **re-login** (auth/session/cookie changes —
  a stale browser session won't have the new cookie), **reconfigure** a Setting, **clear cache / hard
  refresh** (UI bundle), reinstall an app package, etc. The implement/lead notes should carry this
  forward; if the diff touches auth/cookies/session, login, config schema, or the web bundle, name the
  step explicitly.
  - decision=`change` → re-implement, re-push Gate 2, **END**.
  - decision=`reject` → teardown, then `resolve ev-<n> rejected` (clears gate + sets run rejected),
    `phase=rejected`, add to `seen.json`, **END**.

- **`phase=verify`, decision=`approve` (✓ it works):** the loop is done. `python3
  scripts/evolve_poc.py close ev-<n> "Verified working — closing. (Evolve)"` (closes the GitHub
  issue), then `resolve ev-<n> merged` (clears gate + flips run to **merged / done**), set
  `state.json` `phase=done`, add to `seen.json`, **END**.
  - decision=`change` (✗ still broken): the decision `note` is the operator's failure report. **RESUME
    THE SAME CONVERSATION** (re-load this item's grounding/design/spec/build artifacts; do NOT
    re-ground from scratch). **First judge the DEPTH of the fix** (act as Design/Lead) — this decides
    where it re-enters:
    - **Localized bug** — the approach + spec are still right, the *code* was wrong. `resolve ev-<n>
      cleared`, re-cut/locate the worktree, `evolve-implement` the fix, **update the spec's
      `behavior`/`tests` if the behavior shifted at all** (the spec must always match what's built),
      isolation check, `evolve-validate`, re-push **Gate 2**, `phase=gate2`, **END**.
    - **New approach** — the failure shows the *approach itself* was wrong, so the agents change the
      plan. You CANNOT skip to a code patch: re-enter the **SPEC PHASE** so the new way is documented
      and re-reviewed. `evolve-design` (re-frame with the failure as input → new approach + tech
      choices) → `evolve-spec-author` (**REWRITE** the spec(s) to the new way) → **`evolve-code-scout`**
      (re-sketch the code footprint for the new approach) → SPAWN
      `evolve-spec-audit` → SPAWN the 4 `evolve-review` lenses (re-review the NEW design,
      architecture lens gets the new `code_plan`: security/architecture/interop/ux) → `evolve-lead`.
      Re-push **Gate 1** (the intent/approach
      changed — it needs re-approval), `phase=gate1`, **END**. It then flows Gate 1 → build → Gate 2
      → verify as normal.
    **Routing rule:** if the fix changes the **approach, the behavior contract, or a load-bearing tech
    choice** → it's a new approach → spec phase + **Gate 1**. Only a code-level bug *under an unchanged
    spec* skips ahead to re-implement → Gate 2. **Never leave the spec describing a way you no longer
    build** — a stale spec is itself a defect (the architecture reviewer will flag it).
  - decision=`reject` (abandon): `resolve ev-<n> rejected`, teardown, `phase=rejected`, seen, **END**.
    (Leave the GitHub issue open or comment — do not close an abandoned item as resolved.)

## At a gate (push it, then END — NEVER poll)
When a segment reaches a gate, write the packet to `~/.evolve-poc/<n>/<gate>.json` **in the exact
shape the UI panels render** (so the operator sees the ACTUAL spec + reviews, not a summary):
- `work_item` {number, title, body}
- `recommendation` {action: approve|change|reject, current, after, why} — the Lead's call.
- `proposal` — the spec-author's FULL output object: {spec_id, title, behavior, implements,
  tests:[{type, path, rubric}], notes}. The **"Proposed spec"** panel renders this verbatim.
- `spec_tree` — a JSON **array** of specs `[{spec_id, title, summary}, …]` when the design
  decomposed into a tree. For a single spec, **OMIT the key entirely** — do NOT write a string
  (e.g. `"[proposal]"`); the UI calls `.map()` on it and a string crashes the panel.
- `code_plan` — the Code Scout's read-only sketch: {summary, approach, changes:[{path, action, what}],
  new_modules, placement_notes, risks, open_questions}. The **"Planned code changes"** panel renders it
  so the operator sees the change's code footprint (which files, add/modify/**rewrite**, where new logic
  lands) BEFORE approving — not just the spec. Gate 1 only.
- `decisions_needed` — the design's human forks, each {question, recommendation, options:[…]}.
- `agents` — one entry **per role** `{key, label, output}` where `output` is that role's full
  structured result (spec-audit `findings`, each reviewer's `concerns`/`conflicts`, lead arbitration).
  **"The team"** panel renders each agent's full detail from this.
- Gate 2 also: `diff` (the full patch), `validation` {passed, reason}, `feature` {branch}.
- **Gate 3 (verify)** is lighter: `work_item`, `feature` {branch, sha}, and a `recommendation`
  whose `why` tells the operator exactly what to deploy + test (`gate: "gate3"`). The UI relabels
  the buttons to ✓Works / Still-broken / Abandon automatically.
Then:
1. `python3 scripts/evolve_poc.py run ev-<n> --status waiting`
2. `python3 scripts/evolve_poc.py gate ev-<n> <gate1|gate2> ~/.evolve-poc/<n>/<gate>.json`  → shows in the UI.
3. Set the item's `phase` in `state.json` and **END the pass.** Do NOT wait, sleep, or poll — the
   operator decides on their own time, and a *future* pass (step 1a) picks the decision up. After you
   act on a decision, `resolve ev-<n> <merged|rejected|cleared>` to clear the gate. Never approve your own gate.

## Show it in the Evolve UI (report as you go)
The operator watches the **Evolve app**. Report at each step (run id = **`ev-<issue#>`**; the `ev-`
prefix keeps the production poller out of your gates — legacy `poc-` ids are also excluded) via
`python3 scripts/evolve_poc.py …`:
- **run:** `run ev-<n> --title "<t>" --source "<s>" --phase <p> --status <running|building|waiting|merged|rejected>`
- **agent step:** START `event ev-<n> <agent> agent_start "<agent> · evolve"`, END
  `event ev-<n> <agent> agent_end "<✓/✗> <one-line>"`; stream notable lines (`tool`/`info`/`emit`).
  `<agent>` = the role: triage, vision, prio, grounding, design, spec-author, code-scout, spec-audit,
  security/architecture/interop/ux, lead, implement, validate.
- **show the ACTUAL work, not just a one-liner.** The log renders full, untruncated text — so after
  a substantive step, surface its FULL content: after `spec-author` (AND each revise round) the
  complete spec (behavior + every test + notes); after each reviewer its full findings; after `lead`
  the full recommendation; the build diff. Never summarize the detail away.
  - **Emit big content BY FILE, not inline** (token economy): you already wrote these as artifacts in
    `~/.evolve-poc/<n>/` — surface them with `emit-file` so the full text is read+posted by the script
    and does NOT also sit in your conversation context: `python3 scripts/evolve_poc.py emit-file ev-<n>
    spec-author ~/.evolve-poc/<n>/spec.json`. Reserve inline `event … emit "<text>"` for short notes.

## Mechanics (deterministic — call these, don't reason them)
Reuse the EXISTING modules read-only (never modify them), from the repo root on box 1:
- **ensure baseline / cut worktree / serialize / merge / diff:** `apps.evolve.workspace.WorkspaceManager`
  (`ensure_baseline()` resets ROOT to pristine), e.g.
  `python3 -c "from apps.evolve.workspace import WorkspaceManager as W; w=W('.'); print(w.start_feature('ev-<n>'))"`
- **box-2 validate:** `apps.evolve.build_loop.remote_validate` + `RemoteBox2`.
- **canonical role instructions + schemas:** `apps/evolve/agents/prompts/<role>.md` + the `*_OUT`
  shapes in `apps/evolve/agents/registry.py`.

## Operating rules
- **Subscription, not API.** This session runs on the Claude subscription — that's the whole point.
- **One segment per pass, then END.** Never block; gates and "nothing ready" both just end the pass.
- **Token economy — the conversation is disposable between passes.** Files are truth (invariant #1): a
  pass re-hydrates everything it needs from `~/.evolve-poc/<n>/`, so the chat history carried between
  passes is a *cache, not the source*. Keep each pass lean: load ONLY what THIS segment needs, surface
  big artifacts with `emit-file` (not inline), and don't re-read items/artifacts you aren't acting on.
  - **Compaction is automatic** (`autoCompactEnabled` is on — pinned in `.claude/settings.json`); the
    model cannot self-trigger `/compact` and `/loop` has no per-iteration reset, so auto-compaction is
    the safety net. For a *hard, lossless* reset the **operator** can, between passes, run `/clear`
    then re-invoke `/loop` at this skill — the loop rebuilds state from files (nothing is lost), or
    `/compact` to keep a summary. This is the lowest-token way to run long sessions; it's an operator
    action, not something a pass does to itself.
- **Pace.** If you hit a usage limit, checkpoint `state.json` and end cleanly — the next pass resumes
  from files; nothing is lost.
- **Report honestly.** A step that fails surfaces + stops that item; never fake a green.
- **The Pi being down is NOT fatal.** The operator restarts the Pi to test changes (`skipper update`).
  When it's unreachable: `decision` reads return no decisions (handled — `list_decided` yields `[]`),
  and every status/gate write **buffers to the box-1 outbox** and flushes in order when the Pi is back.
  So a Pi outage only pauses *gated-item advancement* for a minute — new GitHub issues still come from
  GitHub and can be worked (box 1 + box 2 need no Pi until reporting, which buffers). **Never stop or
  crash the loop because the Pi is down** — degrade, keep going, reconcile on a later pass.
  - **Flush-first every pass.** The decided-gate scan at the start of a pass (step 1a, `decision …`)
    now **drains the outbox before reading** (`list_decided` calls `_flush` first). This guarantees a
    report buffered while the Pi was down goes out on the very next pass **even for a PARKED item whose
    own pass does no write** — e.g. a Gate-2 push buffered mid-`skipper update`, where the item is then
    parked at Gate 2 and the loop goes idle. Without this, that report could strand until some *other*
    item happened to write. If you ever see a run stuck mid-segment on the Pi after a restart while box
    1 is actually done, force it: `python3 scripts/evolve_poc.py flush`.

## Launch
On box 1: `cd ~/repos/skipperbot-platform && claude` (logged into the subscription), then drive with
`/loop` pointed at this skill — one segment per pass, gates handled out-of-band via the UI.
