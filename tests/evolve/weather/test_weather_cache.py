"""Bound test for weather.caching.serve-fresh-background-refresh (ev-22).

Offline / deterministic — pure-stdlib ``unittest``, no real network, no real
config backend. The cache time source is swapped per-test; the background
gating tests stub the tool-level helpers ``_refresh_once`` drives.
"""
import sys
import types
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

# Offline substrate: apps.weather.tools imports app_platform.time / .config /
# .location, whose real modules want psycopg2 + a live DB. Stub the leaves of
# that chain so the import stays pure-stdlib (mirrors test_weather_tools.py).
if "app_platform.time" not in sys.modules:
    _t = types.ModuleType("app_platform.time")
    _t.get_timezone = lambda user_id=None: ZoneInfo("UTC")
    sys.modules["app_platform.time"] = _t

if "app_platform.settings" not in sys.modules:
    _s = types.ModuleType("app_platform.settings")
    _s.get = lambda *a, **k: k.get("default")
    _s.set = lambda *a, **k: None
    _s.is_configured = lambda *a, **k: False
    sys.modules["app_platform.settings"] = _s

if "app_platform.config" not in sys.modules:
    _c = types.ModuleType("app_platform.config")
    # default-returning stub; the real _cache_settings is patched in tests anyway
    _c.get = lambda key, default=None, **k: default
    sys.modules["app_platform.config"] = _c

from apps.weather import cache as wcache  # noqa: E402
from apps.weather import tools  # noqa: E402
from apps.weather import background  # noqa: E402


_PLACE = {"lat": 30.27, "lon": -97.74, "label": "Austin",
          "country_code": "US", "region": "TX"}


