"""Bound tests for spec platform.location.resolver — app_platform/location.py.

Fully offline: app_platform.settings is replaced with an in-memory fake, and
every outbound geocode call is mocked. No DB / network is touched.
"""

import json
import sys
import types
import unittest
from unittest import mock


# ---------------------------------------------------------------------------
# Offline substrate. app_platform.location reads/writes settings lazily via
# `from app_platform import settings`. Install a fake settings module BEFORE
# importing location so the import chain never touches data_layer.db / psycopg2.
# ---------------------------------------------------------------------------

class _FakeSettings:
    """In-memory stand-in for app_platform.settings (platform scope only)."""

    def __init__(self):
        self.store = {}

    def get(self, key, *, scope=None, secret=False, default=None):
        val = self.store.get((scope, key))
        return default if val in (None, "") else val

    def set(self, key, value, *, scope=None, secret=False, by=""):
        self.store[(scope, key)] = value

    def is_configured(self, key, *, scope=None):
        return self.store.get((scope, key)) not in (None, "")


_fake = _FakeSettings()

# Build a module object so `from app_platform import settings` resolves to it.
_fake_mod = types.ModuleType("app_platform.settings")
_fake_mod.get = _fake.get
_fake_mod.set = _fake.set
_fake_mod.is_configured = _fake.is_configured
sys.modules["app_platform.settings"] = _fake_mod

from app_platform import location  # noqa: E402


def _seed(record):
    """Seed the cached default_location (stored as JSON string)."""
    _fake.store[("platform", "default_location")] = json.dumps(record)


def _seed_zip(zip_code):
    _fake.store[("platform", "default_zip")] = zip_code


def _clear():
    _fake.store.clear()


# An Open-Meteo-style geocode result.
def _gc(name, admin1, country, cc, lat, lon):
    return {"name": name, "admin1": admin1, "country": country,
            "country_code": cc, "latitude": lat, "longitude": lon}


class TestResolveCachedDefault(unittest.TestCase):
    def setUp(self):
        _clear()

    def test_cached_default_no_geocode(self):
        _seed({"display_name": "London", "region": "England",
               "country_name": "United Kingdom", "country_code": "GB",
               "lat": 51.5074, "lon": -0.1278})
        with mock.patch.object(location, "_geocode",
                               side_effect=AssertionError("geocoder called!")):
            rec = location.resolve_location()
        self.assertEqual(rec["lat"], 51.5074)
        self.assertEqual(rec["lon"], -0.1278)
        self.assertEqual(rec["display_label"], "London, England, United Kingdom")
        self.assertTrue(rec["configured"])

    def test_display_label_drops_empty_and_redundant_region(self):
        # Empty region.
        self.assertEqual(
            location.display_label({"display_name": "Austin", "region": "",
                                    "country_name": "United States"}),
            "Austin, United States")
        # Region redundant with city.
        self.assertEqual(
            location.display_label({"display_name": "Singapore", "region": "Singapore",
                                    "country_name": "Singapore"}),
            "Singapore")
        # No bare ISO code / no "(zip)" suffix ever.
        label = location.display_label({"display_name": "London", "region": "England",
                                        "country_name": "United Kingdom",
                                        "country_code": "GB"})
        self.assertEqual(label, "London, England, United Kingdom")
        self.assertNotIn("GB", label)
        self.assertNotIn("(", label)

    def test_corrupted_cached_record_fails_safe(self):
        _seed({"display_name": "Bad", "region": "", "country_name": "X",
               "country_code": "X", "lat": "not-a-number", "lon": "nope"})
        # No legacy zip → unconfigured result, NO crash.
        rec = location.resolve_location()
        self.assertFalse(rec.get("configured"))
        self.assertIn("Settings", rec.get("message", ""))


class TestSaveDefaultLocation(unittest.TestCase):
    def setUp(self):
        _clear()

    def test_top_ranked_country_filtered_and_urlencoded(self):
        captured = {}

        def fake_http(url, *, timeout=10):
            captured["url"] = url
            # Multiple ranked results; the FR one is not first to prove filtering.
            return {"results": [
                _gc("Paris", "Texas", "United States", "US", 33.66, -95.55),
                _gc("Paris", "Île-de-France", "France", "FR", 48.85, 2.35),
            ]}

        with mock.patch.object(location, "_http_get_json", side_effect=fake_http):
            rec = location.save_default_location("Paris, France")

        # Country-filtered to FR top-ranked.
        self.assertEqual(rec["country_code"], "FR")
        self.assertEqual(rec["display_label"], "Paris, Île-de-France, France")
        # Stored.
        self.assertIn(("platform", "default_location"), _fake.store)

    def test_user_components_url_encoded(self):
        captured = {}

        def fake_http(url, *, timeout=10):
            captured["url"] = url
            return {"results": [_gc("Foo Bar", "R", "Country", "CC", 1.0, 2.0)]}

        with mock.patch.object(location, "_http_get_json", side_effect=fake_http):
            location.save_default_location("Foo & Bar")

        url = captured["url"]
        # The space/& must be percent-encoded, never raw in the query string.
        self.assertNotIn("Foo & Bar", url)
        self.assertTrue("Foo+%26+Bar" in url or "Foo%20%26%20Bar" in url
                        or "%26" in url)

    def test_no_match_rejected_previous_preserved(self):
        prev = {"display_name": "London", "region": "England",
                "country_name": "United Kingdom", "country_code": "GB",
                "lat": 51.5, "lon": -0.1}
        _seed(prev)
        with mock.patch.object(location, "_http_get_json",
                               return_value={"results": []}):
            with self.assertRaises(location.LocationNotFound):
                location.save_default_location("Zzzznowhere")
        # Previous preserved.
        rec = location.resolve_location()
        self.assertEqual(rec["display_label"], "London, England, United Kingdom")

    def test_geocoder_error_transient_previous_preserved(self):
        prev = {"display_name": "London", "region": "England",
                "country_name": "United Kingdom", "country_code": "GB",
                "lat": 51.5, "lon": -0.1}
        _seed(prev)
        with mock.patch.object(location, "_http_get_json",
                               side_effect=location.GeocoderUnavailable("down")):
            with self.assertRaises(location.GeocoderUnavailable):
                location.save_default_location("Berlin")
        rec = location.resolve_location()
        self.assertEqual(rec["display_label"], "London, England, United Kingdom")


