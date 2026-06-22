---
name: evolve-reproduce
description: >
  Evolve spec phase — empirical reproduction on box 2, run after the security screen clears and BEFORE
  grounding/design. Deploys current release to box 2, drives the real UI/flow to reproduce the REPORTED
  symptom, screenshots what the user sees, and posts it to the GitHub issue. Proves/disproves the issue
  is real and names the actual user-facing surface so grounding targets the right code. Done by the
  orchestrator (it drives box 2).
---

# Reproduce (gate-1 empirical reproduction)

Play the **reproduce** agent. Canonical instructions: `apps/evolve/agents/prompts/reproduce.md`.

You run **after** `evolve-security-screen` returns `clear` and **before** `evolve-grounding`. You see
what the USER sees first — then grounding goes and finds the code that produces *that*. This kills the
"read code → misattribute the UI symptom → check the wrong code → wrongly conclude no-issue" failure.

## Run it (orchestrator, shared conversation — it drives box 2, like validate)
1. `python3 scripts/box2_live.py deploy release` — the current pre-fix state (mock data). No fix applied.
2. Reproduce the reported symptom on the **exact surface** the issue names (notification, button, app
   screen, refresh) via `scripts/ui_harness.py` + Playwright or the real endpoint — follow the issue's
   steps literally; honor any `repro_constraints` from the security screen.
3. `page.screenshot(path=...)` the actual symptom; **look at it**; then
   `python3 -c "import apps.evolve.github_connector as g; g.attach_image_to_issue(<issue#>, '<path>', 'gate-1 repro: …')"`.

Produce `REPRODUCE_OUT` (`apps/evolve/agents/registry.py`): `reproduced` (`yes`/`no`/`inconclusive`),
`evidence` (catbox URLs), `observed`, `surface` (the precise real surface, for grounding), `notes`.
Save as `reproduce.json`.

- `reproduced=yes` → continue: `evolve-grounding` grounds in the code behind `surface`, then the rest
  of the spec phase.
- `reproduced=no`/`inconclusive` → **first-class outcome, do NOT invent a fix.** Orchestrator pushes a
  Gate-1 packet ("could not reproduce" + evidence) for the operator; `phase=gate1`, END.

NEVER conclude "already works" from reading code — only the screenshot decides.
