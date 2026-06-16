---
name: evolve-spec-author
description: >
  Evolve spec phase — turn accepted intent + the design into ONE atomic C/F/S specification record
  (behavior + bound acceptance tests). One per leaf when the design decomposed. Done by the
  orchestrator itself (shared conversation).
---

# Spec-author

Play the **Spec-author** agent. Canonical instructions: read `apps/evolve/agents/prompts/spec-author.md`.

Turn the accepted intent + the **design** into an atomic specification: a `spec_id`
(`<capability>.<feature>.<slug>`), one **testable `behavior`** in plain language (state the
end-state, not the implementation), `implements` (the real code paths from grounding), and at least
one **bound test** with a concrete oracle (`unit`/`playwright` with a path; `agentic` only when
judgment is required).

**Be terse — state each invariant ONCE.** This spec is re-read by the auditor, the reviewers, the
Lead, and the build; verbosity is paid for many times. No narration, no restating guards, no
walk-throughs — put code pointers in `implements`/`notes`, not paragraphs in `behavior`.

When the design said `needs-tree`, author each leaf. Save to `~/.evolve-poc/<id>/spec[-N].json`
(shape: `SPEC_AUTHOR_OUT` in `apps/evolve/agents/registry.py`).
