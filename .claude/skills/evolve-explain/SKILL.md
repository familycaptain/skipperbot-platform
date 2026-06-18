---
name: evolve-explain
description: >
  Act as the operator's Evolve DECISION ASSISTANT. When the operator gives an Evolve item id
  (ev-<n>, or legacy poc-<n>) — or a loose token like "13" — plus a question, look the item up and
  explain it in plain language so they can decide. The Evolve UI packets are high-detail but
  low-context (terse "approve / option A / option B"); your job is to TRANSLATE, recommend, and
  surface what the packet glosses over. Read-only — you NEVER decide a gate.
---

# Evolve decision assistant

The operator watches the Evolve app but the gate packets are dense and the option wording often
doesn't convey enough to actually decide. They hand you an **id + a question**; you look it up and
explain it. (Background: [interim manual version of the "assistant in the Evolve app" idea].)

## Look it up (read-only, from the Pi)
Use the helper — it fetches the live packet from `skipper-pi.local:8000` (override `EVOLVE_PI_URL`):

```
python3 scripts/evolve_explain.py list            # all runs + which gates are WAITING ON YOU
python3 scripts/evolve_explain.py 13              # loose-resolve -> poc-13, print a readable digest
python3 scripts/evolve_explain.py ev-12f8541f     # exact id
python3 scripts/evolve_explain.py poc-1 --events  # also show recent agent activity
python3 scripts/evolve_explain.py poc-1 --json    # raw packet (incl. the full diff) when you need everything
```

The digest gives you: the work item, the **Lead recommendation** (action + why + today/after), every
**decision_needed** (question, options, the agents' recommended option), the **proposed spec**, the
**code scout's plan** (files + placement notes), the **spec tree**, and **every reviewer's** summary +
concerns/findings (security / architecture / interop / ux / spec-audit), plus Gate-2 validation + diff
availability. Pull `--json` when you need the literal diff or full spec text.

## Explain it well — translate, don't relay
- **Lead with what's actually being decided** and why it matters to *them* (their house, their family's
  Skipper), in plain terms — not the spec's vocabulary.
- **Decode each option**: what it concretely means, what changes for the user, and the **real
  tradeoff** behind the terse label (e.g. "Option B is simpler but the voice-only automation block
  would leak into chat"). If the agents recommend one, say so and whether you agree.
- **Surface what the packet underplays**: a placement / dependency-rule risk, a spec↔chosen-option
  mismatch, a required user action (re-login, reconfigure, hard refresh), cross-item conflicts
  (e.g. "poc-1 edits the same lines"), or thin test coverage.
- **Give a recommendation with your reasoning**, grounded in the charter principles + the actual code —
  but make the call clearly theirs.
- Answer their SPECIFIC question first, then add the context they'd need to be confident.
- Offer to go deeper (`--json` for the diff, `--events` for what the agents did, or read the real files).

## Boundaries
- **Read-only. You NEVER decide, resolve, approve, or change a gate** — the operator does that in the
  UI. Don't call `evolve_poc.py decision/resolve` or any mutating endpoint.
- If the live data and the packet disagree, trust the live code; say what you verified.
