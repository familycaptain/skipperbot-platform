# Evolve — SDLC process flow (v0.1)

> **Generated view.** The source of truth is [`sdlc.yaml`](./sdlc.yaml); this
> Mermaid is the picture of it. Open this file in GitHub (or VS Code preview /
> mermaid.live) to see the graph. See [`../EVOLVE.md`](../EVOLVE.md) for the design.

**Legend:** 🟦 event · 🟩 agent (one specialized agent each) · 🟪 system
(deterministic automation, no LLM) · 🟨 human gate · 🟥 gateway (branch/join).

```mermaid
flowchart TD
  s_issue(["Issue — Issues app / GitHub"]):::event --> triage
  s_pr(["PR — community"]):::event --> triage
  s_design(["Design proposal — proactive"]):::event --> spec

  triage["Triage: bug/feature, dedup, link"]:::agent --> gw_kind{"bug or feature?"}:::gw
  gw_kind -->|bug| spec
  gw_kind -->|feature| vision["Vision-fit vs charter"]:::agent
  vision --> gw_vision{"fits vision?"}:::gw
  gw_vision -->|off-vision| e_rejected(["Rejected"]):::event
  gw_vision -->|fits| spec

  spec["Spec-author: draft/update C/F/S + tests"]:::agent --> prio["Prioritize (backlog-PM)"]:::agent
  prio --> gw_prio{"surface or park?"}:::gw
  gw_prio -->|"park (low-pri)"| e_parked(["Parked / declined"]):::event
  gw_prio -->|"top-N / critical"| gw_rev{{"review fan-out"}}:::gw

  gw_rev --> sec["Security review"]:::agent
  gw_rev --> arch["Architecture review"]:::agent
  gw_rev --> interop["Interop / conflict check"]:::agent
  gw_rev --> ux["UX/UI review"]:::agent
  sec --> gw_revj{{"join"}}:::gw
  arch --> gw_revj
  interop --> gw_revj
  ux --> gw_revj
  gw_revj --> gw_conf{"conflict?"}:::gw
  gw_conf -->|"conflict, rework"| spec
  gw_conf -->|clear| gate1

  gate1[/"GATE 1 — approve intent"/]:::gate
  gate1 -->|"change this"| spec
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
  gate2 -->|approve| merge[["Auto-merge to main"]]:::sys
  merge --> resync[["Re-sync files to DB"]]:::sys
  resync --> e_done(["Merged"]):::event

  classDef event fill:#e8eef7,stroke:#5b7aa7,color:#1b2b44;
  classDef agent fill:#eaf6ec,stroke:#4c9a5a,color:#16331e;
  classDef sys fill:#f3eefc,stroke:#8a6bbf,color:#2c1f44;
  classDef gate fill:#fdf1d6,stroke:#caa23a,color:#4a3a0e;
  classDef gw fill:#fdeaea,stroke:#cc6666,color:#4a1616;
  classDef box2 fill:#e6f7f8,stroke:#3fa6ad,color:#0e3b3e;
```

### Reading it

- **Three intake sources** (top) converge at **Spec-author** — issues/PRs go
  through Triage first (and features through Vision-fit); proactive Design
  proposals are already vision-aligned, so they enter at Spec-author.
- **Prioritize** is the attention valve: the long tail is *parked/declined*
  (recorded, never lost); only the **top-N or safety-critical** continue.
- **Review fan-out** runs Security / Architecture / Interop / UX in parallel, then
  joins; an **interop conflict** routes back to Spec-author for rework.
- **Gate 1** (approve intent) → autonomous **implement + author tests** on the
  box-1 workspace branch → **box 2** pulls + validates with Playwright.
- The tests gateway loops **failing → retry** (within budget) or **stuck →
  escalate**; **green** builds the review packet.
- **Gate 2** (approve the packet) → **auto-merge** spec+code+tests → **re-sync**.
- Both gates can **bounce back** ("change this") instead of approve/reject.
