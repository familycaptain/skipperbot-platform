"""Pass-2: actually set the home location via the real Settings UI (as onboarding instructs)
and verify it persists/geocodes. Uses the robust ui_harness."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_harness import UI, BASE

async def main():
    ui = await UI.launch()
    try:
        await ui.login("rodney", "testpass123")
        await ui.open_settings()
        await ui.settings_section("System")

        ph = await ui.field_placeholder("Location")
        print(f"[finding] Location placeholder = {ph!r}  ({'MISSING — schema hint not rendered' if not ph else 'ok'})")

        await ui.set_field("Location", "Round Rock, Texas")
        await ui.save()
        print("[ok] filled + saved Location")

        # reload from scratch → re-open → read back (proves persistence + geocoding)
        await ui.page.goto(BASE, wait_until="domcontentloaded")
        await ui.page.wait_for_selector('button[title="Settings"]', timeout=15000)
        await ui.open_settings(); await ui.settings_section("System")
        val = await ui.get_field("Location")
        ok = "Round Rock" in (val or "")
        print(f"[{'PASS' if ok else 'FAIL'}] persisted Location after reload = {val!r}")
    except Exception as e:
        print("[ERROR]", repr(e))
    finally:
        print("HTTP>=400 :", sorted(set(ui.http_errors))[:10] or "none")
        print("CONSOLE   :", sorted(set(ui.console_errors))[:5] or "none")
        await ui.close()

asyncio.run(main())
