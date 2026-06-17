#!/usr/bin/env python3
"""POC acceptance-validation spike (Phase 0): drive the LIVE box-2 Skipper UI with Playwright.

Stage 1 — log in (2-step form) and explore the desktop: screenshot + dump the clickable
elements so we can see how to open the Auto app and drive a real scenario. Read-only on the UI
except logging in. Runs on box 2 (host .venv has playwright + chromium); targets the dockerized
Skipper on http://localhost:8000.
"""
import os
import re
import sys
import json

BASE = os.environ.get("QA_BASE", "http://localhost:8000")
USER = os.environ.get("QA_USER", "evolve_qa")
PW = open(os.path.expanduser("~/.evolve_qa_pw")).read().strip()
SHOTS = os.path.expanduser("~/evolve-qa-shots")
os.makedirs(SHOTS, exist_ok=True)

from playwright.sync_api import sync_playwright


def shot(page, name):
    p = os.path.join(SHOTS, name)
    page.screenshot(path=p, full_page=False)
    print(f"  shot: {p}")


def dump_clickables(page, label):
    """Print visible buttons / links / role=button with their text — to learn the UI."""
    print(f"\n=== clickable elements [{label}] ===")
    js = """() => {
      const out = [];
      const sel = 'button, a, [role=button], [data-appid], [data-app], li, [class*=app]';
      for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        const t = (el.innerText || el.getAttribute('aria-label') || el.title || '').trim().slice(0,40);
        if (!t) continue;
        out.push({tag: el.tagName.toLowerCase(), t,
                  app: el.getAttribute('data-appid') || el.getAttribute('data-app') || ''});
      }
      return out.slice(0, 80);
    }"""
    for e in page.evaluate(js):
        print(f"   <{e['tag']}> {e['t']!r}" + (f"  app={e['app']}" if e['app'] else ""))


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        print(f"goto {BASE}")
        page.goto(BASE, wait_until="networkidle")
        shot(page, "01-landing.png")

        # --- 2-step login: username -> Continue -> password -> Sign In ---
        authed = False
        try:
            page.get_by_role("textbox").first.fill(USER)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            pwfield = page.locator("input[type=password]")
            if pwfield.count():
                pwfield.first.fill(PW)
                page.keyboard.press("Enter")           # submit via Enter (button is an icon)
            print("login submitted; polling for token…")
            # poll up to 25s for the auth token to appear
            for _ in range(50):
                tok = page.evaluate("() => localStorage.getItem('skipperbot_token')")
                if tok:
                    authed = True
                    break
                page.wait_for_timeout(500)
        except Exception as e:
            print(f"LOGIN step error: {type(e).__name__}: {e}")
        page.wait_for_timeout(2000)
        shot(page, "02-after-login.png")
        print("authenticated:", authed)
        if not authed:
            try:
                print("page text:", page.evaluate("() => document.body.innerText")[:400])
            except Exception:
                pass

        print("\nTITLE:", page.title())
        print("URL:", page.url)
        dump_clickables(page, "desktop")
        # also dump the first chunk of visible page text
        try:
            txt = page.evaluate("() => document.body.innerText").strip()
            print("\n=== page text (first 1500 chars) ===\n" + txt[:1500])
        except Exception:
            pass

        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
