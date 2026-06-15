"""Tests for apps/weather/tools.py — current-weather city label authority.

Bound to spec weather.current-conditions.zip-city-authoritative.

Offline/deterministic: both outbound fetches in apps/weather/tools.py are
mocked, so no network is touched.
"""
import sys
import types
import unittest
from unittest import mock

# Offline substrate: apps.weather.tools transitively imports app_platform.time
# -> app_platform.config -> data_layer.db, which requires psycopg2 + a live DB.
# Stub the timezone helper so the import chain stays pure-stdlib and no network
# or database is touched. _local_now (the only get_timezone consumer) is not on
# the get_current_weather_by_zip code path under test.
if "app_platform.time" not in sys.modules:
    _stub = types.ModuleType("app_platform.time")
    from zoneinfo import ZoneInfo as _ZoneInfo

    _stub.get_timezone = lambda user_id=None: _ZoneInfo("UTC")
    sys.modules["app_platform.time"] = _stub

from apps.weather import tools


# A valid wttr.in current_condition payload whose nearest_area names "Rena"
# (the wrong city wttr.in returns for ZIP 72956).
_WTTR_RENA = {
    "current_condition": [
        {
            "temp_F": "55",
            "temp_C": "13",
            "weatherDesc": [{"value": "Partly cloudy"}],
            "humidity": "60",
            "windspeedMiles": "7",
            "winddir16Point": "NW",
            "FeelsLikeF": "54",
        }
    ],
    "nearest_area": [
        {
            "areaName": [{"value": "Rena"}],
            "region": [{"value": "AR"}],
        }
    ],
}


class TestZipCityAuthoritative(unittest.TestCase):
    def test_uses_authoritative_zip_city_not_wttr_nearest_area(self):
        """ZIP 72956 should label as Van Buren, AR (zippopotam) not Rena (wttr.in)."""
        with mock.patch.object(
            tools, "_lookup_zip",
            return_value={"city": "Van Buren", "region": "AR",
                          "lat": 35.43, "lon": -94.35},
        ), mock.patch.object(tools, "_fetch_json", return_value=_WTTR_RENA):
            out = tools.get_current_weather_by_zip("72956")

        self.assertIn("Van Buren, AR", out)
        self.assertNotIn("Rena", out)
        # weather data still comes from wttr.in
        self.assertIn("Partly cloudy", out)
        self.assertIn("55", out)

    def test_falls_back_to_wttr_area_when_lookup_fails(self):
        """If _lookup_zip raises, degrade gracefully to wttr.in's area label and
        still return the weather (never 'Error fetching weather')."""
        with mock.patch.object(
            tools, "_lookup_zip", side_effect=RuntimeError("offline"),
        ), mock.patch.object(tools, "_fetch_json", return_value=_WTTR_RENA):
            out = tools.get_current_weather_by_zip("72956")

        self.assertIn("Rena, AR", out)
        self.assertIn("Partly cloudy", out)
        self.assertIn("55", out)
        self.assertNotIn("Error fetching weather", out)

    def test_city_region_matches_lookup_zip_consistency(self):
        """Current-weather and forecast tools must agree on the place name:
        the label in the output equals _lookup_zip's city/region for that ZIP."""
        place = {"city": "Van Buren", "region": "AR", "lat": 35.43, "lon": -94.35}
        with mock.patch.object(tools, "_lookup_zip", return_value=place), \
                mock.patch.object(tools, "_fetch_json", return_value=_WTTR_RENA):
            out = tools.get_current_weather_by_zip("72956")

        self.assertIn(f"{place['city']}, {place['region']}", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
