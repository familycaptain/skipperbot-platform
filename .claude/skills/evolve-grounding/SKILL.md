---
name: evolve-grounding
description: >
  Evolve spec phase — scan the relevant code ONCE for a work item and produce a reusable map
  (files, key symbols, excerpts, conventions). The single cold scan; the rest of the spec phase
  builds on it. Done by the orchestrator itself (it's the shared conversation), not a subagent.
---

# Grounding

Play the **Grounding** agent. Canonical instructions: read `apps/evolve/agents/prompts/grounding.md`.

This is the **one cold scan per item** — explore the code that matters for this work item with
Read/Grep/Glob: the relevant files + their role, the key functions/classes/routes the change will
touch, crucial excerpts, the conventions to follow, and where behavior is wired (routes/tools/UI).

**Also read the existing specs, not just the code.** Identify the target `capability` (the app
under `apps/<cap>/`; `platform` for the core) and run `python3 -m apps.evolve.spec_index <cap>` —
a bounded, one-line-per-record view of that capability's existing C/F/S tree. Emit it as
`existing_specs` so design/spec-author EXTEND and place within the tree instead of duplicating. (It
stays small — one app's tree — so it scales no matter how big the whole corpus gets.)

**You (the orchestrator) do this yourself and KEEP it in your conversation** — design, spec-author,
and the Lead all build on this without re-scanning (1 issue = 1 conversation). Save a copy to
`~/.evolve-poc/<id>/grounding.json` (shape: `GROUNDING_OUT` in `apps/evolve/agents/registry.py`) so
subagents you spawn can read it without re-exploring.
