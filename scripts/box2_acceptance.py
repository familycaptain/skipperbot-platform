#!/usr/bin/env python3
"""Box-2 acceptance harness (Phase 1) — the reusable spine the validation agent drives.

A `Session` wraps a logged-in Playwright page with high-level primitives (open_app, click, fill,
select, send_chat). `send_chat` returns HARD EVIDENCE — the assistant's answer AND the actual
tool-calls that fired (pulled from /api/chat/history) — so judgments are grounded in what really
happened, not in scraped vibes. `run_scenario` executes a declarative scenario and reports per-step
pass/fail with that evidence.

The chat checks deliberately use VARIED phrasing + assert the RIGHT TOOL fired — the exact thing a
brittle string-match implementation fails (and that author-written bound tests miss).

Runs on box 2 against the live dockerized Skipper.
  python box2_acceptance.py            # run the built-in demo scenario
"""
import os, re, json, time
BASE = os.environ.get("QA_BASE", "http://localhost:8000")
USER = os.environ.get("QA_USER", "evolve_qa")
PW = open(os.path.expanduser("~/.evolve_qa_pw")).read().strip()
SHOTS = os.path.expanduser("~/evolve-qa-shots"); os.makedirs(SHOTS, exist_ok=True)
from playwright.sync_api import sync_playwright


class Session:
    def __init__(self, page):
        self.page = page

    # --- lifecycle ---
    def login(self, user=USER, pw=PW):
        p = self.page
        p.goto(BASE, wait_until="networkidle")
        p.get_by_role("textbox").first.fill(user)
        p.keyboard.press("Enter")
        p.wait_for_selector("input[type=password]", timeout=15000)
        p.locator("input[type=password]").first.fill(pw)
        p.keyboard.press("Enter")
        for _ in range(50):
            if p.evaluate("() => localStorage.getItem('skipperbot_token')"):
                return True
            p.wait_for_timeout(500)
        raise RuntimeError("login failed (no token)")

    # --- UI primitives ---
    def screenshot(self, name): self.page.screenshot(path=os.path.join(SHOTS, name))
    def ui_text(self): return self.page.evaluate("() => document.body.innerText")
    def settle(self, ms=800):
        for _ in range(20):
            self.page.wait_for_timeout(400)
            if "loading" not in self.ui_text().lower(): break
        self.page.wait_for_timeout(ms)

    def open_app(self, name):
        self.page.get_by_role("button", name=name, exact=True).first.click(); self.settle()

    def click(self, text):
        self.page.get_by_role("button", name=re.compile(re.escape(text), re.I)).first.click(); self.settle()

    def fill(self, value, placeholder=None, input_type=None):
        loc = (self.page.locator(f"input[placeholder*='{placeholder}']") if placeholder
               else self.page.locator(f"input[type={input_type}]"))
        loc.first.fill(value)

    def select(self, label):
        self.page.locator("select").first.select_option(label=label)

    # --- chat (returns evidence) ---
    def history(self, limit=8):
        return self.page.evaluate("""async (limit) => {
            const tok = localStorage.getItem('skipperbot_token');
            const r = await fetch('/api/chat/history?limit='+limit, {headers:{Authorization:'Bearer '+tok}});
            return await r.json();
        }""", limit)

    def send_chat(self, text, wait_s=60):
        before = len(self.history().get("messages") or [])
        ta = self.page.locator("textarea"); ta.first.click(); ta.first.fill(text)
        self.page.keyboard.press("Enter")
        msgs, deadline = [], time.time() + wait_s
        while time.time() < deadline:
            self.page.wait_for_timeout(3000)
            msgs = self.history().get("messages") or []
            if len(msgs) > before and any(m.get("role") == "bot" and m.get("content") for m in msgs[before:]):
                break
        new = msgs[before:] if len(msgs) > before else msgs[-6:]
        answer = next((m.get("content", "") for m in reversed(new) if m.get("role") == "bot"), "")
        tools = [{"tool": m.get("toolName"), "args": m.get("toolArgs")} for m in new if m.get("role") == "tool_call"]
        return {"asked": text, "answer": answer, "tool_calls": tools}


def run_scenario(sess, scenario):
    """Execute a declarative scenario; return a report with per-step pass/fail + evidence."""
    results = []
    for i, step in enumerate(scenario["steps"]):
        kind = step["action"]
        rec = {"step": i, "action": kind}
        try:
            if kind == "open_app":       sess.open_app(step["name"])
            elif kind == "click":        sess.click(step["text"])
            elif kind == "fill":         sess.fill(step["value"], step.get("placeholder"), step.get("input_type"))
            elif kind == "select":       sess.select(step["label"])
            elif kind == "expect_ui":
                rec["pass"] = step["contains"] in sess.ui_text(); rec["contains"] = step["contains"]
            elif kind == "chat":
                ev = sess.send_chat(step["text"])
                rec["evidence"] = ev
                checks = {}
                if "expect_tool" in step:
                    checks["right_tool_fired"] = any(t["tool"] == step["expect_tool"] for t in ev["tool_calls"])
                if "expect_answer_contains" in step:
                    checks["answer_reflects_data"] = step["expect_answer_contains"].lower() in (ev["answer"] or "").lower()
                rec["checks"] = checks
                rec["pass"] = all(checks.values()) if checks else None
            else:
                rec["error"] = f"unknown action {kind}"
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"; rec["pass"] = False
        results.append(rec)
    judged = [r for r in results if r.get("pass") is not None]
    return {"scenario": scenario["name"],
            "passed": all(r.get("pass") for r in judged) if judged else None,
            "steps": results}


# --- built-in demo: varied-phrasing chat over real UI data (reuses the schedule already in box2) ---
DEMO = {
    "name": "auto maintenance — varied-phrasing chat hits the right tool",
    "steps": [
        {"action": "open_app", "name": "Auto"},
        {"action": "click", "text": "Tesla Model 3"},
        {"action": "click", "text": "Maintenance"},
        {"action": "expect_ui", "contains": "Cabin Air Filter Replacement"},
        # NOT the literal phrasing — an LLM-intent test; we assert the RIGHT tool fired + data reflected
        {"action": "chat", "text": "anything I need to service soon on the Model 3?",
         "expect_tool": "get_vehicle_maintenance", "expect_answer_contains": "Cabin Air Filter"},
    ],
}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", help="JSON file: one scenario object or a list of them (default: built-in demo)")
    a = ap.parse_args()
    scenarios = [DEMO]
    if a.scenario:
        loaded = json.load(open(os.path.expanduser(a.scenario)))
        scenarios = loaded if isinstance(loaded, list) else [loaded]

    reports = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        sess = Session(b.new_context(viewport={"width": 1400, "height": 900}).new_page())
        sess.login(); print("✓ logged in")
        for sc in scenarios:
            reports.append(run_scenario(sess, sc))
        b.close()
    out = {"all_passed": all(r.get("passed") for r in reports if r.get("passed") is not None),
           "scenarios": reports}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
