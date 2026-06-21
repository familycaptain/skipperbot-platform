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

**Your TEST is yours to author; PRODUCT code is hands-off.** You MAY make the test robust — e.g. log
in **programmatically** (API auth + inject the token) when the login UI is racy under load and isn't
what's under test; that's fixing the TEST. You may NOT change application/product code or **redesign a
product subsystem** to pass — don't rewrite the product login because the theme test couldn't get past
it. A blocker that might be a **real product bug** → file a GitHub issue even if you work around it in
the test (never dismiss it as "just a test artifact"); a product that genuinely doesn't work → `passed:
false` (blocked): file + name + push back. Product fixes/redesigns are separate items needing the
operator's **Gate-1**. "Validate a toggle" must never become "rebuild login."

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
**Reusable scaffolding goes IN the harness, not a one-off.** If you build something future validations
will also need (a robust login, a wait/utility helper), add it to `ui_harness.py` (the `UI` class) so it
compounds — don't bury it in this item's acceptance script to be re-derived next time. E.g. robust auth
is already `ui_harness.login()` (programmatic); `login_via_form()` drives the real form only when login
itself is under test.

**Behaviour is PROBABILISTIC — verify like it.** Re-run any scenario whose outcome can vary **N×
(≥3)**; a single green run is not proof (a real duplicate-write bug surfaced ~1 in 3). If a fix only
holds 2/3, it's **not** green — escalate. **Bug-scout:** if you trip over a bug **unrelated** to this
change (the change under test still works; this bug is independent), do NOT fix it and do NOT fail this
gate for it — **file it as its own GitHub issue** and keep going:
`python3 -c "import apps.evolve.github_connector as g; print(g.create_issue('<short title>', '<1-3 line desc + found while validating ev-<n>>', labels=['evolve-incidental']))"` — note the # in your output.
(If instead the bug means the change UNDER TEST doesn't work → that's `passed:false`, not an incidental.)

**If it CAN be checked in the real UI, you MUST check it in the real UI — a bound/unit test never
substitutes.** Decide per change: does it alter anything a person sees or clicks (a `web/` or
`apps/*/ui/` file, a new control, a visible state/behaviour)? If yes, the live acceptance MUST
exercise that exact thing in the running UI — click the real control, drive the real flow, and assert
the rendered result the user would see (not just that a function returns the right value). A green
unit/bound test for UI behaviour is necessary but **NOT sufficient**: a change that touches the UI and
was validated only by unit tests is **NOT green**. For visual/appearance changes (themes, layout,
states), additionally **capture screenshots of the before/after states** (e.g. via `ui.shot(...)`) —
always, not only on failure — and surface them as artifacts so the operator can eyeball the actual
look at verify. Don't shrink scope to what's easy to assert headlessly; if the user can see it, prove
it in the UI.

**Fail closed (either layer):**
- A change with **no bound test** → NOT green.
- **Validation that couldn't RUN is a FAIL, not a skip.** If the tests/acceptance can't execute —
  missing build/test tooling (e.g. no node to build the web bundle, no Playwright), or the box-2
  target unavailable/occupied (e.g. uncommitted work you must not destroy) — emit `passed: false`
  with the blocker as the reason. Never proceed as if validated, never let a clean lint/dep-check/
  isolation result substitute, never hand it forward with a soft "verify later." Get the tool/target
  and re-run; flag the missing capability loudly.
- A **UI-affecting** change with no live-UI acceptance step that drives the real control → NOT green
  (unit tests alone don't count for UI behaviour).
- Any **red** bound test, OR any **failed acceptance scenario** (wrong tool fired / answer or UI
  doesn't reflect the change) → NOT green; report it as the variance signal → back to implement.
- Only all-green (bound tests + acceptance) is green → Gate 2.

> The baseline fixture is captured once (`box2_fixture.py snapshot`) and restored per run (step 2);
> the acceptance scenarios are the agent's to author from the spec.

Emit `VALIDATE_OUT` (`apps/evolve/agents/registry.py`) — `passed` + `failures` (include the failing
scenario's captured evidence). Save to `~/.evolve-poc/<id>/validate.json`.
