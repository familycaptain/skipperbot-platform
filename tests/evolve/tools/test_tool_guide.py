"""Tests for apps/tools/routes.py — guide names are public, resolvable, "/"-free.

Bound to spec tools.guide-viewer.resolvable-name.

BUG (baseline): GET /api/apps/tools/categories returned each packaged
category's internal ABSOLUTE ``_guide_path`` as its public ``guide`` field, and
GET /guide/{name} rejects any name containing "/" → every Tools-app guide showed
an absolute path and "Failed to load." FIX: /categories now derives a bare,
"/"-free, resolvable guide *name* (or null) per category; /guide is unchanged.

Offline/deterministic: the FastAPI dependency is stubbed so the routes module
imports without it, the routes are exercised by calling the async functions
directly (no TestClient, no network), and ``tool_router.TOOL_CATEGORIES`` is
monkeypatched. Real on-disk guides under apps/<id>/guide.md and prompts/guides/
are used for resolution.
"""
import asyncio
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path

# Repo root = .../skipperbot-platform-wt/poc-14 (this file is tests/evolve/tools/).
REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Offline substrate ────────────────────────────────────────────────────────
# apps/tools/routes.py imports ``from fastapi import APIRouter, HTTPException``.
# FastAPI isn't installed in the offline test substrate and isn't needed: we call
# the route coroutines directly. Stub a minimal fastapi module so the import works
# and HTTPException carries a status_code we can assert on.
if "fastapi" not in sys.modules:
    _fastapi = types.ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *a, **k):
            pass

        def get(self, *a, **k):
            def _decorator(fn):
                return fn
            return _decorator

    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    _fastapi.APIRouter = _APIRouter
    _fastapi.HTTPException = _HTTPException
    sys.modules["fastapi"] = _fastapi

from fastapi import HTTPException  # noqa: E402  (now the stub, or the real thing)


