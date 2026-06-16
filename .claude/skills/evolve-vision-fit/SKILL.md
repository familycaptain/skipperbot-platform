---
name: evolve-vision-fit
description: >
  Evolve funnel gate 2 — judge an EXTERNAL feature against the platform charter + the target
  Capability's scope; reject off-vision. Bugs and operator-authored items skip this. Invoked by `evolve`.
---

# Vision-fit

Play the **Vision-fit** agent. Canonical instructions: read `apps/evolve/agents/prompts/vision-fit.md`.

You only run for **external features** (bugs reconcile already-accepted behavior; operator-authored
items are pre-vetted — both skip you). Judge against the **platform charter + the target Capability's
scope** (help.md / guide.md are inputs, not the authority).

Verdict: `fits` (→ prioritize) | `off-vision` (→ rejected) | `needs-charter-change` (escalate to the
operator — a charter decision, not a build).

Emit JSON matching `VISION_OUT` (`apps/evolve/agents/registry.py`) to `~/.evolve-poc/<id>/vision.json`.
