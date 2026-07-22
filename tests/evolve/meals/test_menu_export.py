"""Meals menu export — the restored page and honest 404s on both standalone routes.

Clicking "Export menu PDF" in Meals opened a page showing the raw text
`[{"error":"Meal menu page not found"},404]`. Two defects: web/meal-menu.html was
lost in the fresh-start squash, and the route's fallback returned a Flask-style
`{...}, 404` tuple, which FastAPI serializes as a 200 whose body is a two-element
array — a response that lies about its status.

The page is a LITERAL PORT of the pre-public original; its markup and CSS are
normative. PART 1 binds the reported defect with real HTTP; PART 2 scopes the
source check to the two handlers; PART 3 byte-compares the ported stylesheet so a
restyle cannot pass; PARTS 4-6 cover parity, wiring, and the injection hardening
that closes the ported file's live reflected-XSS hole.

Run: python -m unittest tests.evolve.meals.test_menu_export
"""
import hashlib
import os
import re
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# The port source the page must remain faithful to, vendored as a fixture so the
# byte-compare runs on EVERY host. Kept beside the test on purpose: pointing at a
# path outside the repo makes the strongest assertion here skip itself silently
# anywhere but the machine that happened to have the file.
ORIGINAL = os.path.join(os.path.dirname(__file__), "fixtures", "meal-menu-original.html")
ORIGINAL_MD5 = "5ed863cc9490be83c7ffb8bcf54e886f"

# Style rules the port is allowed to ADD on top of the original's stylesheet.
# Anything else differing is a restyle, and a restyle is a failure.
ALLOWED_STYLE_ADDITIONS = {
    ".menu-hint",
    ".filter-chips",
    ".filter-chip",
    ".filter-chip button",
    ".filter-chip button:hover",
    ".link-btn",
}


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _style_block(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    return m.group(1) if m else ""


def _rules(css):
    """{selector: normalized-declarations} for every top-level rule."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(sel.split())
        body = " ".join(body.split())
        if sel:
            out.setdefault(sel, []).append(body)
    return out


def _func_body(src, name):
    """Source of one `async def <name>(...)` up to the next top-level def/decorator."""
    m = re.search(r"^async def %s\(" % re.escape(name), src, re.M)
    assert m, "handler %s not found" % name
    rest = src[m.start():]
    nxt = re.search(r"\n(?=@app\.|def |async def |# ──)", rest[1:])
    return rest[: nxt.start() + 1] if nxt else rest


class MealMenuRoutes404(unittest.TestCase):
    """PART 1 — real HTTP. This is what actually binds the reported defect."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest("fastapi TestClient unavailable: %s" % exc)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.testclient import TestClient
        import agent

        # Mount only the two handlers under test — importing agent's full app
        # would pull in the auth gate and the SPA catch-all.
        app = FastAPI()
        app.get("/capture")(agent.serve_capture_page)
        app.get("/meal-menu")(agent.serve_meal_menu_page)
        app.get("/meal-menu.html")(agent.serve_meal_menu_page)
        assert FileResponse  # imported for parity with the handlers
        return TestClient(app, raise_server_exceptions=False)

    def test_meal_menu_page_is_served_when_the_asset_exists(self):
        client = self._client()
        res = client.get("/meal-menu.html")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers.get("content-type", ""))

    def test_meal_menu_missing_asset_is_a_real_404_not_a_200_array(self):
        import agent
        original = agent._MEAL_MENU_HTML
        agent._MEAL_MENU_HTML = agent.Path("/nonexistent/meal-menu.html")
        try:
            res = self._client().get("/meal-menu.html", headers={"accept": "application/json"})
        finally:
            agent._MEAL_MENU_HTML = original
        self.assertEqual(res.status_code, 404, "missing page must be a real 404, not a 200")
        self.assertNotIsInstance(res.json(), list, "must not serialize as the [{...},404] array")
        self.assertEqual(res.json().get("error"), "Meal menu page not found")

    def test_capture_missing_asset_is_a_real_404_not_a_200_array(self):
        # web/capture.html is ALSO absent from this repo (same squash), so this
        # is the live behaviour of /capture, not a hypothetical.
        res = self._client().get("/capture", headers={"accept": "application/json"})
        self.assertEqual(res.status_code, 404)
        self.assertNotIsInstance(res.json(), list)
        self.assertEqual(res.json().get("error"), "Capture page not found")

    def test_capture_is_served_when_the_asset_exists(self):
        import agent
        original = agent._CAPTURE_HTML
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
            fh.write("<!DOCTYPE html><title>capture</title>")
            tmp = fh.name
        agent._CAPTURE_HTML = agent.Path(tmp)
        try:
            res = self._client().get("/capture")
            self.assertEqual(res.status_code, 200)
            self.assertIn("text/html", res.headers.get("content-type", ""))
        finally:
            agent._CAPTURE_HTML = original
            os.unlink(tmp)

    def test_a_browser_gets_html_not_a_raw_json_blob(self):
        res = self._client().get("/capture", headers={"accept": "text/html"})
        self.assertEqual(res.status_code, 404)
        self.assertIn("text/html", res.headers.get("content-type", ""))
        self.assertNotIn('{"error"', res.text)


