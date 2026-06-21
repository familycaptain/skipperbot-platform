#!/usr/bin/env python3
"""Box-2 LIVE acceptance for issue #36 — no web SPA form can native-submit / reload.

Bound test for ev-36. Runs ON box 2 against the live dockerized Skipper
(localhost:8000). Proves, on the REAL forms (not a token-inject bypass), that
clicking a form's primary button never triggers a native HTML form submission /
full-page reload.

Oracle = a window-level sentinel: before the click we set `window.__noReload`; a
full navigation/reload wipes window globals, so after the click the sentinel is
gone IFF the page reloaded. To prove the oracle actually detects a reload we run a
NEGATIVE CONTROL first: inject a real <button type=submit> in a <form>, click it,
and assert the sentinel IS cleared. Only if the negative control fires do the
positive assertions mean anything.

  .venv/bin/python scripts/box2_no_reload_acceptance.py            # all scenarios
Exit 0 = all green; 1 = any red. Emits a JSON evidence block at the end.
"""
import os, json, traceback
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://localhost:8000")
USER = os.environ.get("QA_USER", "evolve_qa")
PWFILE = os.path.expanduser("~/.evolve_qa_pw")
PW = open(PWFILE).read().strip() if os.path.exists(PWFILE) else os.environ.get("QA_PW", "")
SHOTS = os.path.expanduser("~/evolve-qa-shots"); os.makedirs(SHOTS, exist_ok=True)
REPEAT = int(os.environ.get("NO_RELOAD_REPEAT", "3"))

SENTINEL = "EV36_NO_RELOAD"


def set_sentinel(page):
    page.evaluate(f"() => {{ window.__noReload = '{SENTINEL}'; }}")


def survived(page):
    """True if no reload happened (sentinel still present)."""
    return page.evaluate("() => window.__noReload") == SENTINEL


def fresh_context(browser):
    # No service worker: a controllerchange reload must never be mistaken for a
    # native submit. A fresh context starts with no SW; we also block SW scripts.
    ctx = browser.new_context(service_workers="block")
    return ctx


def negative_control(page):
    """Prove the oracle: a real native submit MUST clear the sentinel."""
    page.goto(BASE, wait_until="domcontentloaded")
    set_sentinel(page)
    # Inject a native form whose submit navigates (default GET to current URL).
    page.evaluate(
        """() => {
          const f = document.createElement('form');
          const b = document.createElement('button');
          b.type = 'submit'; b.id = '__nc_submit'; b.textContent = 'nc';
          f.appendChild(b); document.body.appendChild(f);
        }"""
    )
    try:
        with page.expect_navigation(timeout=5000):
            page.click("#__nc_submit")
    except Exception:
        pass
    cleared = not survived(page)
    return {"scenario": "negative_control", "passed": cleared,
            "detail": "native submit cleared sentinel (oracle works)" if cleared
            else "native submit did NOT clear sentinel — ORACLE BROKEN, positives are meaningless"}


def test_login(browser):
    """Real LoginScreen form: clicking Continue must not reload (>=REPEAT x).
    /auth/login is routed to a stub so repeats are cheap and dodge the rate
    limiter — the property under test is 'the button click does not natively
    submit', independent of the auth result."""
    runs = []
    for i in range(REPEAT):
        ctx = fresh_context(browser); page = ctx.new_page()
        # Stub the username-step call so we get a deterministic, rate-limit-free state.
        page.route("**/auth/login", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"error": "password_required", "name": USER, "display_name": USER})))
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector('input[placeholder="Username"]', timeout=15000)
        page.fill('input[placeholder="Username"]', USER)
        set_sentinel(page)
        page.click('button:has-text("Continue")')
        page.wait_for_timeout(800)
        ok_click = survived(page)
        # advanced to password step (SPA transition, no reload)
        advanced = page.locator('input[placeholder="Password"]').count() > 0
        # Enter-key path on the username step (fresh page, fresh sentinel)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector('input[placeholder="Username"]', timeout=15000)
        page.fill('input[placeholder="Username"]', USER)
        set_sentinel(page)
        page.press('input[placeholder="Username"]', "Enter")
        page.wait_for_timeout(800)
        ok_enter = survived(page)
        runs.append({"run": i + 1, "click_no_reload": ok_click, "spa_advanced": advanced,
                     "enter_no_reload": ok_enter})
        ctx.close()
    passed = all(r["click_no_reload"] and r["enter_no_reload"] and r["spa_advanced"] for r in runs)
    return {"scenario": "login_no_reload", "passed": passed, "runs": runs}


def test_chat(browser):
    """Real chat: clicking Send must not reload (>=REPEAT x). Requires a real
    login (done once via the real form, which also exercises the full login flow
    for real). Chat is not rate-limited like auth."""
    if not PW:
        return {"scenario": "chat_no_reload", "passed": False,
                "detail": f"no QA password ({PWFILE}); cannot log in to reach chat"}
    ctx = fresh_context(browser); page = ctx.new_page()
    # Real form login (no stub) — also proves the live login flow end to end once.
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector('input[placeholder="Username"]', timeout=15000)
    page.fill('input[placeholder="Username"]', USER)
    page.click('button:has-text("Continue")')
    page.wait_for_selector('input[placeholder="Password"]', timeout=15000)
    page.fill('input[placeholder="Password"]', PW)
    page.click('button:has-text("Sign In")')
    try:
        page.wait_for_selector('button[title="Settings"]', timeout=20000)
    except Exception:
        ctx.close()
        return {"scenario": "chat_no_reload", "passed": False,
                "detail": "could not reach the signed-in app to test chat"}
    page.wait_for_timeout(1500)
    runs = []
    for i in range(REPEAT):
        ta = page.locator("form textarea").first
        if ta.count() == 0:
            runs.append({"run": i + 1, "detail": "no chat textarea found", "click_no_reload": False})
            break
        ta.fill(f"ev36 no-reload probe {i + 1}")
        set_sentinel(page)
        page.locator('form button[type="button"]').last.click()
        page.wait_for_timeout(800)
        runs.append({"run": i + 1, "click_no_reload": survived(page)})
    passed = bool(runs) and all(r.get("click_no_reload") for r in runs)
    ctx.close()
    return {"scenario": "chat_no_reload", "passed": passed, "runs": runs}


def main():
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page0 = browser.new_page()
            nc = negative_control(page0); results.append(nc); page0.close()
            results.append(test_login(browser))
            results.append(test_chat(browser))
        finally:
            browser.close()
    oracle_ok = next((r["passed"] for r in results if r["scenario"] == "negative_control"), False)
    positives = [r for r in results if r["scenario"] != "negative_control"]
    all_green = oracle_ok and all(r["passed"] for r in positives)
    out = {
        "item": "ev-36",
        "all_green": all_green,
        "oracle_proven": oracle_ok,
        "note": ("Onboarding form is verified by the static guardrail + per-file static "
                 "assertion only: box 2 is already onboarded so /api/onboarding/create-user "
                 "is closed and the form does not render. Confirm Onboarding on a fresh "
                 "skipper-uat at verify."),
        "results": results,
    }
    print("EV36_RESULT " + json.dumps(out))
    raise SystemExit(0 if all_green else 1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("EV36_RESULT " + json.dumps({"item": "ev-36", "all_green": False,
              "error": traceback.format_exc()[-1500:]}))
        raise SystemExit(1)
