"""Pass-2: link a personal Discord ID via Settings → Members → "My Discord" (as onboarding
instructs), then verify it persisted. Different panel + save button than System — exercises the
harness's generality."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_harness import UI, BASE

TEST_ID = "123456789012345678"  # 18 digits (valid 17-20 range)

async def main():
    ui = await UI.launch()
    try:
        await ui.login("rodney", "testpass123")
        await ui.open_settings()
        await ui.open_section_text("Members", "My Discord")
        await ui.set_field("My Discord", TEST_ID)
        # button text is contextual: Link / Update / Unlink Discord
        for label in ("Link Discord", "Update Discord ID", "Update Discord", "Save"):
            try:
                await ui.click_button(label); print(f"[ok] clicked {label!r}"); break
            except Exception:
                continue
        # reload + read back
        await ui.page.goto(BASE, wait_until="domcontentloaded")
        await ui.page.wait_for_selector('button[title="Settings"]', timeout=15000)
        await ui.open_settings(); await ui.open_section_text("Members", "My Discord")
        val = await ui.get_field("My Discord")
        ok = TEST_ID in (val or "")
        print(f"[{'PASS' if ok else 'FAIL'}] persisted My Discord = {val!r}")
    except Exception as e:
        print("[ERROR]", repr(e))
    finally:
        print("HTTP>=400 :", sorted(set(ui.http_errors))[:10] or "none")
        await ui.close()

asyncio.run(main())