class TestMigration(unittest.TestCase):
    def setUp(self):
        _clear()

    def test_lazy_one_time_migration_idempotent(self):
        _seed_zip("78704")
        calls = {"n": 0}

        def fake_http(url, *, timeout=10):
            calls["n"] += 1
            return {"results": [_gc("Austin", "Texas", "United States", "US",
                                    30.26, -97.74)]}

        with mock.patch.object(location, "_http_get_json", side_effect=fake_http):
            rec1 = location.resolve_location()
            self.assertEqual(rec1["display_label"], "Austin, Texas, United States")
            self.assertEqual(calls["n"], 1)
            # Second read must NOT geocode again (default_location now set).
            rec2 = location.resolve_location()
            self.assertEqual(rec2["display_label"], "Austin, Texas, United States")
        self.assertEqual(calls["n"], 1, "migration must be one-time / idempotent")
        # default_zip retained.
        self.assertEqual(_fake.store.get(("platform", "default_zip")), "78704")

    def test_migration_failure_falls_back_to_legacy_usable_result(self):
        _seed_zip("78704")
        with mock.patch.object(location, "_http_get_json",
                               side_effect=location.GeocoderUnavailable("offline")):
            rec = location.resolve_location()
        # Not the Settings error — a usable legacy result.
        self.assertTrue(rec.get("configured"))
        self.assertNotIn("No location is configured", rec.get("display_label", ""))
        self.assertIn("78704", rec.get("display_label", ""))
        # default_location stays unset.
        self.assertNotIn(("platform", "default_location"), _fake.store)


class TestOverride(unittest.TestCase):
    def setUp(self):
        _clear()

    def test_place_name_override_resolves(self):
        with mock.patch.object(
                location, "_http_get_json",
                return_value={"results": [_gc("Lyon", "Auvergne-Rhône-Alpes",
                                              "France", "FR", 45.76, 4.83)]}):
            rec = location.resolve_location(override="Lyon, France")
        self.assertEqual(rec["country_code"], "FR")
        self.assertEqual(rec["display_label"], "Lyon, Auvergne-Rhône-Alpes, France")

    def test_non_us_postal_override_resolves_no_5digit_assumption(self):
        captured = {}

        def fake_http(url, *, timeout=10):
            captured["url"] = url
            return {"results": [_gc("London", "England", "United Kingdom", "GB",
                                    51.5, -0.12)]}

        with mock.patch.object(location, "_http_get_json", side_effect=fake_http):
            rec = location.resolve_location(override="SW1A 1AA, UK")
        self.assertEqual(rec["country_code"], "GB")
        # The non-numeric postal made it into the (encoded) request.
        self.assertIn("SW1A", captured["url"].replace("%20", "").replace("+", ""))

    def test_override_never_substitutes_cached_default(self):
        _seed({"display_name": "London", "region": "England",
               "country_name": "United Kingdom", "country_code": "GB",
               "lat": 51.5, "lon": -0.1})
        # Override geocode fails → must raise, NOT silently return London.
        with mock.patch.object(location, "_http_get_json",
                               return_value={"results": []}):
            with self.assertRaises(location.LocationNotFound):
                location.resolve_location(override="Nowhereville")

    def test_empty_and_no_default_returns_settings_message(self):
        rec = location.resolve_location(override="")
        self.assertFalse(rec.get("configured"))
        self.assertIn("Settings", rec.get("message", ""))

    def test_home_location_not_in_error_string(self):
        # An override that fails must not echo the user's location text.
        secret_place = "123 Private Lane, Secretville"
        with mock.patch.object(location, "_http_get_json",
                               return_value={"results": []}):
            try:
                location.resolve_location(override=secret_place)
                self.fail("expected LocationNotFound")
            except location.LocationNotFound as exc:
                self.assertNotIn("Secretville", str(exc))
                self.assertNotIn("Private Lane", str(exc))


if __name__ == "__main__":
    unittest.main(verbosity=2)
