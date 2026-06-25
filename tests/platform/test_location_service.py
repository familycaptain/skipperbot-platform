"""Bound tests for spec platform.location.resolver — app_platform/location.py.

Fully offline: app_platform.settings is replaced with an in-memory fake, and
every outbound geocode call is mocked. No DB / network is touched.
"""

import json
import sys
import types
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse


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


def _params(url):
    """Outbound query params as a flat {key: first-value} dict."""
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


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


class TestRegionQualifiedOverride(unittest.TestCase):
    """ev-47: 'City, Region[, Country]' overrides resolve over a SINGLE Open-Meteo
    call, with region/country preference applied client-side; a trailing US-state
    token is never mis-bound to countryCode (the 'Austin, TX' bug)."""

    def setUp(self):
        _clear()

    def _stub(self, results):
        calls = {"n": 0, "url": None}

        def fake_http(url, *, timeout=10):
            calls["n"] += 1
            calls["url"] = url
            return {"results": results}

        return calls, fake_http

    # (1) 'Austin, Texas, US' — 3-piece, full region name.
    def test_city_region_country_full_name(self):
        calls, fake = self._stub([
            _gc("Austin", "Texas", "United States", "US", 30.27, -97.74),
            _gc("Austin", "Indiana", "United States", "US", 39.49, -85.80),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Austin, Texas, US")
        self.assertEqual(calls["n"], 1)
        p = _params(calls["url"])
        self.assertEqual(p["name"], "Austin")            # NOT 'Austin, Texas'
        self.assertEqual(p["countryCode"], "US")
        self.assertEqual(rec["region"], "Texas")

    # (2) 'Austin, TX, US' — abbrev region in the 3-piece form.
    def test_city_abbrev_region_country(self):
        calls, fake = self._stub([
            _gc("Austin", "Texas", "United States", "US", 30.27, -97.74),
            _gc("Austin", "Indiana", "United States", "US", 39.49, -85.80),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Austin, TX, US")
        self.assertEqual(calls["n"], 1)
        p = _params(calls["url"])
        self.assertEqual(p["name"], "Austin")
        self.assertEqual(p["countryCode"], "US")
        self.assertEqual(rec["region"], "Texas")         # TX expanded to Texas

    # (3) 'Austin, TX' — 2-piece, no country: TX must NOT become countryCode.
    def test_city_state_abbrev_two_piece_no_countrycode(self):
        calls, fake = self._stub([
            _gc("Austin", "Texas", "United States", "US", 30.27, -97.74),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Austin, TX")
        self.assertEqual(calls["n"], 1)
        p = _params(calls["url"])
        self.assertEqual(p["name"], "Austin")
        self.assertNotIn("countryCode", p)               # the 'Austin, TX' bug
        self.assertEqual(rec["region"], "Texas")

    # (4) 'Paris, TX, US' — region hint beats the otherwise top-ranked Paris, France.
    def test_paris_texas_us_region_beats_top(self):
        calls, fake = self._stub([
            _gc("Paris", "Île-de-France", "France", "FR", 48.85, 2.35),
            _gc("Paris", "Texas", "United States", "US", 33.66, -95.55),
            _gc("Paris", "Kentucky", "United States", "US", 38.21, -84.25),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Paris, TX, US")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(rec["region"], "Texas")
        self.assertEqual(rec["country_code"], "US")

    # (5) 'Paris, TX' — 2-piece: still Paris/Texas over the top-ranked Paris/France.
    def test_paris_tx_two_piece_no_countrycode(self):
        calls, fake = self._stub([
            _gc("Paris", "Île-de-France", "France", "FR", 48.85, 2.35),
            _gc("Paris", "Texas", "United States", "US", 33.66, -95.55),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Paris, TX")
        self.assertEqual(calls["n"], 1)
        p = _params(calls["url"])
        self.assertNotIn("countryCode", p)
        self.assertEqual(rec["region"], "Texas")
        self.assertEqual(rec["country_code"], "US")

    # (6) Tie-break on a token that is BOTH a US state AND an ISO country (CA).
    def test_tiebreak_region_present_wins_state(self):
        # 'San Diego, CA' with a California result present -> region (California).
        calls, fake = self._stub([
            _gc("San Diego", "California", "United States", "US", 32.72, -117.16),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="San Diego, CA")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(rec["region"], "California")
        self.assertEqual(rec["country_code"], "US")

    def test_tiebreak_region_absent_wins_country(self):
        # 'Toronto, CA' with NO admin1=='California' -> country (Canada) top.
        calls, fake = self._stub([
            _gc("Toronto", "Ontario", "Canada", "CA", 43.70, -79.42),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Toronto, CA")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(rec["country_code"], "CA")
        self.assertEqual(rec["region"], "Ontario")

    # (7) Region that excludes everything -> country-filtered top, never raises.
    def test_region_excludes_all_falls_back_no_raise(self):
        calls, fake = self._stub([
            _gc("Austin", "Texas", "United States", "US", 30.27, -97.74),
            _gc("Austin", "Indiana", "United States", "US", 39.49, -85.80),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.resolve_location(override="Austin, Nowhere, US")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(rec["country_code"], "US")      # a US result, no raise

    # (8) save_default_location shares _geocode -> Settings stores the Texas record.
    def test_save_default_location_region_qualified(self):
        calls, fake = self._stub([
            _gc("Austin", "Texas", "United States", "US", 30.27, -97.74),
            _gc("Austin", "Indiana", "United States", "US", 39.49, -85.80),
        ])
        with mock.patch.object(location, "_http_get_json", side_effect=fake):
            rec = location.save_default_location("Austin, Texas, US")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(rec["region"], "Texas")
        self.assertIn(("platform", "default_location"), _fake.store)
        stored = json.loads(_fake.store[("platform", "default_location")])
        self.assertEqual(stored["region"], "Texas")


class TestExistingFormsByteForByte(unittest.TestCase):
    """ev-47 invariant: the pre-existing override forms keep IDENTICAL outbound
    URL params (name + countryCode) and make exactly one call."""

    def setUp(self):
        _clear()

    def _run(self, override, results):
        calls = {"n": 0, "url": None}

        def fake_http(url, *, timeout=10):
            calls["n"] += 1
            calls["url"] = url
            return {"results": results}

        with mock.patch.object(location, "_http_get_json", side_effect=fake_http):
            rec = location.resolve_location(override=override)
        self.assertEqual(calls["n"], 1)
        return _params(calls["url"]), rec

    def test_bare_city(self):
        p, _ = self._run("London", [_gc("London", "England", "United Kingdom",
                                         "GB", 51.5, -0.12)])
        self.assertEqual(p["name"], "London")
        self.assertNotIn("countryCode", p)

    def test_city_country_code(self):
        p, _ = self._run("Chicago, US", [_gc("Chicago", "Illinois",
                                             "United States", "US", 41.85, -87.65)])
        self.assertEqual(p["name"], "Chicago")
        self.assertEqual(p["countryCode"], "US")

    def test_city_country_name(self):
        # 'France' is a NAME hint applied client-side — never sent as countryCode.
        p, rec = self._run("Lyon, France", [
            _gc("Lyon", "Texas", "United States", "US", 33.0, -94.0),
            _gc("Lyon", "Auvergne-Rhône-Alpes", "France", "FR", 45.76, 4.83),
        ])
        self.assertEqual(p["name"], "Lyon")
        self.assertNotIn("countryCode", p)
        self.assertEqual(rec["country_code"], "FR")

    def test_postal_country(self):
        p, rec = self._run("SW1A 1AA, UK", [_gc("London", "England",
                                               "United Kingdom", "GB", 51.5, -0.12)])
        self.assertEqual(p["name"], "SW1A 1AA")
        self.assertEqual(p["countryCode"], "GB")
        self.assertEqual(rec["country_code"], "GB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
