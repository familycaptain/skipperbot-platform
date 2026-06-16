# Evolve on a subscription: `/loop` + skills instead of the SDK swarm

**Status:** proposal for discussion (drafted end of the big build session). Cost win ≈ **20×**.

## The idea (in one line)
The hard work is finished — the SDLC **graph + funnel** (branching/order), the **agent prompts**,
the **Evolve UI**, and a proven **end-to-end** run. Only the *execution substrate* changes: move the
agent swarm off the `claude-agent-sdk` (which legally **must** use `ANTHROPIC_API_KEY` → metered API
credits) and into an **interactive Claude Code session**, where `/loop` orchestrates an array of
**Claude Skills** (one per agent role) + **Claude Code subagents** (the Task tool, for independent /
forked reviewers). The operator runs it **on-demand** — on when working, off when done. Interactive,
human-initiated, supervised → within ToS → **flat-rate Max subscription**, ~20× cheaper than
pay-as-you-go (research confirmed a subscription cannot drive the SDK/headless, but interactive
Claude Code use is fine).

## The mapping — reuse, don't rebuild
| Today (SDK swarm, API credits) | Subscription model (interactive `/loop`) |
|---|---|
| Each agent = a `ClaudeSDKBackend` call | Each agent = a **Skill** (its prompt + output contract), run as a **subagent** (Task tool) |
| Forked adversarial critics | **Independent subagents** — fresh context, true independence, subscription-billed |
| Graph/funnel walk (`sdlc.yaml`) | A `/loop` **orchestration skill** walks the same order (triage→vision→prioritize→spec→gates) |
| Human gates (pipeline + Pi UI) | `/loop` pauses at a gate; operator reviews in the **same Evolve UI**; resumes on the decision |
| Deterministic mechanics (serialize / merge / validate-on-box2) | **KEEP** as box-1 scripts the session calls (git + tests don't need an LLM) |
| Observability / cost reported to the Pi | The session reports to the **same bridge** → the Evolve app keeps working unchanged |
| Workspace isolation (worktree, fail-closed) | **RE-ENFORCE** in the build skill — the session has full repo write access (the guardrail we just fought for) |

## Architecture options
- **A — Fully in-session:** `/loop` runs the whole pipeline; subagents do the agent steps; state lives
  in the instance store; reports to the Pi. Cleanest, no API process, but the orchestration logic
  moves into the loop/skills.
- **B — Hybrid:** box-1 keeps the graph/queue/gates/UI; the session is the **worker pool** — box-1
  enqueues "run design on item X", the `/loop` picks it up, runs it (subagent + skill), posts the
  result, box-1 advances. Reuses the proven pipeline exactly; adds a small task-queue bridge.
- **Recommended blend:** the **session** drives the *reasoning* agents (subscription); **box-1 scripts**
  do the *deterministic* git/test mechanics (serialize, cut worktree, merge, run box-2 validate). Best
  of both — keeps everything deterministic that should be, spends subscription quota only on thinking.

## On-demand operation
Operator opens a Claude Code session → `/loop evolve` pulls the work queue → processes within the
subscription → pauses at gates → operator reviews → turns it off when done. Matches both the
subscription's interactive model and the operator's actual work rhythm.

## Pros
1. **~20× cost** — flat Max vs metered API (this one dev day burned ~$160; at issue scale the API is
   thousands/month). The headline.
2. **Reuses ~80% of what's built** — graph, funnel, prompts, UI, gates, the E2E flow.
3. **Within ToS** — interactive, operator-initiated, supervised, on-demand (not headless/automated).
4. **The session Claude is *more* capable** than the constrained SDK agents — full tools, whole-repo
   context, can run tests / browse / reason across the codebase.
5. **Subagents preserve the swarm** — independent reviewers + forked critics still exist (Task tool),
   on the subscription. We don't lose the multi-agent structure.
6. **Simpler infra** — no SDK process, no API key, no per-agent process spawning.
7. **Tighter operator loop** — you're *in* the session; intervene, redirect, and watch live.

## Cons / risks
1. **Serial + capped to work-hours** — one session = one Claude; no unattended overnight backlog
   churn. (By design — it's on-demand — but it caps throughput to "while I'm working.")
2. **Subscription rate limits** — 5-hour windows + weekly caps; a heavy loop can throttle mid-work.
   Must pace agent-steps within the plan's limits.
3. **ToS gray area** — keep it genuinely interactive/supervised/on-demand, **not** a 24/7 daemon, to
   stay clearly inside "interactive use."
4. **Isolation regression risk** — the session has full write access, so the worktree + fail-closed
   guardrails **must** be re-enforced in the build skill (we just spent real effort on this).
5. **Structured-output discipline** — the SDK *forced* JSON via schema; skills enforce the output
   contract by instruction only, so they must be written tightly (and verified).
6. **Independent critique** — self-review by the same session is weaker; use **subagents** to keep
   reviewers genuinely independent.
7. **Migration effort** — port ~15 prompts → skills + a `/loop` orchestrator + re-wire observability
   and gates. Real, but mostly mechanical (the thinking is done).

## To decide tomorrow
- **A vs B vs the blend** (recommend the blend).
- **How much of box-1 to keep** — recommend: the deterministic scripts + the UI/state + the Pi; drop
  only the SDK agent backend.
- **Isolation in-session** — how the build skill enforces "work in the worktree, fail closed."
- **"Cost" UI when it's subscription usage, not $** — maybe show agent-step counts / rate-limit
  headroom instead of dollars.
- **Pacing** within rate limits (how many issues/agent-steps per session).

## Proof it's feasible
This very session — a Claude Code session on the subscription — already drove the entire Evolve build
end-to-end (multi-step, tools, tests, git, the whole pipeline). The agents are just *roles*; a session
can play them via skills + subagents. The capability is demonstrated; the work is the port.
