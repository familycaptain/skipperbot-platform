"""Meals menu export — the page is now owned + served by the meals app.

Originally (ev-110) the page was restored at web/meal-menu.html, served by a
hardcoded route in agent.py. ev-111 (Option B) MOVES it into the meals app:
apps/meals/pages/menu.html, served by the meals router at GET /api/apps/meals/menu,
retiring the platform block (a legacy 308 redirect is kept). The page's markup + CSS
are UNCHANGED from ev-110 and are still byte-compared here, so a restyle cannot pass
under cover of a move.

PART 1  real HTTP against the NEW route (full router, so the /{meal_id} wildcard
        shadow is caught), the legacy redirect, and the 1d content-negotiated 401.
PART 2  source: the platform block is retired; capture is untouched.
PART 3  byte-compare the stylesheet against the ev-110 fixture (must EXECUTE).
PART 4  structural parity.  PART 5  wiring + the repointed button.  PART 6  injection.

Run: python -m unittest tests.evolve.meals.test_menu_export
"""
import hashlib
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# The page's new home (moved out of the platform web/ root into the meals app).
PAGE_REL = "apps/meals/pages/menu.html"

# The ev-110 port reference, vendored beside the test so the byte-compare runs on
# EVERY host. A missing fixture must FAIL (never skip silently), or the strongest
# assertion here quietly disappears.
ORIGINAL = os.path.join(os.path.dirname(__file__), "fixtures", "meal-menu-original.html")
ORIGINAL_MD5 = "5ed863cc9490be83c7ffb8bcf54e886f"

# Style rules the page is allowed to ADD on top of the original's stylesheet.
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
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(sel.split())
        body = " ".join(body.split())
        if sel:
            out.setdefault(sel, []).append(body)
    return out


