"""Tests for apps/weather/tools.py + apps/weather/data.py — international
location via the platform service, Open-Meteo data, identical canonical label.

Bound to spec weather.current-conditions.zip-city-authoritative.

Offline/deterministic: the platform location resolver and every outbound fetch
are mocked, so no network is touched.
"""
import sys
import types
import unittest
from unittest import mock

# Offline substrate: apps.weather.tools transitively imports app_platform.time
# -> app_platform.config -> data_layer.db, which requires psycopg2 + a live DB.
# Stub the timezone helper so the import chain stays pure-stdlib.
if "app_platform.time" not in sys.modules:
    _stub = types.ModuleType("app_platform.time")
    from zoneinfo import ZoneInfo as _ZoneInfo

    _stub.get_timezone = lambda user_id=None: _ZoneInfo("UTC")
    sys.modules["app_platform.time"] = _stub

# app_platform.location reads app_platform.settings lazily; stub settings so the
# real location module imports without a DB. (We mock resolve_location anyway.)
if "app_platform.settings" not in sys.modules:
    _s = types.ModuleType("app_platform.settings")
    _s.get = lambda *a, **k: k.get("default")
    _s.set = lambda *a, **k: None
    _s.is_configured = lambda *a, **k: False
    sys.modules["app_platform.settings"] = _s

from apps.weather import tools  # noqa: E402
from apps.weather import data  # noqa: E402


_LONDON = {
    "configured": True,
    "display_name": "London", "region": "England",
    "country_name": "United Kingdom", "country_code": "GB",
    "display_label": "London, England, United Kingdom",
    "lat": 51.5074, "lon": -0.1278,
}

_AUSTIN = {
    "configured": True,
    "display_name": "Austin", "region": "Texas",
    "country_name": "United States", "country_code": "US",
    "display_label": "Austin, Texas, United States",
    "lat": 30.26715, "lon": -97.74306,
}

_NO_LOCATION = {"configured": False, "message": "No location is configured. Set it in Settings."}

# Open-Meteo current-weather payload (NOT wttr.in / zippopotam).
_OPEN_METEO_CURRENT = {
    "current": {
        "temperature_2m": 55.0,
        "apparent_temperature": 54.0,
        "relative_humidity_2m": 60,
        "weather_code": 2,
        "wind_speed_10m": 7.0,
        "wind_direction_10m": 315,
    }
}


class TestCurrentConditionsLabel(unittest.TestCase):
    def test_home_location_label_and_open_meteo_source(self):
        with mock.patch.object(tools, "resolve_location", return_value=_LONDON) as rl, \
                mock.patch.object(tools, "_fetch_json", return_value=_OPEN_METEO_CURRENT):
            out = tools.get_current_weather_by_zip()  # no override → home location
        rl.assert_called_once_with(override=None)
        self.assertIn("London, England, United Kingdom", out)
        # Open-Meteo WMO code 2 → "Partly cloudy"; not wttr/zippopotam.
        self.assertIn("Partly cloudy", out)
        self.assertIn("55", out)
        self.assertNotIn("Rena", out)

    def test_override_flows_through_to_resolve_location(self):
        lyon = dict(_LONDON, display_name="Lyon", region="Auvergne-Rhône-Alpes",
                    country_name="France", country_code="FR",
                    display_label="Lyon, Auvergne-Rhône-Alpes, France",
                    lat=45.76, lon=4.83)
        with mock.patch.object(tools, "resolve_location", return_value=lyon) as rl, \
                mock.patch.object(tools, "_fetch_json", return_value=_OPEN_METEO_CURRENT):
            out = tools.get_current_weather_by_zip(location="Lyon, France")
        rl.assert_called_once_with(override="Lyon, France")
        self.assertIn("Lyon, Auvergne-Rhône-Alpes, France", out)

    def test_no_location_returns_settings_message(self):
        with mock.patch.object(tools, "resolve_location", return_value=_NO_LOCATION):
            out = tools.get_current_weather_by_zip()
        self.assertIn("Settings", out)

    def test_current_and_forecast_agree_on_label(self):
        forecast_payload = {
            "timezone": "Europe/London",
            "daily": {"time": [], "weathercode": [], "temperature_2m_max": [],
                      "temperature_2m_min": []},
        }
        with mock.patch.object(tools, "resolve_location", return_value=_LONDON), \
                mock.patch.object(tools, "_fetch_json", return_value=_OPEN_METEO_CURRENT):
            cur = tools.get_current_weather_by_zip()
        with mock.patch.object(tools, "resolve_location", return_value=_LONDON), \
                mock.patch.object(tools, "_fetch_json", return_value=forecast_payload):
            daily = tools.get_daily_forecast_by_zip()
        label = "London, England, United Kingdom"
        self.assertIn(label, cur)
        self.assertIn(label, daily)


class TestNwsAlertsUsOnly(unittest.TestCase):
    def test_non_us_returns_explicit_us_only_message(self):
        with mock.patch.object(data, "resolve_location", return_value=_LONDON), \
                mock.patch.object(data, "_fetch_json",
                                  side_effect=AssertionError("must not fetch NWS for non-US")):
            out = data.nws_alerts()
        self.assertTrue(out.get("us_only"))
        self.assertIn("Severe-weather alerts are US-only", out.get("message", ""))
        self.assertEqual(out.get("features"), [])

    def test_us_location_fetches_alerts_normally(self):
        nws_payload = {"features": [
            {"geometry": {"type": "Polygon", "coordinates": []},
             "properties": {"event": "Tornado Warning", "headline": "h",
                            "severity": "Severe", "areaDesc": "Travis"}},
        ]}
        with mock.patch.object(data, "resolve_location", return_value=_AUSTIN), \
                mock.patch("urllib.request.urlopen") as urlopen:
            cm = mock.MagicMock()
            cm.read.return_value = __import__("json").dumps(nws_payload).encode()
            urlopen.return_value.__enter__.return_value = cm
            out = data.nws_alerts()
        events = [f["properties"]["event"] for f in out.get("features", [])]
        self.assertIn("Tornado Warning", events)


if __name__ == "__main__":
    unittest.main(verbosity=2)