class MealMenuHandlerSource(unittest.TestCase):
    """PART 2 — source assertions SCOPED to the two handlers.

    agent.py keeps other bare-tuple returns by design (a repo-wide sweep is its
    own issue), so a file-wide assertion would be red on arrival.
    """

    def setUp(self):
        self.agent = _read("agent.py")

    def test_both_handlers_return_a_real_404_and_no_bare_tuple(self):
        for name in ("serve_meal_menu_page", "serve_capture_page"):
            body = _func_body(self.agent, name)
            self.assertNotRegex(body, r"\}, 404", "%s still returns a bare tuple" % name)
            self.assertRegex(body, r"_missing_page_404\(", "%s must use the 404 helper" % name)

    def test_the_helper_sets_a_real_404_status(self):
        helper = re.search(r"def _missing_page_404\(.*?\n\n\n", self.agent, re.S).group(0)
        self.assertIn("status_code=404", helper)
        self.assertIn("JSONResponse", helper)
        self.assertIn("HTMLResponse", helper)

    def test_htmlresponse_is_imported(self):
        self.assertRegex(self.agent, r"from fastapi\.responses import [^\n]*HTMLResponse")


class MealMenuPortFidelity(unittest.TestCase):
    """PART 3 — the port is the contract: byte-compare the stylesheet."""

    def setUp(self):
        self.page = _read("web/meal-menu.html")
        with open(ORIGINAL, "rb") as f:
            raw = f.read()
        self.assertEqual(hashlib.md5(raw).hexdigest(), ORIGINAL_MD5,
                         "the vendored port reference has been altered")
        self.original = raw.decode("utf-8")

    def test_stylesheet_matches_the_original_except_for_declared_additions(self):
        ported = _rules(_style_block(self.page))
        origin = _rules(_style_block(self.original))

        missing = sorted(set(origin) - set(ported))
        self.assertEqual(missing, [], "ported stylesheet dropped rules: %s" % missing)

        added = sorted(set(ported) - set(origin) - ALLOWED_STYLE_ADDITIONS)
        self.assertEqual(added, [], "undeclared style additions (a restyle): %s" % added)

        changed = [s for s in origin if s not in ALLOWED_STYLE_ADDITIONS and ported[s] != origin[s]]
        # @media print legitimately gains the .menu-hint hide rule.
        changed = [s for s in changed if s != "@media print"]
        self.assertEqual(changed, [], "ported rules were modified: %s" % changed)

    def test_print_block_hides_the_new_chrome_too(self):
        printed = _style_block(self.page).split("@media print", 1)[1]
        self.assertRegex(printed, r"\.controls\s*\{[^}]*display:\s*none")
        self.assertRegex(printed, r"\.menu-hint\s*\{[^}]*display:\s*none")


class MealMenuParity(unittest.TestCase):
    """PART 4 — structural parity with the original."""

    def setUp(self):
        self.page = _read("web/meal-menu.html")
        self.css = " ".join(_style_block(self.page).split())

    def test_pagination(self):
        self.assertRegex(self.page, r"ITEMS_PER_PAGE\s*=\s*6")
        self.assertRegex(self.css, r"\.menu-page \{ page-break-after: always")
        self.assertRegex(self.css, r"\.meal-item \{ page-break-inside: avoid")
        self.assertRegex(self.css, r"@page \{ margin: 0\.6in; size: letter portrait")

    def test_sort_is_photo_first_then_by_name(self):
        self.assertIn("localeCompare", self.page)
        self.assertRegex(self.page, r"a\.primary_photo \? 0 : 1")

    def test_header_and_section_copy(self):
        for text in ("Family Kitchen", "Curated Selections", "Selections", "Continued", "Family Menu"):
            self.assertIn(text, self.page)
        self.assertNotIn("Our Menu", self.page)
        self.assertIn("<title>Meal Menu</title>", self.page)
        self.assertIn("🍽 Menu Export", self.page)

    def test_exactly_one_h1_and_it_is_the_control_bar_heading(self):
        h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", self.page, re.S)
        self.assertEqual(len(h1s), 1, "the repeated menu title must not be an h1")
        self.assertIn("Menu Export", h1s[0])

    def test_no_photo_renders_the_placeholder_tile(self):
        self.assertIn("meal-item-nophoto", self.page)
        self.assertRegex(self.css, r"\.meal-item-nophoto \{[^}]*background: #f0e8d8")

    def test_ratings_are_clamped_and_announced(self):
        self.assertIn("star-filled", self.page)
        self.assertIn("star-empty", self.page)
        self.assertRegex(self.page, r"rating >= 1 && rating <= 5")
        self.assertRegex(self.page, r'aria-label",\s*"Rated ')
        self.assertRegex(self.page, r'setAttribute\("role", "img"\)')

    def test_the_printed_date_footer_survives_printing(self):
        self.assertIn("menu-footer", self.page)
        self.assertIn('"Printed "', self.page)
        printed = _style_block(self.page).split("@media print", 1)[1]
        self.assertNotIn("menu-footer", printed, "the date footer must not be hidden in print")