def _load_routes():
    """Import apps/tools/routes.py by file path (apps has no __init__.py)."""
    path = REPO_ROOT / "apps" / "tools" / "routes.py"
    spec = importlib.util.spec_from_file_location("apps_tools_routes_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A fake registry mirroring tool_router.merge_app_tool_routes shape:
#   packaged categories keyed "app:<id>", carrying an absolute _guide_path and
#   NO "guide" key. We pick real apps so on-disk resolution is exercised.
_ABS_AUTO = str(REPO_ROOT / "apps" / "auto" / "guide.md")
_ABS_WEATHER = str(REPO_ROOT / "apps" / "weather" / "guide.md")
_ABS_GHOST = str(REPO_ROOT / "apps" / "arcade" / "guide.md")  # file does NOT exist


def _fake_categories():
    return {
        # Packaged, has guide on disk.
        "app:auto": {
            "description": "Auto",
            "tools": ["a"],
            "keywords": [],
            "_guide_path": _ABS_AUTO,
        },
        # Packaged, has guide on disk — distinct from auto (regression check).
        "app:weather": {
            "description": "Weather",
            "tools": ["w"],
            "keywords": [],
            "_guide_path": _ABS_WEATHER,
        },
        # Packaged, _guide_path points at a non-existent file → guide must be None.
        "app:arcade": {
            "description": "Arcade",
            "tools": ["g"],
            "keywords": [],
            "_guide_path": _ABS_GHOST,
        },
        # Packaged with no guide info at all → None.
        "app:tools": {
            "description": "Tools",
            "tools": ["t"],
            "keywords": [],
        },
    }


class _PatchedRegistry:
    """Context manager that installs a stub ``tool_router`` with our categories
    and an empty legacy tool_routes.json view (routes.py reads the real file;
    we leave it, but our fake packaged cats are the focus)."""

    def __init__(self, cats):
        self.cats = cats
        self._saved = None

    def __enter__(self):
        self._saved = sys.modules.get("tool_router")
        stub = types.ModuleType("tool_router")
        stub.TOOL_CATEGORIES = self.cats
        sys.modules["tool_router"] = stub
        return self

    def __exit__(self, *exc):
        if self._saved is not None:
            sys.modules["tool_router"] = self._saved
        else:
            sys.modules.pop("tool_router", None)


def _run(coro):
    return asyncio.run(coro)


class ToolGuideCategoriesTest(unittest.TestCase):
    def setUp(self):
        self.routes = _load_routes()
        # Sanity: the real fixtures exist / don't exist as expected.
        self.assertTrue(Path(_ABS_AUTO).is_file(), "fixture apps/auto/guide.md missing")
        self.assertTrue(Path(_ABS_WEATHER).is_file(), "fixture apps/weather/guide.md missing")
        self.assertFalse(Path(_ABS_GHOST).is_file(), "apps/arcade/guide.md unexpectedly exists")

    def _categories(self):
        with _PatchedRegistry(_fake_categories()):
            data = _run(self.routes.api_tool_categories())
        return {c["id"]: c for c in data["categories"]}

    def test_packaged_guide_is_bare_name(self):
        cats = self._categories()
        self.assertEqual(cats["app:auto"]["guide"], "auto")
        self.assertEqual(cats["app:weather"]["guide"], "weather")

    def test_no_guide_category_is_none(self):
        cats = self._categories()
        # _guide_path present but file absent → None.
        self.assertIsNone(cats["app:arcade"]["guide"])
        # No guide info at all → None.
        self.assertIsNone(cats["app:tools"]["guide"])

    def test_no_guide_is_absolute_or_contains_slash(self):
        cats = self._categories()
        for cid, c in cats.items():
            g = c["guide"]
            if g is None:
                continue
            self.assertNotIn("/", g, f"{cid} guide contains '/': {g!r}")
            self.assertFalse(g.startswith("/"), f"{cid} guide is absolute: {g!r}")
            # Regression: never the internal absolute path.
            self.assertNotEqual(g, c.get("_guide_path"))

    def test_distinct_packaged_apps_distinct_guides(self):
        cats = self._categories()
        self.assertNotEqual(
            cats["app:auto"]["guide"], cats["app:weather"]["guide"],
            "distinct packaged apps must return distinct guide names",
        )

    def test_internal_guide_path_untouched(self):
        # The categories change must not strip _guide_path from the registry.
        fake = _fake_categories()
        with _PatchedRegistry(fake):
            _run(self.routes.api_tool_categories())
        self.assertEqual(fake["app:auto"]["_guide_path"], _ABS_AUTO)


class ToolGuideRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.routes = _load_routes()

    def test_each_nonnull_guide_round_trips(self):
        with _PatchedRegistry(_fake_categories()):
            data = _run(self.routes.api_tool_categories())
            for c in data["categories"]:
                if not c["guide"]:
                    continue
                res = _run(self.routes.api_tool_guide(c["guide"]))
                self.assertTrue(res["content"].strip(), f"empty guide for {c['guide']}")

    def test_guide_auto_returns_disk_content(self):
        res = _run(self.routes.api_tool_guide("auto"))
        on_disk = Path(_ABS_AUTO).read_text(encoding="utf-8")
        self.assertEqual(res["content"], on_disk)
        self.assertTrue(res["content"].strip())

    def test_traversal_guard_intact(self):
        for bad in ("foo/bar", "/etc/passwd", "..\\x", "apps/auto/guide.md"):
            with self.assertRaises(HTTPException) as ctx:
                _run(self.routes.api_tool_guide(bad))
            self.assertEqual(ctx.exception.status_code, 400, f"{bad!r} should be 400")

    def test_nonexistent_name_404(self):
        with self.assertRaises(HTTPException) as ctx:
            _run(self.routes.api_tool_guide("definitely-not-a-real-guide-xyz"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_md_suffix_tolerated_by_guide_route(self):
        # Legacy guide values carry a ".md" suffix and must resolve verbatim.
        # web.md exists under prompts/guides/.
        if (REPO_ROOT / "prompts" / "guides" / "web.md").is_file():
            res = _run(self.routes.api_tool_guide("web.md"))
            self.assertTrue(res["content"].strip())
        # And a packaged app id with a stray .md still resolves (suffix dropped).
        res2 = _run(self.routes.api_tool_guide("auto.md"))
        self.assertTrue(res2["content"].strip())


class LegacyGuideTest(unittest.TestCase):
    """Legacy (bare-keyed) categories return their declared guide verbatim when
    the prompts/guides file exists, else None — never re-suffixed, never '/'."""

    def setUp(self):
        self.routes = _load_routes()

    def test_legacy_guide_verbatim_when_present(self):
        # Drive the helper directly with a legacy-shaped category.
        root = self.routes._platform_root()
        if (root / "prompts" / "guides" / "web.md").is_file():
            g = self.routes._resolvable_guide(root, "web", {"guide": "web.md"})
            self.assertEqual(g, "web.md")
            # Round-trips through the guide route.
            res = _run(self.routes.api_tool_guide(g))
            self.assertTrue(res["content"].strip())

    def test_legacy_guide_none_when_file_absent(self):
        root = self.routes._platform_root()
        g = self.routes._resolvable_guide(root, "core", {"guide": "no-such-guide.md"})
        self.assertIsNone(g)

    def test_legacy_guide_with_slash_rejected(self):
        root = self.routes._platform_root()
        g = self.routes._resolvable_guide(root, "x", {"guide": "../secrets.md"})
        self.assertIsNone(g)


if __name__ == "__main__":
    unittest.main()
