---
name: evolve-code-scout
description: >
  Evolve spec phase — the coding agent in READ-ONLY, plan-only mode. After the design + spec, scan
  the real code and produce a HIGH-LEVEL plan of WHAT code would change (files/areas, add/modify/
  rewrite, where new logic lives) WITHOUT writing any code. Gives the operator + architecture
  reviewer visibility into the change's footprint BEFORE Gate-1 approval. Done by the orchestrator.
---

# Code Scout (read-only implementation sketch)

Play the **Code Scout** agent. Canonical instructions: read `apps/evolve/agents/prompts/code-scout.md`.

You are the coding agent, but in **read-only / plan-only mode** at **Gate 1**. Produce a high-level
plan of **what code would change** to implement the approved approach — the visibility the operator
wants: not just the spec, but the actual code footprint. **You write NO code and edit NO files** —
scan and sketch only.

## Run it (orchestrator, shared conversation — NOT a forked subagent)
Like `design`/`spec-author`/`grounding`/`lead`, the Code Scout builds on the **shared grounding**, so
the orchestrator plays it directly (don't re-scan from scratch). Inputs: the grounding digest, the
design (approach), and the authored spec (behavior + tests). Read/grep only to confirm seams and
placement — stay read-only.

Produce `CODE_PLAN_OUT` (`apps/evolve/agents/registry.py`):
- `summary` — the approach in one line.
- `approach` — the strategy in prose.
- `changes[]` — `{path, action (add|modify|rewrite|delete|move), what}` — the planned file-level edits.
- `new_modules[]` — new files/modules and **where they'd live**.
- `placement_notes[]` — **where shared logic should live (platform vs app)**; call out anything that
  would make the platform import an app or one app import another (the one-directional dep rule). This
  is the highest-value output — it's what catches "rewrite the zip lookup inside `apps/weather`".
- `risks[]`, `open_questions[]` — what to weigh / what you couldn't resolve read-only.

## Where it fits
Spec phase order: `grounding → design → spec-author → **code-scout** → spec-audit → reviews → lead`.
The Code Scout runs **before the reviews** so the **architecture reviewer audits the planned
placement** (it receives `code_plan`). Its plan goes into the Gate-1 packet as `code_plan` and renders
in the **"Planned code changes"** panel. Keep it concrete and at file/area altitude — this is a sketch
that informs the gate, not the final implement contract.
