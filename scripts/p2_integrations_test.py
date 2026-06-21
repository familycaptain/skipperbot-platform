"""Pass-2: open Settings -> Integrations (where onboarding sends users for 'other integrations
e.g. Trello') and check what's actually configurable there. Onboarding implies Trello lives here;
the code says it's in the Lists app's settings. Verify live."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_harness import UI

async def main():
    ui = await UI.launch()
    try:
        await ui.login("rodney", "testpass123")
        await ui.open_settings()
        await ui.settings_section("Integrations")
        labels = await ui.page.evaluate("""() => [...document.querySelectorAll('label,h3,h4')]
            .map(e=>[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ').replace(/\\s+/g,' ').trim())
            .filter(t=>t && t.length<40)""")
        print("Integrations panel labels:", labels)
        has_trello = any("trello" in (l or "").lower() for l in labels)
        print(f"[{'note' if not has_trello else 'ok'}] Trello in Integrations panel: {has_trello}",
              "-> onboarding 'connect Trello in Settings -> Integrations' is MISLEADING (it's in the Lists app settings)"
              if not has_trello else "")
    except Exception as e:
        print("[ERROR]", repr(e))
    finally:
        await ui.close()

asyncio.run(main())
