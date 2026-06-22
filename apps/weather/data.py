"""Weather app — structured forecast data for the dashboard UI.

Location is resolved by the platform service (``app_platform.location``); the
forecast comes from Open-Meteo by lat/lon. Returns structured JSON for the UI
instead of the formatted strings the MCP tools return. No data is stored.

NWS severe-weather alerts are US-only; for a non-US location the alerts call
returns an explicit message rather than a silent empty result.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime

from app_platform.location import (
    resolve_location,
    display_label,
    LocationNotFound,
    GeocoderUnavailable,
)

# WMO weather-code -> short description (mirrors apps/weather/tools.py).
_WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Heavy rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
}

_ALERTS_NON_US_MSG = (
    "Severe-weather alerts are US-only; current conditions and forecast still work."
)


def _desc(code) -> str:
    try:
        return _WMO.get(int(code), f"code {code}")
    except (TypeError, ValueError):
        return "unknown"


def _norm_cc(cc) -> str:
    """Normalize a country code to an ISO alpha-2 (uppercase), else ''.

    Anything that is not exactly two letters (empty / 3-letter / garbage)
    becomes '' — which the NWS gate treats as non-US, degrading safely rather
    than crashing or mis-gating.
    """
    s = str(cc or "").strip().upper()
    return s if (len(s) == 2 and s.isalpha()) else ""


def _valid_coords(lat, lon):
    """Return (lat, lon) as finite floats in range, or None.

    Both must be present and parse to finite floats with lat in [-90, 90] and
    lon in [-180, 180]; otherwise None so the caller degrades to the
    location-string resolve path (never fetch a garbage point).
    """
    if lat is None or lon is None:
        return None
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    import math
    if not (math.isfinite(la) and math.isfinite(lo)):
        return None
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        return None
    return la, lo


def _place_from_coords(lat: float, lon: float, label: str = "", cc: str = "") -> dict:
    """Build the place dict directly from known coordinates — NO geocoding.

    Used when refreshing a location the UI already resolved (it holds the
    coords), so the verbose display_label is never re-geocoded.
    """
    return {
        "display_label": (label or "").strip() or "Current location",
        "lat": lat,
        "lon": lon,
        "country_code": _norm_cc(cc),
    }


def _resolve(location: str = ""):
    """Resolve a place via the platform service.

    Returns (place_dict_or_None, error_message_or_None). ``place`` carries
    {display_label, lat, lon, country_code}.
    """
    override = (location or "").strip() or None
    try:
        record = resolve_location(override=override)
    except LocationNotFound:
        return None, "Couldn't find that location. Try a place name or postal,country."
    except GeocoderUnavailable:
        return None, "The location service is temporarily unavailable. Please try again."
    except Exception:
        return None, "Couldn't resolve that location."
    if not record.get("configured"):
        return None, record.get("message") or "No location configured (Settings → System → Location)."
    if record.get("lat") is None or record.get("lon") is None:
        return None, "Your home location couldn't be resolved to coordinates. Re-save it in Settings."
    return {
        "display_label": record.get("display_label") or display_label(record),
        "lat": record.get("lat"),
        "lon": record.get("lon"),
        "country_code": record.get("country_code") or "",
    }, None


def _fetch_json(url: str, timeout: int = 12) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SkipperBot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _val(arr, i):
    return arr[i] if isinstance(arr, list) and i < len(arr) else None


def weather_summary(location: str = "", hours: int = 12, days: int = 10,
                    lat=None, lon=None, label: str = "", cc: str = "") -> dict:
    """Return {place, current, hourly[], daily[]} for the dashboard, or {error}.

    When valid lat/lon are supplied (a refresh of a location the UI already
    resolved), fetch by those coordinates and SKIP geocoding entirely; otherwise
    resolve ``location`` via the platform service as before.
    """
    coords = _valid_coords(lat, lon)
    if coords:
        place, err = _place_from_coords(coords[0], coords[1], label, cc), None
    else:
        place, err = _resolve(location)
    if err:
        return {"error": err}

    try:
        hours = max(1, min(int(hours), 48))
    except (TypeError, ValueError):
        hours = 12
    try:
        days = max(1, min(int(days), 16))
    except (TypeError, ValueError):
        days = 10

    params = {
        "latitude": place["lat"],
        "longitude": place["lon"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,is_day",
        "hourly": "temperature_2m,weather_code,precipitation_probability,uv_index",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "auto",
        "forecast_days": days,
    }
    try:
        fc = _fetch_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params), timeout=15)
    except Exception as e:
        return {"error": f"Couldn't fetch the forecast: {e}"}

    cur = fc.get("current") or {}

    # Current UV: take the uv_index for the current hour from the hourly series.
    h = fc.get("hourly") or {}
    htimes = h.get("time") or []
    cur_uv = None
    cur_iso = cur.get("time")
    if cur_iso and cur_iso in htimes:
        cur_uv = _val(h.get("uv_index"), htimes.index(cur_iso))

    current = {
        "temp": cur.get("temperature_2m"),
        "feels": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "wind_dir": cur.get("wind_direction_10m"),
        "code": cur.get("weather_code"),
        "desc": _desc(cur.get("weather_code")),
        "uv": cur_uv,
        "is_day": bool(cur.get("is_day", 1)),
    }

    # Hourly — next `hours` entries from "now" forward.
    now_iso = cur.get("time") or ""
    start = 0
    for i, t in enumerate(htimes):
        if t >= now_iso:
            start = i
            break
    hourly = []
    for i in range(start, min(start + hours, len(htimes))):
        hourly.append({
            "time": htimes[i],
            "temp": _val(h.get("temperature_2m"), i),
            "code": _val(h.get("weather_code"), i),
            "desc": _desc(_val(h.get("weather_code"), i)),
            "pop": _val(h.get("precipitation_probability"), i),
            "uv": _val(h.get("uv_index"), i),
        })

    # Daily — up to `days`.
    d = fc.get("daily") or {}
    dtimes = d.get("time") or []
    daily = []
    for i in range(min(days, len(dtimes))):
        daily.append({
            "date": dtimes[i],
            "hi": _val(d.get("temperature_2m_max"), i),
            "lo": _val(d.get("temperature_2m_min"), i),
            "code": _val(d.get("weather_code"), i),
            "desc": _desc(_val(d.get("weather_code"), i)),
            "pop": _val(d.get("precipitation_probability_max"), i),
            "uv": _val(d.get("uv_index_max"), i),
            "sunrise": _val(d.get("sunrise"), i),
            "sunset": _val(d.get("sunset"), i),
        })

    return {
        "place": {"display_label": place["display_label"],
                  "lat": place["lat"], "lon": place["lon"],
                  "country_code": place["country_code"]},
        "current": current,
        "hourly": hourly,
        "daily": daily,
    }


def nws_alerts(location: str = "", lat=None, lon=None, cc: str = "") -> dict:
    """Active NWS severe-weather alerts near the location, as GeoJSON.

    NWS alerts are US-only: for a non-US location, return an explicit message
    (never a silent empty result). Fetched server-side because the NWS API
    expects a descriptive User-Agent (browsers can't set one). Returns a
    GeoJSON FeatureCollection trimmed to what the map needs.

    When valid lat/lon are supplied (a refresh from the Radar map, which already
    holds the coords), use them and SKIP geocoding; the US-only gate uses the
    normalized ``cc`` (empty/odd -> treated non-US, degrades safely).
    """
    empty = {"type": "FeatureCollection", "features": []}
    coords = _valid_coords(lat, lon)
    if coords:
        place, err = _place_from_coords(coords[0], coords[1], "", cc), None
    else:
        place, err = _resolve(location)
    if err:
        return {**empty, "message": err}

    if (place.get("country_code") or "").upper() != "US":
        return {**empty, "us_only": True, "message": _ALERTS_NON_US_MSG}

    try:
        url = f"https://api.weather.gov/alerts/active?point={place['lat']},{place['lon']}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "SkipperBot Weather app (self-hosted)",
            "Accept": "application/geo+json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return empty

    feats = []
    for f in data.get("features", []) or []:
        if not f.get("geometry"):
            continue  # zone-only alerts have no polygon to draw
        p = f.get("properties", {}) or {}
        feats.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "event": p.get("event"),
                "headline": p.get("headline"),
                "severity": p.get("severity"),
                "area": p.get("areaDesc"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}
