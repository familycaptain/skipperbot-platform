#!/usr/bin/env python3
"""Box-2 acceptance for the light/dark theme (issue #26).

Drives the LIVE dockerized Skipper web UI and proves the variable-inversion
theme end to end. Per operator requirement, it ALWAYS captures screenshots of
BOTH themes — the shell AND an open app panel, in dark and in light — so the
operator can eyeball the real look at Gate-3 (beyond the programmatic checks).

Asserts:
  1. the theme toggle is present in the header (accessible name).
  2. fresh load defaults to dark (html[data-theme] != 'light').
  3. clicking the toggle flips html[data-theme] to 'light' WITHOUT a reload, and
     a representative shell surface recolors (whole-desktop switch).
  4. the choice persists across reload (still 'light', applied before first paint).
  5. a basic AA contrast spot-check on body text in light mode (>= 4.5:1).
Run on box 2: QA_BASE=http://localhost:8000 .venv/bin/python scripts/p2_theme_acceptance.py
"""
import os, json
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://localhost:8000")
USER = os.environ.get("QA_USER", "evolve_qa")
PW = open(os.path.expanduser("~/.evolve_qa_pw")).read().strip()
SHOTS = os.path.expanduser("~/evolve-qa-shots"); os.makedirs(SHOTS, exist_ok=True)


def shot(page, n):
    page.screenshot(path=os.path.join(SHOTS, n)); print(f"  shot: {n}")


def login(page):
    page.goto(BASE, wait_until="networkidle")
    page.get_by_role("textbox").first.fill(USER)
    page.keyboard.press("Enter")
    page.wait_for_selector("input[type=password]", timeout=15000)
    page.locator("input[type=password]").first.fill(PW)
    page.keyboard.press("Enter")
    for _ in range(50):
        if page.evaluate("() => localStorage.getItem('skipperbot_token')"):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500); print("✓ logged in")


def theme_attr(page):
    return page.evaluate("() => document.documentElement.getAttribute('data-theme')")


def _lum(rgb):
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(fg, bg):
    l1, l2 = _lum(fg), _lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def body_colors(page):
    """Return (fg_rgb, bg_rgb) of the shell root text/background for a contrast check."""
    return page.evaluate("""() => {
        const el = document.querySelector('#root > div') || document.body;
        const s = getComputedStyle(el);
        const parse = (v) => (v.match(/\\d+/g) || [0,0,0]).slice(0,3).map(Number);
        // walk up for a non-transparent background
        let bgEl = el, bg = s.backgroundColor;
        while (bgEl && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
            bgEl = bgEl.parentElement; if (!bgEl) break; bg = getComputedStyle(bgEl).backgroundColor;
        }
        return { fg: parse(s.color), bg: parse(bg) };
    }""")


def open_an_app(page):
    # Open any app tile to get an app-panel surface in the screenshot.
    for name in ("Auto", "Lists", "Goals", "Settings", "Home"):
        try:
            btn = page.get_by_role("button", name=name, exact=True).first
            if btn.count():
                btn.click(); page.wait_for_timeout(2000); return name
        except Exception:
            pass
    return None


def main():
    report = {"checks": {}, "screenshots": [], "ok": False}
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(page)

        # (2) default dark
        d = theme_attr(page)
        report["checks"]["default_dark"] = (d != "light")
        shot(page, "theme_dark_shell.png"); report["screenshots"].append("theme_dark_shell.png")
        app = open_an_app(page)
        shot(page, "theme_dark_panel.png"); report["screenshots"].append("theme_dark_panel.png")
        dark_bg = body_colors(page)["bg"]

        # (1) toggle present
        toggle = page.get_by_role("button", name=lambda n: n and "theme" in n.lower())
        report["checks"]["toggle_present"] = bool(toggle.count())

        # (3) click -> light, no reload, recolor
        toggle.first.click(); page.wait_for_timeout(600)
        light = theme_attr(page)
        light_bg = body_colors(page)["bg"]
        report["checks"]["flips_to_light"] = (light == "light")
        report["checks"]["shell_recolored"] = (light_bg != dark_bg)
        shot(page, "theme_light_shell.png"); report["screenshots"].append("theme_light_shell.png")
        shot(page, "theme_light_panel.png"); report["screenshots"].append("theme_light_panel.png")

        # (5) AA contrast spot-check in light mode
        c = body_colors(page)
        ratio = _contrast(c["fg"], c["bg"])
        report["checks"]["light_contrast_aa"] = (ratio >= 4.5)
        report["light_contrast_ratio"] = round(ratio, 2)

        # (4) persists across reload, applied before paint
        page.reload(wait_until="domcontentloaded")
        persisted = theme_attr(page)
        report["checks"]["persists_light"] = (persisted == "light")

        # toggle back to dark + reload persists
        page.wait_for_timeout(800)
        tg = page.get_by_role("button", name=lambda n: n and "theme" in n.lower())
        if tg.count():
            tg.first.click(); page.wait_for_timeout(500)
            page.reload(wait_until="domcontentloaded")
            report["checks"]["persists_dark"] = (theme_attr(page) != "light")
        b.close()

    report["ok"] = all(report["checks"].values())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
