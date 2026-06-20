---
name: evolve-validate
description: >
  Evolve build — validate a change on box 2 TWO ways: (A) run its bound tests, and (B) drive the
  LIVE Skipper as a real user (UI clicks + chat) and judge on captured evidence (the actual
  tool-calls + responses). Honest by construction: no bound test AND/OR a failed acceptance scenario
  is NOT green. Done by the orchestrator after implement.
---

# Validate (on box 2)

Play the **Validate** agent. Canonical instructions: read `apps/evolve/agents/prompts/validate.md`.
Box 1 never validates itself — everything here runs on **box 2** (the test host), which runs
the live dockerized Skipper.

## A) Bound tests (existing)
`apps.evolve.build_loop.remote_validate` + `RemoteBox2`: deploy the feature branch to box 2, run the
change's **bound tests** (unit via `unittest`, browser via Playwright), then reset to `release`.

## B) LIVE acceptance — drive it like a user (the real "does it actually work")
Bound tests are written by the *implement* agent and can be self-confirming. So ALSO exercise the
running app and judge on **hard evidence** — the actual tool-calls + responses, not vibes. Two
reusable harness scripts on box 2 do the heavy lifting (drive them over ssh from box 1):

1. **Deploy the change onto the live instance:** `python ~/box2_live.py deploy <feature-branch>` —
   `git checkout` + `skipper update` (non-interactive) + waits until it's actually serving. (Code
   reset after with `python ~/box2_live.py reset`.)
2. **Restore the data fixture (reproducible start):** `python ~/box2_fixture.py reset` — rolls box 2's
   DB back to a known baseline snapshot, so every run starts from an IDENTICAL state (the DB persists
   across deploys, so without this, data drifts run-to-run). Capture the baseline once with
   `box2_fixture.py snapshot`.
3. **Generate acceptance scenarios from the APPROVED spec/story** — a JSON list of scenarios, each a
   sequence of `steps`: UI actions (`open_app`, `click`, `fill`, `select`, `expect_ui`) and `chat`
   turns. **For chat, use VARIED phrasings** (how real users actually talk, not the literal wording)
   and assert the RIGHT outcome: `expect_tool` (which MCP tool must fire) + `expect_answer_contains`.
   This is what catches an intent path that string-matches instead of letting the LLM decide.
4. **Run it:** `python ~/box2_acceptance.py --scenario <file.json>` → returns a structured report
   with per-step pass/fail and the captured evidence (answer + `tool_calls` from `/api/chat/history`).
5. **Judge** the report. Cap scenarios (~5–10 chat turns — bounded; box 2's agent spends API credits).

**Driving the real UI — use the hardened harness, not naive Playwright.** For UI steps prefer
`scripts/ui_harness.py` (the `UI` class), which encodes the friction that makes naive automation
lie: React **controlled inputs** ignore `.fill()` → it sets the value via the native setter +
dispatches `input`/`change` so the form goes dirty and **Save un-disables**; **SPA nav is flaky** →
it clicks-and-waits-for-the-target with retries + overlay/Escape, not click+sleep; it finds a field
by the control after ANY element whose direct text matches the label; and it captures every console
error + **HTTP>=400** and screenshots failures to `/tmp/ui_*.png`. Host is `SKIPPER_UI_BASE` — point
it at **box 2** for both the Gate-2 (feature branch) and Gate-3 pre-verify (merged release) passes.
(skipper-uat is the *operator's* manual box, not part of this automated loop.)

**Behaviour is PROBABILISTIC — verify like it.** Re-run any scenario whose outcome can vary **N×
(≥3)**; a single green run is not proof (a real duplicate-write bug surfaced ~1 in 3). If a fix only
holds 2/3, it's **not** green — escalate. **Bug-scout:** if you trip over a bug unrelated to this
change, do NOT fix it — **file a GitHub issue** and keep going.

**Fail closed (either layer):**
- A change with **no bound test** → NOT green.
- Any **red** bound test, OR any **failed acceptance scenario** (wrong tool fired / answer or UI
  doesn't reflect the change) → NOT green; report it as the variance signal → back to implement.
- Only all-green (bound tests + acceptance) is green → Gate 2.

> The baseline fixture is captured once (`box2_fixture.py snapshot`) and restored per run (step 2);
> the acceptance scenarios are the agent's to author from the spec.

Emit `VALIDATE_OUT` (`apps/evolve/agents/registry.py`) — `passed` + `failures` (include the failing
scenario's captured evidence). Save to `~/.evolve-poc/<id>/validate.json`.