class CacheCoreTests(unittest.TestCase):
    def setUp(self):
        wcache.clear()
        self.t = 1000.0
        self._orig_now = wcache._now
        wcache._now = lambda: self.t

    def tearDown(self):
        wcache._now = self._orig_now
        wcache.clear()

    # (1) SERVE-IF-FRESH
    def test_serve_if_fresh(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return f"v{calls['n']}"

        v1 = wcache.cached_fetch("u", fetcher, 300, True)
        self.t += 100  # still within window
        v2 = wcache.cached_fetch("u", fetcher, 300, True)
        self.assertEqual(v1, "v1")
        self.assertEqual(v2, "v1")
        self.assertEqual(calls["n"], 1)  # fetcher ran exactly once

    # (2) STALE EXPIRY -> REFETCH
    def test_stale_expiry_refetch(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return f"v{calls['n']}"

        self.assertEqual(wcache.cached_fetch("u", fetcher, 300, True), "v1")
        self.t += 301  # past the freshness window
        self.assertEqual(wcache.cached_fetch("u", fetcher, 300, True), "v2")
        self.assertEqual(calls["n"], 2)

    # (3) INDEPENDENT KEYS
    def test_independent_keys(self):
        self.assertEqual(wcache.cached_fetch("a", lambda: "A", 300, True), "A")
        self.assertEqual(wcache.cached_fetch("b", lambda: "B", 300, True), "B")
        # "a" still holds its own value (warming "b" didn't touch it)
        self.assertEqual(wcache.cached_fetch("a", lambda: "X", 300, True), "A")

    # (4) STALE-ON-FAILURE
    def test_stale_on_failure(self):
        self.assertEqual(wcache.cached_fetch("u", lambda: "good", 300, True), "good")
        self.t += 10_000  # now well past freshness

        def boom():
            raise RuntimeError("network down")

        # graceful degradation: last stored value, not an exception
        self.assertEqual(wcache.cached_fetch("u", boom, 300, True), "good")

    # (5) COLD-MISS RE-RAISE (must NOT return None / store)
    def test_cold_miss_reraise(self):
        def boom():
            raise RuntimeError("network down")

        with self.assertRaises(RuntimeError):
            wcache.cached_fetch("u", boom, 300, True)
        self.assertNotIn("u", wcache._ENTRIES)

    # (6) DISABLED BYPASS
    def test_disabled_bypass(self):
        calls = {"n": 0}

        def fetcher():
            calls["n"] += 1
            return "v"

        wcache.cached_fetch("u", fetcher, 300, False)
        wcache.cached_fetch("u", fetcher, 300, False)
        self.assertEqual(calls["n"], 2)  # always live
        self.assertNotIn("u", wcache._ENTRIES)  # never read/wrote the store

    # (7) INTERVAL CLAMP
    def test_interval_clamp(self):
        self.assertEqual(wcache.effective_ttl(0), 30)
        self.assertEqual(wcache.effective_ttl(-5), 30)
        self.assertEqual(wcache.effective_ttl(None), 30)
        self.assertEqual(wcache.effective_ttl("nope"), 30)
        self.assertEqual(wcache.effective_ttl(5), 300)


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        wcache.clear()

    def tearDown(self):
        wcache.clear()

    # (8) WARMED-KEY IDENTITY — background warms the same URL the tool reads
    def test_warmed_key_identity(self):
        captured = []

        def fake_cf(url, fetcher, ttl, enabled):
            captured.append(url)
            return {"current": {}}

        with mock.patch.object(tools, "cached_fetch", fake_cf), \
                mock.patch.object(tools, "_cache_settings", lambda: (True, 300)), \
                mock.patch.object(tools, "_resolve_place", lambda location="": (_PLACE, None)), \
                mock.patch.object(tools, "_fetch_json", lambda url, **k: {"current": {}}):
            tool_url = tools._current_weather_url(_PLACE)
            background._refresh_once()

        self.assertIn(tool_url, captured)
        # helper is byte-identical across calls (deterministic param order)
        self.assertEqual(tools._current_weather_url(_PLACE), tool_url)

    # (9) BACKGROUND GATING
    def test_background_gating(self):
        fetches = []

        def record(url, f, ttl, en):
            fetches.append(url)
            return {"x": 1}

        fetch_json = lambda url, **k: {"x": 1}

        # (a) caching disabled -> no fetch
        with mock.patch.object(tools, "cached_fetch", record), \
                mock.patch.object(tools, "_fetch_json", fetch_json), \
                mock.patch.object(tools, "_cache_settings", lambda: (False, 300)), \
                mock.patch.object(tools, "_resolve_place", lambda location="": (_PLACE, None)):
            background._refresh_once()
        self.assertEqual(fetches, [])

        # (b) enabled but NO configured location -> no fetch
        with mock.patch.object(tools, "cached_fetch", record), \
                mock.patch.object(tools, "_fetch_json", fetch_json), \
                mock.patch.object(tools, "_cache_settings", lambda: (True, 300)), \
                mock.patch.object(tools, "_resolve_place", lambda location="": (None, "no location")):
            background._refresh_once()
        self.assertEqual(fetches, [])

        # (c) enabled + a configured home -> the four standard lookups fetched
        with mock.patch.object(tools, "cached_fetch", record), \
                mock.patch.object(tools, "_fetch_json", fetch_json), \
                mock.patch.object(tools, "_cache_settings", lambda: (True, 300)), \
                mock.patch.object(tools, "_resolve_place", lambda location="": (_PLACE, None)):
            background._refresh_once()
        self.assertEqual(len(fetches), 4)

        # (d) a fetcher raising does NOT propagate out of _refresh_once
        def boom(url, f, ttl, en):
            raise RuntimeError("down")

        with mock.patch.object(tools, "cached_fetch", boom), \
                mock.patch.object(tools, "_fetch_json", fetch_json), \
                mock.patch.object(tools, "_cache_settings", lambda: (True, 300)), \
                mock.patch.object(tools, "_resolve_place", lambda location="": (_PLACE, None)):
            background._refresh_once()  # must not raise


if __name__ == "__main__":
    unittest.main()