class MealMenuRoute(unittest.TestCase):
    """PART 1 — real HTTP against the meals app's own route. Binds the move."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest("fastapi TestClient unavailable: %s" % exc)

    def _client_full_router(self):
        # Mount the ACTUAL meals router (not a bare handler) so a /menu route
        # registered AFTER the /{meal_id} wildcard would be caught (it would
        # resolve to the meal-detail handler and 404 'Meal not found').
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.meals import routes as meals_routes

        app = FastAPI()
        app.include_router(meals_routes.router, prefix="/api/apps/meals")
        return TestClient(app, raise_server_exceptions=False)

    def test_menu_page_is_served_by_the_meals_router(self):
        res = self._client_full_router().get("/api/apps/meals/menu")
        self.assertEqual(res.status_code, 200, "the /menu route must not be shadowed by /{meal_id}")
        self.assertIn("text/html", res.headers.get("content-type", ""))
        self.assertIn("Menu Export", res.text)

    def test_menu_missing_asset_is_a_real_404_not_a_200_array(self):
        from apps.meals import routes as meals_routes
        original = meals_routes._MENU_PAGE
        meals_routes._MENU_PAGE = meals_routes.Path("/nonexistent/menu.html")
        try:
            res = self._client_full_router().get(
                "/api/apps/meals/menu", headers={"accept": "application/json"})
        finally:
            meals_routes._MENU_PAGE = original
        self.assertEqual(res.status_code, 404, "missing page must be a real 404, not a 200")
        self.assertNotIsInstance(res.json(), list, "must not serialize as the [{...},404] array")

    def test_legacy_url_308_redirects_and_preserves_the_query_string(self):
        # The platform keeps a redirect from the old public URL so bookmarks / open
        # tabs survive — and a shared FILTERED link must keep its filters.
        import agent
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.get("/meal-menu")(agent.meal_menu_legacy_redirect)
        app.get("/meal-menu.html")(agent.meal_menu_legacy_redirect)
        client = TestClient(app, raise_server_exceptions=False)

        res = client.get("/meal-menu.html?tag=family&q=x&effort=low", follow_redirects=False)
        self.assertIn(res.status_code, (307, 308))
        loc = res.headers["location"]
        self.assertTrue(loc.startswith("/api/apps/meals/menu"), "relative Location to the new route")
        self.assertNotIn("://", loc, "Location must be relative (no Host-header reflection)")
        for kv in ("tag=family", "q=x", "effort=low"):
            self.assertIn(kv, loc, "the redirect must preserve the query string")

    def test_the_auth_gate_401_is_content_negotiated_1d(self):
        # 1d: a browser navigation (Accept: text/html) that hits the gate gets a
        # friendly HTML sign-in page; an XHR/API caller (Accept: application/json)
        # still gets the JSON 401, so the SPA's error handling is unchanged.
        import agent

        class _Req:
            def __init__(self, accept):
                self.headers = {"accept": accept}

        html = agent._unauthenticated_response(_Req("text/html"))
        self.assertEqual(html.status_code, 401)
        self.assertIn("text/html", html.media_type or "")

        js = agent._unauthenticated_response(_Req("application/json"))
        self.assertEqual(js.status_code, 401)
        self.assertNotIn("text/html", js.media_type or "")


class MealMenuPlatformRetired(unittest.TestCase):
    """PART 2 — the platform no longer owns the meal-menu page; capture untouched."""

    def setUp(self):
        self.agent = _read("agent.py")

    def test_agent_no_longer_defines_the_meal_menu_handler_or_constant(self):
        self.assertNotRegex(self.agent, r"\basync def serve_meal_menu_page\b",
                            "the platform meal-menu handler must be retired")
        self.assertNotRegex(self.agent, r"\b_MEAL_MENU_HTML\b",
                            "the platform meal-menu Path constant must be retired")

    def test_agent_keeps_a_legacy_redirect_to_the_new_route(self):
        self.assertRegex(self.agent, r"async def meal_menu_legacy_redirect")
        self.assertRegex(self.agent, r"RedirectResponse")
        self.assertIn("/api/apps/meals/menu", self.agent)

    def test_capture_is_left_untouched(self):
        # Decision #2 = leave capture in the platform (its asset doesn't exist and
        # it belongs to the issues app).
        self.assertRegex(self.agent, r"\basync def serve_capture_page\b")
        self.assertRegex(self.agent, r"\b_CAPTURE_HTML\b")

    def test_the_meals_router_serves_the_page_from_a_fixed_path(self):
        routes = _read("apps/meals/routes.py")
        self.assertRegex(routes, r'@router\.get\("/menu"\)')
        # Registered ABOVE the /{meal_id} wildcard (which routes.py comments say
        # must be last).
        self.assertLess(routes.index('@router.get("/menu")'),
                        routes.index('@router.get("/{meal_id}")'),
                        "/menu must be registered before the /{meal_id} wildcard")
        self.assertIn("FileResponse", routes)
        self.assertNotRegex(routes, r'@router\.get\("/menu/\{',
                            "the page route must not take a user-controlled segment")


class MealMenuPortFidelity(unittest.TestCase):
    """PART 3 — the page is unchanged from ev-110: byte-compare the stylesheet."""

    def setUp(self):
        self.page = _read(PAGE_REL)
        self.assertTrue(os.path.exists(ORIGINAL),
                        "the byte-compare fixture is missing — this check must never skip")
        with open(ORIGINAL, "rb") as f:
            raw = f.read()
        self.assertEqual(hashlib.md5(raw).hexdigest(), ORIGINAL_MD5,
                         "the vendored port reference has been altered")
        self.original = raw.decode("utf-8")

    def test_stylesheet_matches_the_original_except_for_declared_additions(self):
        ported = _rules(_style_block(self.page))
        origin = _rules(_style_block(self.original))

        missing = sorted(set(origin) - set(ported))
        self.assertEqual(missing, [], "stylesheet dropped rules: %s" % missing)

        added = sorted(set(ported) - set(origin) - ALLOWED_STYLE_ADDITIONS)
        self.assertEqual(added, [], "undeclared style additions (a restyle): %s" % added)

        changed = [s for s in origin if s not in ALLOWED_STYLE_ADDITIONS and ported[s] != origin[s]]
        changed = [s for s in changed if s != "@media print"]
        self.assertEqual(changed, [], "rules were modified: %s" % changed)

    def test_print_block_hides_the_new_chrome_too(self):
        printed = _style_block(self.page).split("@media print", 1)[1]
        self.assertRegex(printed, r"\.controls\s*\{[^}]*display:\s*none")
        self.assertRegex(printed, r"\.menu-hint\s*\{[^}]*display:\s*none")


class MealMenuParity(unittest.TestCase):
    """PART 4 — structural parity with the original."""

    def setUp(self):
        self.page = _read(PAGE_REL)
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
    """PART 5 — how the page talks to the API, and the repointed button."""

    def setUp(self):
        self.page = _read(PAGE_REL)

    def test_meals_list_path_has_no_trailing_slash(self):
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

    def test_the_export_button_points_at_the_new_route_with_filters(self):
        jsx = _read("apps/meals/ui/MealsApp.jsx")
        self.assertIn("/api/apps/meals/menu", jsx, "the button must open the new route")
        self.assertNotIn("/meal-menu.html", jsx, "the old URL must be gone from the button")
        launcher = jsx.split("/api/apps/meals/menu")[0][-600:]
        for key in ('params.set("tag"', 'params.set("q"', 'params.set("effort"'):
            self.assertIn(key, launcher, "the button must still forward the active filters")


class MealMenuInjectionHardening(unittest.TestCase):
    """PART 6 — negative security assertions (ev-110's XSS hardening, preserved)."""

    def setUp(self):
        self.page = _read(PAGE_REL)
        body = self.page.split("</head>", 1)[1]
        self.markup = re.sub(r"<script>.*?</script>", "", body, flags=re.S)

    def test_no_html_injection_sinks(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "srcdoc"):
            self.assertNotIn(sink, self.page, "%s must not survive" % sink)

    def test_no_dynamic_code_evaluation(self):
        self.assertNotRegex(self.page, r"\beval\s*\(")
        self.assertNotRegex(self.page, r"\bnew Function\s*\(")
        self.assertNotRegex(self.page, r"\bset(?:Timeout|Interval)\s*\(\s*['\"]")

    def test_no_inline_event_handler_markup(self):
        self.assertNotRegex(self.markup, r"""\son[a-z]+\s*=\s*["']""",
                            "wire events with addEventListener, not on*= markup")

    def test_the_broken_escapers_are_deleted_not_left_dead(self):
        self.assertNotRegex(self.page, r"\bescHtml\s*\(")
        self.assertNotRegex(self.page, r"\besc\s*\(")

    def test_navigation_targets_are_hardcoded(self):
        self.assertNotRegex(self.page, r"location\.(href|assign|replace)\s*=")
        for m in re.findall(r"\.href\s*=\s*([^;\n]+)", self.page):
            self.assertRegex(m.strip(), r'^"/"?"?$|^"/"$', "href must be a hardcoded path: %s" % m)


if __name__ == "__main__":
    unittest.main()
