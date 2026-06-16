---
name: evolve-validate
description: >
  Evolve build — deploy the feature branch to box 2 and run the change's BOUND tests there
  (Playwright + unit), then judge green/red. Honest by construction: a change with no runnable bound
  test is NOT green. Done by the orchestrator after implement.
---

# Validate (on box 2)

Play the **Validate** agent. Canonical instructions: read `apps/evolve/agents/prompts/validate.md`.

Box 1 never validates itself. Use the existing mechanics — `apps.evolve.build_loop.remote_validate`
with `RemoteBox2` — which: deploys the feature branch to **box 2** (`evolve-test.local`), runs the
change's **bound tests** there (the test files the feature actually added/edited — unit via
`unittest`, browser via **Playwright/Chromium**, now installed on box 2), then resets box 2 to a
clean `release` baseline.

**Fail closed:**
- A change with **no bound test** → NOT green (you can't validate what you didn't test).
- Any **red** bound test → NOT green; report the failures as the variance signal.
- Only an explicit all-green pass is green → Gate 2.

Emit `VALIDATE_OUT` (`apps/evolve/agents/registry.py`) — `passed` + `failures`. Save to
`~/.evolve-poc/<id>/validate.json`.
