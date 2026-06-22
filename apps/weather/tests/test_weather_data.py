"""Bound tests for spec weather.current-conditions.refresh-by-coords.

Issue #42: refreshing the location already on screen must refetch by its STORED
lat/lon and SKIP geocoding, so the verbose display_label is never re-geocoded
(the bug). Search (a changed location string) still geocodes. Covers the /summary
and /alerts coords paths, validation/degrade, cc normalization, and the access-log
redaction of home coordinates.

Offline/deterministic: the platform resolver and every outbound fetch are mocked.
"""
import json
import sys
import types
import unittest
from unittest import mock

# Same offline substrate as test_weather_tools.py: stub app_platform.time and
# app_platform.settings so importing apps.weather.data needs no DB.
if "app_platform.time" not in sys.modules:
    _t = types.ModuleType("app_platform.time")
    from zoneinfo import ZoneInfo as _ZoneInfo
    _t.get_timezone = lambda user_id=None: _ZoneInfo("UTC")
    sys.modules["app_platform.time"] = _t
if "app_platform.settings" not in sys.modules:
    _s = types.ModuleType("app_platform.settings")
    _s.get = lambda *a, **k: k.get("default")
    _s.set = lambda *a, **k: None
    _s.is_configured = lambda *a, **k: False
    sys.modules["app_platform.settings"] = _s

from apps.weather import data  # noqa: E402
from app_platform import log_redaction  # noqa: E402

_AUSTIN = {
    "configured": True,
    "display_name": "Austin", "region": "Texas",
    "country_name": "United States", "country_code": "US",
    "display_label": "Austin, Texas, United States",
    "lat": 30.26715, "lon": -97.74306,
}
_FORECAST = {"current": {"time": "2026-06-22T12:00", "temperature_2m": 92.0,
                         "weather_code": 0}, "hourly": {"time": []}, "daily": {"time": []}}


class TestSummaryCoordsPath(unittest.TestCase):
    def test_coords_skip_geocode(self):
        with mock.patch.object(data, "resolve_location") as rl, \
                mock.patch.object(data, "_fetch_json", return_value=_FORECAST):
            out = data.weather_summary(lat=30.26715, lon=-97.74306,
                                       label="Austin, Texas, United States", cc="US")
        self.assertNotIn("error", out)
        self.assertEqual(out["place"]["display_label"], "Austin, Texas, United States")
        self.assertEqual(out["place"]["lat"], 30.26715)
        self.assertEqual(out["place"]["lon"], -97.74306)
        self.assertEqual(out["place"]["country_code"], "US")
        rl.assert_not_called()  # the whole point: ZERO geocoding on a coord refresh

    def test_string_path_still_resolves(self):
        with mock.patch.object(data, "resolve_location", return_value=_AUSTIN) as rl, \
                mock.patch.object(data, "_fetch_json", return_value=_FORECAST):
            out = data.weather_summary(location="Austin, Texas, US")
        self.assertNotIn("error", out)
        rl.assert_called_once()

    def test_invalid_or_partial_coords_degrade_to_string(self):
        for lat, lon in [(30.27, None), (None, -97.7), ("nan", -97.7),
                         (float("inf"), -97.7), (999.0, -97.7), (30.27, 999.0)]:
            with mock.patch.object(data, "resolve_location", return_value=_AUSTIN) as rl, \
                    mock.patch.object(data, "_fetch_json", return_value=_FORECAST):
                data.weather_summary(location="Austin, Texas, US", lat=lat, lon=lon)
            rl.assert_called_once()  # degraded to the resolve path, no garbage point


class TestAlertsCoordsPath(unittest.TestCase):
    def _fake_urlopen(self, payload):
        cm = mock.MagicMock()
        cm.read.return_value = json.dumps(payload).encode()
        m = mock.MagicMock()
        m.return_value.__enter__.return_value = cm
        return m

    def test_us_coords_fetch_no_geocode(self):
        fake = self._fake_urlopen({"features": []})
        with mock.patch.object(data, "resolve_location") as rl, \
                mock.patch("urllib.request.urlopen", fake):
            out = data.nws_alerts(lat=30.26715, lon=-97.74306, cc="US")
        self.assertEqual(out.get("type"), "FeatureCollection")
        rl.assert_not_called()
        fake.assert_called()  # NWS fetched by point, not geocoded

    def test_non_us_coords_returns_us_only_message_no_crash(self):
        for cc in ("GB", "", "usa", "xx1"):
            with mock.patch.object(data, "resolve_location") as rl:
                out = data.nws_alerts(lat=51.5074, lon=-0.1278, cc=cc)
            self.assertTrue(out.get("us_only"))
            self.assertIn("US-only", out.get("message", ""))
            rl.assert_not_called()

    def test_string_path_still_resolves(self):
        with mock.patch.object(data, "resolve_location", return_value=_AUSTIN) as rl, \
                mock.patch("urllib.request.urlopen", self._fake_urlopen({"features": []})):
            data.nws_alerts(location="Austin, Texas, US")
        rl.assert_called_once()


class TestCcNormalization(unittest.TestCase):
    def test_norm_cc(self):
        self.assertEqual(data._norm_cc("us"), "US")
        self.assertEqual(data._norm_cc("US"), "US")
        self.assertEqual(data._norm_cc("usa"), "")
        self.assertEqual(data._norm_cc(""), "")
        self.assertEqual(data._norm_cc(None), "")
        self.assertEqual(data._norm_cc("1A"), "")


class TestAccessLogRedaction(unittest.TestCase):
    def test_lat_lon_location_masked(self):
        line = ('GET /api/apps/weather/summary?location=Austin%2C+Texas'
                '&lat=30.26715&lon=-97.74306&hours=12 HTTP/1.1')
        red = log_redaction.redact_access_log_line(line)
        self.assertNotIn("30.26715", red)
        self.assertNotIn("-97.74306", red)
        self.assertNotIn("Austin", red)
        self.assertIn("lat=***", red)
        self.assertIn("lon=***", red)
        self.assertIn("location=***", red)

    def test_does_not_clobber_unrelated_words(self):
        # a param merely ENDING in 'lat'/'lon' must not be masked
        line = "GET /x?flatten=yes&salon=z HTTP/1.1"
        red = log_redaction.redact_access_log_line(line)
        self.assertIn("flatten=yes", red)
        self.assertIn("salon=z", red)


if __name__ == "__main__":
    unittest.main()
