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


def _goto_create_user(page):
    """Navigate the onboarding wizard welcome -> openai -> user (create-account form).
    Returns True if the create-account form is reached."""
    page.goto(BASE, wait_until="domcontentloaded")
    # Welcome step
    try:
        page.wait_for_selector('button:has-text("Get started")', timeout=15000)
    except Exception:
        return False
    page.click('button:has-text("Get started")')
    # OpenAI step auto-checks on mount; Next enables once state==ok (key present on box 2).
    try:
        page.wait_for_selector('button:has-text("Next"):not([disabled])', timeout=20000)
    except Exception:
        return False
    page.click('button:has-text("Next")')
    # Create-account form
    try:
        page.wait_for_selector('input[name="username"]', timeout=15000)
    except Exception:
        return False
    return True


def test_onboarding(browser):
    """Real Onboarding account-creation form on a FRESH (pre-onboarding) box 2 — the
    form with the most behavioral change (it needed a NEW explicit Enter onKeyDown
    handler once the submit button became type=button). Asserts: (a) clicking Create
    performs the SPA action with NO reload (>=REPEAT x), (b) Enter in EACH multi-input
    field submits via the onKeyDown (a create-user request fires) with no reload, and
    (c) no duplicate submit (a delayed in-flight window admits at most one request).
    The property tests stub create-user to {ok:false} so the form stays put; a final
    REAL create (as USER/PW so the chat test can then log in) proves end-to-end."""
    ctx = fresh_context(browser); page = ctx.new_page()
    # Count create-user requests for the Enter / duplicate-submit assertions.
    req = {"n": 0}
    page.on("request", lambda r: req.__setitem__("n", req["n"] + 1)
            if "onboarding/create-user" in r.url else None)

    VALIDU, VALIDP = USER, (PW or "evtestpw123")

    # --- (a) click no-reload, REPEAT x: stub create-user to ok:false so form stays ---
    page.route("**/api/onboarding/create-user", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": False, "error": "(stub: no-reload probe)"})))
    click_runs = []
    for i in range(REPEAT):
        if not _goto_create_user(page):
            click_runs.append({"run": i + 1, "detail": "could not reach create-account form",
                               "click_no_reload": False}); break
        page.fill('input[name="username"]', VALIDU)
        page.fill('input[name="password"]', VALIDP)
        set_sentinel(page)
        page.click('button:has-text("Create account")')
        page.wait_for_timeout(700)
        click_runs.append({"run": i + 1, "click_no_reload": survived(page)})

    # --- (b) Enter in EACH multi-input field submits via onKeyDown, no reload ---
    enter_fields = {}
    for field in ["username", "display_name", "password"]:
        if not _goto_create_user(page):
            enter_fields[field] = {"enter_submitted": False, "no_reload": False,
                                   "detail": "form not reached"}; continue
        page.fill('input[name="username"]', VALIDU)
        page.fill('input[name="password"]', VALIDP)
        before = req["n"]
        set_sentinel(page)
        page.press(f'input[name="{field}"]', "Enter")
        page.wait_for_timeout(700)
        enter_fields[field] = {"enter_submitted": req["n"] > before, "no_reload": survived(page)}

    # --- (c) no duplicate submit. The in-flight guard is SYNCHRONOUS (inFlightRef set
    # before the await), so two clicks in the SAME JS tick deterministically exercise it:
    # the 1st sets the ref + calls fetch; the 2nd sees the ref set and returns. Exactly
    # one request, independent of stub latency. ---
    dup = {"detail": "form not reached", "single_request": False}
    if _goto_create_user(page):
        page.fill('input[name="username"]', VALIDU)
        page.fill('input[name="password"]', VALIDP)
        before = req["n"]
        page.evaluate("""() => {
          const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('Create account'));
          b.click(); b.click();   // same-tick double click
        }""")
        page.wait_for_timeout(900)
        dup = {"requests_fired": req["n"] - before, "single_request": (req["n"] - before) <= 1}

    # --- final REAL create (no stub) as USER/PW -> advances, no reload, box onboarded ---
    page.unroute("**/api/onboarding/create-user")
    real = {"created_no_reload": False, "advanced": False}
    if _goto_create_user(page):
        page.fill('input[name="username"]', VALIDU)
        page.fill('input[name="display_name"]', "Evolve QA")
        page.fill('input[name="password"]', VALIDP)
        set_sentinel(page)
        page.click('button:has-text("Create account")')
        try:
            page.wait_for_selector('button:has-text("Open the desktop"), button[title="Settings"]', timeout=20000)
            real["advanced"] = True
        except Exception:
            pass
        real["created_no_reload"] = survived(page)
    ctx.close()

    passed = (bool(click_runs) and all(r.get("click_no_reload") for r in click_runs)
              and all(v.get("enter_submitted") and v.get("no_reload") for v in enter_fields.values())
              and dup.get("single_request")
              and real["created_no_reload"] and real["advanced"])
    return {"scenario": "onboarding_no_reload", "passed": passed,
            "click_runs": click_runs, "enter_per_field": enter_fields,
            "no_duplicate_submit": dup, "real_create": real}


def is_fresh():
    """True if box 2 is pre-onboarding (the onboarding form will render)."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{BASE}/api/onboarding/status", timeout=4) as r:
            return bool(json.loads(r.read()).get("needs_onboarding"))
    except Exception:
        return False


def main():
    results = []
    fresh = is_fresh()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page0 = browser.new_page()
            nc = negative_control(page0); results.append(nc); page0.close()
            results.append(test_login(browser))
            if fresh:
                # Onboarding live (creates USER/PW), THEN chat (logs in as that user).
                results.append(test_onboarding(browser))
                results.append(test_chat(browser))
            else:
                results.append(test_chat(browser))
                results.append({"scenario": "onboarding_no_reload", "passed": False,
                                "detail": "CANNOT VALIDATE: box 2 is already onboarded so the "
                                "account-creation form does not render. Run "
                                "scripts/box2_fresh_install.sh feature/ev-36 first."})
        finally:
            browser.close()
    oracle_ok = next((r["passed"] for r in results if r["scenario"] == "negative_control"), False)
    positives = [r for r in results if r["scenario"] != "negative_control"]
    all_green = oracle_ok and all(r["passed"] for r in positives)
    out = {
        "item": "ev-36",
        "all_green": all_green,
        "oracle_proven": oracle_ok,
        "fresh_box": fresh,
        "note": ("All 3 forms live-exercised when run on a FRESH box 2 (run "
                 "box2_fresh_install.sh feature/ev-36 first): Login + Chat + Onboarding "
                 "(Onboarding incl. click-no-reload Nx, Enter-per-field via onKeyDown, and "
                 "no-duplicate-submit). On an already-onboarded box the onboarding form can't "
                 "render -> reported as CANNOT VALIDATE (not a silent static pass)."),
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
