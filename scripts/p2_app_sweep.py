"""Pass-2 bug-scout: open every desktop app and capture broken screens — console errors, HTTP>=400,
empty/blank renders. Broad first pass to surface bug surfaces; deep-dive + issue-log the hits."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_harness import UI, BASE

async def main():
    ui = await UI.launch()
    findings = []
    try:
        await ui.login("rodney", "testpass123")
        tiles = await ui.app_tiles()
        print(f"apps on desktop: {len(tiles)}")
        for name in tiles:
            # reload to a fresh launcher between apps (session persists in localStorage)
            await ui.page.goto(BASE, wait_until="domcontentloaded")
            await ui.page.wait_for_selector('button[title*="hide from your desktop"]', timeout=12000)
            ui.http_errors.clear(); ui.console_errors.clear()
            try:
                await ui.open_app(name)
                # crude blank-screen check: visible text length of the app region
                txt = await ui.page.evaluate("()=>document.body.innerText.length")
                http = sorted(set(e for e in ui.http_errors if 'localhost' not in e or '/api' in e))
                cons = sorted(set(ui.console_errors))
                bad = [e for e in http if e.split()[0] in ('500','502','503','404','403','401')]
                status = "ok"
                if bad: status = f"HTTP {bad[:4]}"
                elif cons: status = f"console {cons[:2]}"
                elif txt < 40: status = f"near-blank (textlen={txt})"
                print(f"  {name:16} -> {status}")
                if status != "ok":
                    findings.append((name, status))
                    await ui.shot(f"app_{name.replace(' ','_')}")
            except Exception as e:
                print(f"  {name:16} -> OPEN FAILED: {e}")
                findings.append((name, f"open failed: {e}"))
        print("\n=== FINDINGS (candidates to deep-dive + issue-log) ===")
        for n, s in findings: print(f"  {n}: {s}")
        if not findings: print("  none — all apps opened clean")
    finally:
        await ui.close()

asyncio.run(main())
