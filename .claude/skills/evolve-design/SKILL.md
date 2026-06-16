---
name: evolve-design
description: >
  Evolve spec phase — set the system-level approach (HOW it should work) for an accepted item
  before the spec is written; decide key technical choices; size one-spec vs needs-tree. Done by
  the orchestrator itself (shared conversation), building on grounding.
---

# Design

Play the **Design** agent. Canonical instructions: read `apps/evolve/agents/prompts/design.md`.

Building on your **grounding**, reframe what's actually needed (not just the literal ask), set the
**approach**, and MAKE the key technical decisions (grounded in the real code) — honor Skipper's
engineering principles (preconfigure once, minimize external calls, config in Settings, build for
the self-hoster, degrade gracefully). Surface genuine forks for the operator as `decisions_needed`
(each with a recommendation). Set `sizing`: `one-spec` or `needs-tree` (+ the `spec_tree` leaves).

You do this yourself (keep it in the conversation). Save to `~/.evolve-poc/<id>/design.json`
(shape: `DESIGN_OUT` in `apps/evolve/agents/registry.py`).
