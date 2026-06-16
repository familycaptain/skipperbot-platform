---
name: evolve-implement
description: >
  Evolve build — write the code that converges the codebase to an APPROVED spec, INSIDE the feature
  worktree only, with its bound test. Fail closed (no code / no test / escaped workspace = not done).
  Done by the orchestrator after Gate-1 approval.
---

# Implement

Play the **Implement** agent. Canonical instructions: read `apps/evolve/agents/prompts/implement.md`.

Write the code that satisfies the approved spec — no more (scope is the spec), no less (satisfy it
fully) — **AND** its bound test. Honor the engineering principles (preconfigure once, config in
Settings, the five surfaces, degrade gracefully, **guard the context window**: wire any new
tools/guidance/memory to load just-in-time and scoped — tool-router category + `guide.md` with the
tool, relevant memories only — never appended to the always-on system prompt). Cross-surface parity
matters: if behavior lives in
both `tools.py` (chat/voice/Discord) and a `*.jsx` UI (web/mobile), fix BOTH with identical messages.

## Workspace isolation — NON-NEGOTIABLE (this bit us before)
- **Edit ONLY files inside the feature worktree** (your cwd, e.g. `~/evolve-wt/poc-<n>/`). Use
  repo-relative paths. NEVER an absolute path into the main `~/repos/skipperbot-platform` checkout,
  never `cd` out to edit. That's the live code.
- After you finish, the orchestrator runs the **isolation check**: if the main checkout is dirty →
  it discards that and FAILS the build. So keep everything in the worktree or it won't merge.

## Fail closed
Real success = you changed code AND left a runnable **bound test** in the worktree. No change, or a
change with no test → report `ok:false` and say why. Emit `IMPLEMENT_OUT`
(`apps/evolve/agents/registry.py`) — `files_changed` + `ok`.
