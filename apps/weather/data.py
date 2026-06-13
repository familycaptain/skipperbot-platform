"""Weather app — structured forecast data for the dashboard UI.

Wraps the same keyless public APIs the chat weather tools use (zippopotam for
ZIP -> lat/lon, open-meteo for forecast), but returns structured JSON for the
UI instead of the formatted strings the MCP tools return. No data is stored.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime

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


def _desc(code) -> str:
    try:
        return _WMO.get(int(code), f"code {code}")
    except (TypeError, ValueError):
        return "unknown"


def _clean_zip(zip_code) -> str:
    return str(zip_code or "").strip().split("-")[0]


def _default_zip() -> str:
    """The configured default ZIP (Settings -> System -> Default ZIP code), or ''."""
    try:
        from app_platform import settings as _settings
        return _clean_zip(_settings.get("default_zip", scope="platform", default="") or "")
    except Exception:
        return ""


def _fetch_json(url: str, timeout: int = 12) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SkipperBot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _lookup_zip(zip_code: str) -> dict:
    data = _fetch_json(f"https://api.zippopotam.us/us/{zip_code}")
    place = data["places"][0]
    return {
        "city": place["place name"],
        "region": place["state abbreviation"],
        "lat": float(place["latitude"]),
        "lon": float(place["longitude"]),
    }


def _val(arr, i):
    return arr[i] if isinstance(arr, list) and i < len(arr) else None


def weather_summary(zip_code: str = "", hours: int = 12, days: int = 10) -> dict:
    """Return {place, current, hourly[], daily[]} for the dashboard, or {error}."""
    zc = _clean_zip(zip_code) or _default_zip()
    if not zc:
        return {"error": "No ZIP provided and no default configured (Settings -> System -> Default ZIP code)."}
    if not zc.isdigit() or len(zc) != 5:
        return {"error": f"'{zc}' is not a valid 5-digit US ZIP code."}

    try:
        hours = max(1, min(int(hours), 48))
    except (TypeError, ValueError):
        hours = 12
    try:
        days = max(1, min(int(days), 16))
    except (TypeError, ValueError):
        days = 10

    try:
        place = _lookup_zip(zc)
    except Exception as e:
        return {"error": f"Couldn't look up ZIP {zc}: {e}"}

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
        "place": {"city": place["city"], "region": place["region"], "zip": zc,
                  "lat": place["lat"], "lon": place["lon"]},
        "current": current,
        "hourly": hourly,
        "daily": daily,
    }


def nws_alerts(zip_code: str = "") -> dict:
    """Active NWS severe-weather alerts near the ZIP, as GeoJSON.

    Fetched server-side because the NWS API expects a descriptive User-Agent
    (browsers can't set one). Returns a GeoJSON FeatureCollection trimmed to
    what the map needs; empty features on any error (alerts are best-effort).
    """
    zc = _clean_zip(zip_code) or _default_zip()
    empty = {"type": "FeatureCollection", "features": []}
    if not zc or not zc.isdigit() or len(zc) != 5:
        return empty
    try:
        place = _lookup_zip(zc)
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
