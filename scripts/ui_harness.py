"""
ui_harness.py — a ROBUST Playwright harness for driving the Skipper web app, built to be the
reusable Gate-3 UI-validation engine (drive real screens like a user, verify, screenshot/log on
failure). Hardened against the real friction we hit doing it by hand:

  * React controlled inputs ignore Playwright .fill() → we set value via the native setter +
    dispatch input/change so onChange fires and the form goes dirty (Save enables).
  * SPA navigation is flaky → every nav waits for the TARGET element to appear and retries,
    instead of click + fixed sleep.
  * Anything blocking clicks (proactive onboarding cards / modals) is detected + reported.
  * Every console error + HTTP>=400 is captured; failures screenshot to /tmp/ui_*.png.

Usage (async):
    ui = await UI.launch()
    await ui.login("rodney", "testpass123")
    await ui.open_settings(); await ui.settings_section("System")
    await ui.set_field("Location", "Round Rock, Texas")
    await ui.save()
    print(await ui.get_field("Location"))
    await ui.close()
"""
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:8000"


class UIError(Exception):
    pass


class UI:
    def __init__(self, pw, browser, page):
        self._pw, self._browser, self.page = pw, browser, page
        self.console_errors, self.http_errors = [], []
        page.on("console", lambda m: self.console_errors.append(m.text[:120]) if m.type == "error" else None)
        page.on("response", lambda r: self.http_errors.append(f"{r.status} {r.url.split('localhost:8000')[-1][:60]}")
                if r.status >= 400 else None)

    @classmethod
    async def launch(cls, headless=True):
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        page = await (await browser.new_context(viewport={"width": 1440, "height": 900})).new_page()
        return cls(pw, browser, page)

    async def close(self):
        await self._browser.close(); await self._pw.stop()

    async def shot(self, name):
        try: await self.page.screenshot(path=f"/tmp/ui_{name}.png", full_page=True)
        except Exception: pass

    async def _blockers(self):
        """Report fixed/high-z overlays that could be intercepting clicks (e.g. onboarding cards)."""
        return await self.page.evaluate("""() => {
          const out=[];
          for (const el of document.querySelectorAll('div,section,aside')) {
            const s=getComputedStyle(el);
            if ((s.position==='fixed'||s.position==='absolute') && +s.zIndex>=40 &&
                el.offsetWidth>200 && el.offsetHeight>120) {
              out.push({z:s.zIndex, txt:(el.innerText||'').replace(/\\s+/g,' ').slice(0,60)});
            }
          } return out.slice(0,6);
        }""")

    async def login(self, user, pw):
        await self.page.goto(BASE, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_selector('input[placeholder="Username"]', timeout=8000)
        except PWTimeout:
            await self.page.wait_for_selector('button[title="Settings"]', timeout=8000)
            return  # already authenticated
        await self.page.fill('input[placeholder="Username"]', user)
        await self.page.click('button:has-text("Continue")')
        await self.page.wait_for_selector('input[placeholder="Password"]', timeout=8000)
        await self.page.fill('input[placeholder="Password"]', pw)
        await self.page.click('button:has-text("Sign In")')
        await self.page.wait_for_selector('button[title="Settings"]', timeout=15000)
        await self.page.wait_for_timeout(800)  # let initial data settle

    async def _click_until(self, click_sel, expect_sel, what, tries=4):
        """Click click_sel, wait for expect_sel; retry. Self-diagnoses on final failure."""
        for i in range(tries):
            try:
                await self.page.click(click_sel, timeout=6000)
                await self.page.wait_for_selector(expect_sel, timeout=6000)
                return
            except Exception:
                blk = await self._blockers()
                if blk:  # something is overlaying — try to dismiss with Escape, then retry
                    await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(900)
        await self.shot(f"FAIL_{what}")
        raise UIError(f"{what}: could not click {click_sel!r} -> {expect_sel!r}. blockers={await self._blockers()}")

    async def open_settings(self):
        await self._click_until('button[title="Settings"]', 'button:has-text("System")', "open_settings")

    async def settings_section(self, name):
        # Each curated/section panel shows a Save button or its fields; wait for Save to exist.
        await self._click_until(f'button:has-text("{name}")', 'button:has-text("Save")', f"section_{name}")
        await self.page.wait_for_timeout(500)

    async def open_section_text(self, name, expect_text):
        """Open a Settings section that isn't a Save-button panel (e.g. Members), waiting for a
        known piece of its text to confirm it rendered."""
        await self._click_until(f'button:has-text("{name}")', f'text={expect_text}', f"section_{name}")
        await self.page.wait_for_timeout(500)

    async def click_button(self, text, wait=2000):
        await self.page.click(f'button:has-text("{text}")', timeout=8000)
        await self.page.wait_for_timeout(wait)

    async def _tag_field(self, label):
        # Find the first form control AFTER an element whose OWN direct text includes the label.
        # Works whether the label is a <label> (System panel) or a header/div (Members panel),
        # and the direct-text match avoids a big container matching prematurely.
        ok = await self.page.evaluate("""(label)=>{
          const own = el => [...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ').replace(/\\s+/g,' ').trim();
          const all=[...document.querySelectorAll('label,h1,h2,h3,h4,h5,p,span,div,input,textarea,select')];
          let f=false;
          for(const el of all){
            if(!f){ if(own(el).includes(label)) f=true; }
            else if(['INPUT','TEXTAREA','SELECT'].includes(el.tagName)){ el.setAttribute('data-uih','f'); return el.tagName; }
          } return false; }""", label)
        if not ok:
            await self.shot("FAIL_field"); raise UIError(f"field not found for label {label!r}")
        return ok

    async def set_field(self, label, value):
        tag = await self._tag_field(label)
        await self.page.evaluate("""(val)=>{
          const inp=document.querySelector('[data-uih=f]');
          const proto = inp.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype
                       : inp.tagName==='SELECT'?HTMLSelectElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(inp,val);
          inp.dispatchEvent(new Event('input',{bubbles:true}));
          inp.dispatchEvent(new Event('change',{bubbles:true}));
          inp.removeAttribute('data-uih');
        }""", value)
        return tag

    async def get_field(self, label):
        await self._tag_field(label)
        return await self.page.evaluate("""()=>{const e=document.querySelector('[data-uih=f]'); const v=e.value; e.removeAttribute('data-uih'); return v;}""")

    async def field_placeholder(self, label):
        await self._tag_field(label)
        return await self.page.evaluate("""()=>{const e=document.querySelector('[data-uih=f]'); const v=e.placeholder||''; e.removeAttribute('data-uih'); return v;}""")

    async def save(self):
        try:
            await self.page.wait_for_function(
                """()=>{const b=[...document.querySelectorAll('button')].find(x=>/^save$/i.test(x.innerText.trim()));return b && !b.disabled;}""",
                timeout=6000)
        except PWTimeout:
            await self.shot("FAIL_save_disabled")
            raise UIError("Save never enabled after edit (form not dirty?)")
        await self.page.click('button:has-text("Save")')
        await self.page.wait_for_timeout(2500)  # save + any geocode round-trip
