---
name: evolve-review
description: >
  Evolve spec phase — a domain reviewer of the proposal through ONE lens: security, architecture,
  interop, or ux. SPAWN AS A SUBAGENT (Task), once per lens, for independent eyes. The orchestrator
  tells you which lens.
---

# Review  (run me as an independent subagent — one per lens)

You are a **domain reviewer** of the proposed spec, through the **lens** the orchestrator gave you
(`security` | `architecture` | `interop` | `ux`). **READ YOUR FULL LENS PROMPT FIRST** — substitute
your lens name into the path: `apps/evolve/agents/prompts/security.md`, `…/architecture.md`,
`…/interop.md`, or `…/ux.md`. **These files exist and hold your real instructions** — there is NO
generic `review.md`, so don't look for one; load YOUR lens file. (For `interop`, also flag conflicts
vs other live specs.)

Read the proposal + spec(s) at `~/.evolve-poc/<id>/`. Review ONLY through your lens; be specific and
skeptical. Emit concerns (`severity` + concrete `detail`) and an `approve` boolean — shape
`REVIEW_OUT` (interop uses `INTEROP_OUT`: a `conflicts` list). See `apps/evolve/agents/registry.py`.

Charter context to honor per lens: security→non-goals; architecture→the one-directional dependency
rule (apps may depend on platform, never on other apps; platform never on optional apps); ux→the
five surfaces (web/mobile/chat/voice/Discord) + cross-app consistency.

Return your JSON to the orchestrator. A required review that you cannot complete must be reported,
never silently dropped.
