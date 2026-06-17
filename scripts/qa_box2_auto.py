#!/usr/bin/env python3
"""POC acceptance spike (Phase 0) — scenario: open the Auto app, explore its UI so we can set up
a maintenance schedule. Logs in, clicks Auto, screenshots, and dumps the app's interactive
elements (buttons / inputs / tabs). Runs on box 2 against the live dockerized Skipper.
"""
import os, re
BASE = os.environ.get("QA_BASE", "http://localhost:8000")
USER = os.environ.get("QA_USER", "evolve_qa")
PW = open(os.path.expanduser("~/.evolve_qa_pw")).read().strip()
SHOTS = os.path.expanduser("~/evolve-qa-shots"); os.makedirs(SHOTS, exist_ok=True)
from playwright.sync_api import sync_playwright


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name)); print(f"  shot: {name}")


def login(page):
    page.goto(BASE, wait_until="networkidle")
    page.get_by_role("textbox").first.fill(USER)
    page.keyboard.press("Enter")
    page.wait_for_selector("input[type=password]", timeout=15000)   # wait for step 2
    page.locator("input[type=password]").first.fill(PW)
    page.keyboard.press("Enter")
    for _ in range(50):
        if page.evaluate("() => localStorage.getItem('skipperbot_token')"):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(2000)
    print("logged in")


def dump_interactive(page, label):
    print(f"\n=== interactive [{label}] ===")
    js = """() => {
      const out = [];
      for (const el of document.querySelectorAll('button,a,[role=button],input,select,textarea,[role=tab]')) {
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        const t = (el.innerText || el.getAttribute('aria-label') || el.placeholder || el.title || el.name || '').trim().slice(0,45);
        out.push({tag: el.tagName.toLowerCase(), type: el.type||'', t});
      }
      return out.slice(0,90);
    }"""
    for e in page.evaluate(js):
        tag = e['tag'] + (f"[{e['type']}]" if e['type'] else "")
        if e['t']:
            print(f"   <{tag}> {e['t']!r}")


def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(page)
        # open Auto from the launcher
        page.get_by_role("button", name="Auto", exact=True).first.click()
        page.wait_for_timeout(2500)
        shot(page, "03-auto-open.png")
        dump_interactive(page, "Auto app")
        # click into a vehicle to find the maintenance-schedule UI
        page.get_by_role("button", name=re.compile("Tesla Model 3", re.I)).first.click()
        # wait for the detail to finish loading (poll until "Loading vehicle" is gone)
        for _ in range(20):
            page.wait_for_timeout(500)
            if "loading vehicle" not in page.evaluate("() => document.body.innerText").lower():
                break
        page.wait_for_timeout(1000)
        shot(page, "04-vehicle-detail.png")
        dump_interactive(page, "vehicle detail")
        # open the Add Schedule form
        page.get_by_role("button", name=re.compile("Add Schedule", re.I)).first.click()
        page.wait_for_timeout(1500)
        shot(page, "05-add-schedule-form.png")
        dump_interactive(page, "Add Schedule form")
        b.close()


if __name__ == "__main__":
    main()