class MealMenuWiring(unittest.TestCase):
    """PART 5 — how the page talks to the API."""

    def setUp(self):
        self.page = _read("web/meal-menu.html")

    def test_meals_list_path_has_no_trailing_slash(self):
        # Only a path-TERMINATED slash is wrong; /tag-cloud is a legitimate sibling.
        self.assertNotRegex(self.page, r"/api/apps/meals/[?\"']")
        self.assertIn('"/api/apps/meals"', self.page)

    def test_include_photos_is_not_requested_and_primary_photo_is_used(self):
        self.assertNotIn("include_photos", self.page)
        self.assertIn("primary_photo", self.page)

    def test_all_three_filters_are_forwarded(self):
        for key in ('"tag"', '"q"', '"effort"'):
            self.assertIn(key, self.page)

    def test_photo_url_is_pinned_with_a_guard_and_encoded_id(self):
        self.assertRegex(self.page, r"\^uploads\\/")
        self.assertIn("/api/apps/images/", self.page)
        self.assertIn("encodeURIComponent(photo.id)", self.page)

    def test_print_is_triggered(self):
        self.assertIn("window.print()", self.page)

    def test_the_export_button_forwards_the_active_filters(self):
        jsx = _read("apps/meals/ui/MealsApp.jsx")
        launcher = jsx.split("/meal-menu.html")[0][-600:]
        for key in ('params.set("tag"', 'params.set("q"', 'params.set("effort"'):
            self.assertIn(key, launcher)


class MealMenuInjectionHardening(unittest.TestCase):
    """PART 6 — negative security assertions.

    The ported original carried a live zero-click reflected XSS: ?tag auto-ran the
    fetch and reached an innerHTML template through esc(), a single-quote-only
    JS-string escaper, plus a second entirely unescaped interpolation of the
    tag-derived subtitle. Wholesale createElement/textContent closes both.
    """

    def setUp(self):
        self.page = _read("web/meal-menu.html")
        body = self.page.split("</head>", 1)[1]
        # Inline handlers are a MARKUP concern, so strip the script block before
        # looking for them. Scanning the JS too makes any identifier beginning
        # with "on" (`var only = ...`) a false positive — the assertion fires on
        # correct code and the tempting "fix" is to rename the variable, which
        # keeps a broken oracle alive.
        self.markup = re.sub(r"<script>.*?</script>", "", body, flags=re.S)

    def test_no_html_injection_sinks(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "srcdoc"):
            self.assertNotIn(sink, self.page, "%s must not survive the conversion" % sink)

    def test_no_dynamic_code_evaluation(self):
        self.assertNotRegex(self.page, r"\beval\s*\(")
        self.assertNotRegex(self.page, r"\bnew Function\s*\(")
        self.assertNotRegex(self.page, r"\bset(?:Timeout|Interval)\s*\(\s*['\"]")

    def test_no_inline_event_handler_markup(self):
        # A real handler attribute is `on<name>="..."` inside a tag.
        self.assertNotRegex(self.markup, r"""\son[a-z]+\s*=\s*["']""",
                            "wire events with addEventListener, not on*= markup")

    def test_the_broken_escapers_are_deleted_not_left_dead(self):
        self.assertNotRegex(self.page, r"\bescHtml\s*\(")
        self.assertNotRegex(self.page, r"\besc\s*\(")

    def test_navigation_targets_are_hardcoded(self):
        # The photo <img>.src is the SINGLE permitted data-derived URL.
        self.assertNotRegex(self.page, r"location\.(href|assign|replace)\s*=")
        for m in re.findall(r"\.href\s*=\s*([^;\n]+)", self.page):
            self.assertRegex(m.strip(), r'^"/"?"?$|^"/"$', "href must be a hardcoded path: %s" % m)


if __name__ == "__main__":
    unittest.main()
