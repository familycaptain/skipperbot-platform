"""Pass-2 cross-surface parity: verify items created via CHAT actually render in the app UIs
(charter: cross-surface parity). Run via the box2 venv: ~/p2venv/bin/python this. Assumes the chat
creates were already driven (buy paint -> To-Do; water the plants -> Chores)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_harness import UI, BASE

async def app_has(ui, app, needle):
    await ui.page.goto(BASE, wait_until="domcontentloaded")
    await ui.page.wait_for_selector('button[title*="hide from your desktop"]', timeout=12000)
    await ui.open_app(app)
    txt = (await ui.page.evaluate("()=>document.body.innerText") or "").lower()
    return needle.lower() in txt

async def main():
    ui = await UI.launch()
    try:
        await ui.login("rodney", "testpass123")
        for app, needle in [("To-Do", "buy paint"), ("Chores", "water the plants")]:
            try:
                ok = await app_has(ui, app, needle)
                print(f"[{'PASS' if ok else 'FAIL'}] {app} UI shows chat-created '{needle}': {ok}")
                if not ok:
                    await ui.shot(f"xsurface_{app}")
            except Exception as e:
                print(f"[ERROR] {app}: {e}")
    finally:
        print("HTTP>=400:", sorted(set(ui.http_errors))[:8] or "none")
        await ui.close()

asyncio.run(main())
