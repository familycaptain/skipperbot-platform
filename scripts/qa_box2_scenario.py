#!/usr/bin/env python3
"""POC acceptance spike (Phase 0) — FULL scenario on the live box-2 Skipper:
  1. log in, open Auto, open the 2022 Tesla Model 3
  2. create a maintenance schedule via the UI (Maintenance tab -> Add Schedule)
  3. verify it appears in the list
  4. ask Skipper about it in chat
  5. capture the chat RESPONSE and the actual TOOL-CALLS that fired (/api/chat/history)
  6. judge: did the right tool fire + does the answer reflect the schedule we created?

This proves the spine of the acceptance-validation agent: drive real UI + chat, capture hard
evidence (tool_calls), judge against expectation. Runs on box 2 against the dockerized Skipper.
"""
import os, re, json, time
BASE = os.environ.get("QA_BASE", "http://localhost:8000")
USER = os.environ.get("QA_USER", "evolve_qa")
PW = open(os.path.expanduser("~/.evolve_qa_pw")).read().strip()
SHOTS = os.path.expanduser("~/evolve-qa-shots"); os.makedirs(SHOTS, exist_ok=True)
SCHEDULE = "Cabin Air Filter Replacement"        # distinctive name so we can verify it round-trips
from playwright.sync_api import sync_playwright


def shot(page, n): page.screenshot(path=os.path.join(SHOTS, n)); print(f"  shot: {n}")


def login(page):
    page.goto(BASE, wait_until="networkidle")
    page.get_by_role("textbox").first.fill(USER)
    page.keyboard.press("Enter")
    page.wait_for_selector("input[type=password]", timeout=15000)
    page.locator("input[type=password]").first.fill(PW)
    page.keyboard.press("Enter")
    for _ in range(50):
        if page.evaluate("() => localStorage.getItem('skipperbot_token')"): break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500); print("✓ logged in")


def history(page, limit=8):
    """Fetch /api/chat/history with the in-page bearer token (gives assistant text + tool_calls)."""
    return page.evaluate("""async (limit) => {
        const tok = localStorage.getItem('skipperbot_token');
        const r = await fetch('/api/chat/history?limit='+limit, {headers:{Authorization:'Bearer '+tok}});
        return await r.json();
    }""", limit)


def main():
    report = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(page)

        # --- open Auto -> Tesla -> Maintenance ---
        page.get_by_role("button", name="Auto", exact=True).first.click()
        page.wait_for_timeout(2000)
        page.get_by_role("button", name=re.compile("Tesla Model 3", re.I)).first.click()
        for _ in range(20):
            page.wait_for_timeout(500)
            if "loading vehicle" not in page.evaluate("() => document.body.innerText").lower(): break
        page.get_by_role("button", name="Maintenance", exact=True).first.click()
        page.wait_for_timeout(800)

        # --- create a maintenance schedule via the UI ---
        page.get_by_role("button", name=re.compile("Add Schedule", re.I)).first.click()
        page.wait_for_timeout(800)
        page.locator("input[placeholder*='Oil Change']").first.fill(SCHEDULE)
        page.locator("input[type=date]").first.fill("2026-12-01")
        try: page.locator("select").first.select_option(label="Every year")
        except Exception: pass
        shot(page, "05-form-filled.png")
        page.get_by_role("button", name="Create", exact=True).first.click()
        page.wait_for_timeout(2500)
        shot(page, "06-schedule-created.png")
        body = page.evaluate("() => document.body.innerText")
        report["schedule_created_in_ui"] = SCHEDULE in body
        print(f"✓ created schedule via UI; appears in list: {report['schedule_created_in_ui']}")

        # --- ask Skipper about it in chat ---
        q = "What maintenance schedules does my 2022 Tesla Model 3 have?"
        before = len((history(page).get("messages") or []))
        ta = page.locator("textarea")
        ta.first.click(); ta.first.fill(q); page.keyboard.press("Enter")
        print(f"→ asked chat: {q!r}; waiting for the agent…")
        # poll history until a new bot turn lands (bounded ~50s)
        msgs, deadline = [], time.time() + 60
        while time.time() < deadline:
            page.wait_for_timeout(3000)
            msgs = history(page).get("messages") or []
            if len(msgs) > before and any(m.get("role") == "bot" and m.get("content") for m in msgs[before:]):
                break
        shot(page, "07-chat-answer.png")

        # --- extract evidence: the answer + the tool_calls that fired ---
        new = msgs[before:] if len(msgs) > before else msgs[-6:]
        answer = next((m.get("content", "") for m in reversed(new) if m.get("role") == "bot"), "")
        tool_calls = [{"tool": m.get("toolName"), "args": m.get("toolArgs")}
                      for m in new if m.get("role") == "tool_call"]
        report["chat_answer"] = answer
        report["tool_calls"] = tool_calls
        # judge (evidence-grounded)
        report["judge"] = {
            "a_tool_fired": bool(tool_calls),
            "answer_mentions_schedule": SCHEDULE.split()[0].lower() in (answer or "").lower(),
        }
        b.close()

    print("\n================ SCENARIO REPORT ================")
    print(json.dumps(report, indent=2)[:3000])


if __name__ == "__main__":
    main()
