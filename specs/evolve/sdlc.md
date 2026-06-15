# Evolve — SDLC process flow (v0.4.0)

> **Generated view.** The source of truth is [`sdlc.yaml`](./sdlc.yaml); this
> Mermaid is the picture of it. Open this file in GitHub (or VS Code preview /
> mermaid.live) to see the graph. See [`../EVOLVE.md`](../EVOLVE.md) for the design.

**Legend:** 🟦 event (incl. cadence triggers) · 🟩 agent (one specialized agent
each) · 🟪 system (deterministic automation, no LLM) · 🟨 human gate · 🟥 gateway
(branch/join). Dashed edge = the variance fast-path.

```mermaid
flowchart TD
  %% intake: two reactive (both pulled from GitHub by one connector)
  s_issue(["GitHub issue — reactive"]):::event --> triage
  s_pr(["GitHub PR — reactive"]):::event --> triage

  %% intake: proactive A — Design (new features)
  gen_design["Design agent (cadence): propose features"]:::agent --> lead

  %% intake: proactive B — QA / bug-discovery (code AND spec defects)
  qa_sweep(["QA sweep (cadence)"]):::event --> qa_var["Variance/drift detector — code vs approved spec"]:::agent
  qa_sweep --> qa_reg[["Run regression suite"]]:::sys
  qa_sweep --> qa_audit["Code-audit — bugs, edge cases, security"]:::agent
  qa_sweep --> qa_spec["Spec-audit — gaps/holes/naive assumptions in existing C/F/S"]:::agent
  qa_var --> qa_join{{"join findings"}}:::gw
  qa_reg --> qa_join
  qa_audit --> qa_join
  qa_spec --> qa_join
  qa_join --> s_bug(["QA finding (bug or spec-gap)"]):::event
  s_bug --> triage
  qa_var -. "fast-path: pure variance" .-> prio

  %% triage / vision
  triage["Triage: bug/feature, dedup, link"]:::agent --> gw_kind{"bug or feature?"}:::gw
  gw_kind -->|bug| lead
  gw_kind -->|feature| vision["Vision-fit — charter + Capability scope"]:::agent
  vision --> gw_vision{"fits vision?"}:::gw
  gw_vision -->|off-vision| e_rejected(["Rejected"]):::event
  gw_vision -->|fits| lead

  %% Spec phase: the LEAD runs an agentic inner loop INSIDE this one node
  %% (Design → spec-author ⇄ spec-auditor, bounded rounds → Security/Arch/Interop/UX),
  %% arbitrates, and owns the proposal + the Gate-1 recommendation.
  lead["<b>Lead</b> — Design → Spec-author ⇄ Spec-auditor (+ Security / Arch / Interop / UX), arbitrate, recommend"]:::agent --> prio["Prioritize (backlog-PM)"]:::agent
  prio --> gw_prio{"surface or park?"}:::gw
  gw_prio -->|"park (low-pri)"| e_parked(["Parked / declined"]):::event
  gw_prio -->|"top-N / critical"| gate1

  gate1[/"GATE 1 — approve intent"/]:::gate
  gate1 -->|"change this"| lead
  gate1 -->|reject| e_rejected
  gate1 -->|approve| serialize[["Serialize spec to file (branch)"]]:::sys

  serialize --> impl["Implement code (or canonicalize PR)"]:::agent
  impl --> tests["Author/update tests"]:::agent
  tests --> deploy[["Box 2: pull branch + restart"]]:::sys
  deploy --> validate["Validate on box 2 (Playwright)"]:::box2
  validate --> gw_tests{"tests green?"}:::gw
  gw_tests -->|"failing, retry within budget"| impl
  gw_tests -->|"stuck, escalate"| gate2
  gw_tests -->|green| packet["Build review packet"]:::agent
  packet --> gate2

  gate2[/"GATE 2 — approve result"/]:::gate
  gate2 -->|"change this"| impl
  gate2 -->|reject| e_rejected
  gate2 -->|approve| merge[["Auto-merge to release branch"]]:::sys
  merge --> resync[["Re-sync files to DB"]]:::sys
  resync --> e_done(["Merged to release — awaiting operator publish"]):::event

  classDef event fill:#e8eef7,stroke:#5b7aa7,color:#1b2b44;
  classDef agent fill:#eaf6ec,stroke:#4c9a5a,color:#16331e;
  classDef sys fill:#f3eefc,stroke:#8a6bbf,color:#2c1f44;
  classDef gate fill:#fdf1d6,stroke:#caa23a,color:#4a3a0e;
  classDef gw fill:#fdeaea,stroke:#cc6666,color:#4a1616;
  classDef box2 fill:#e6f7f8,stroke:#3fa6ad,color:#0e3b3e;
```

### Reading it

- **Four intake lanes — two reactive, two proactive:**
  - **Reactive:** *GitHub issues* and *PRs* (one connector, no in-app tracker) → **Triage**.
  - **Proactive A — Design agent (cadence):** generates new-feature proposals from
    the charter + request clusters + C/F/S coverage gaps → enters at the **Lead**
    (already vision-aligned).
  - **Proactive B — QA / bug-discovery (cadence):** a *separate* system running four
    detectors in parallel — **variance/drift** (code vs. approved spec), the
    **regression suite**, a **code-audit** agent (defects in the *code*), and a
    **spec-audit** agent (gaps/holes/naive assumptions in the *C/F/S* itself) —
    whose findings become **bug or spec-gap** work items → **Triage**.
- **Variance fast-path** (dashed): a *pure* code-vs-approved-spec drift skips
  Spec-author **and** Gate 1 (the intent was approved when the spec was) → straight
  to **Prioritize**, then implement → validate → Gate 2.
- **Vision-fit** judges against the **platform charter + the target Capability's
  scope** (help.md/guide.md are inputs, not the authority).
- **Prioritize** is the attention valve: long tail *parked/declined* (recorded);
  only **top-N or safety-critical** continue.
- **The Lead owns the spec phase** (an agentic inner loop inside the deterministic
  walk). It runs **Design** (how should it work — reframes the ask, sets the approach,
  honors the engineering principles), then iterates **Spec-author ⇄ Spec-auditor** in
  **bounded** rounds (a stuck negotiation *escalates* to the human rather than spinning),
  brings in **Security / Architecture / Interop / UX**, **arbitrates**, and is the single
  agent that hands the human a synthesized **proposal + recommendation** at Gate 1. Every
  agent (the Lead included) emits a plain-language `summary` and gets its own UI panel.
- **Gate 1** (approve intent) → autonomous **implement + author tests** on the box-1
  branch → **box 2** validates with Playwright → loop **failing→retry** / **stuck→
  escalate** / **green→packet** → **Gate 2** → **auto-merge to the `release` branch**
  → **re-sync**. Both gates can **bounce back** ("change this").
- **The build half fails closed (#29).** A change reaches a *green* Gate 2 only when the
  implement agent actually changed code **and** included a runnable **bound test**, and
  box 2 ran *that* test (not the engine's own suite) and it passed. A failed/empty/untested
  implement, or red bound tests, never green — it lands at Gate 2 with a `change`
  recommendation that names the reason, so a broken build can't be auto-approved.
- **The per-change process ends at `release`, not `main`.** Promotion `release →
  main` (publish to the world) is a separate, operator-owned **release gate** —
  batched over many completed instances and canaried on the Pi — so it lives outside
  this per-change graph (EVOLVE.md §5/§9).
