"""
Zip Weather Tool - Get weather for US zip codes using no-key public APIs.
"""

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from app_platform.time import get_timezone


def _clean_zip(zip_code) -> str:
    # str() — a configured default ZIP can come back as an int (e.g. 72956);
    # calling .strip() on an int would raise.
    return str(zip_code or "").strip().split("-")[0]


def _validate_zip(zip_code: str) -> str | None:
    if not zip_code.isdigit() or len(zip_code) != 5:
        return f"Error: '{zip_code}' is not a valid 5-digit US zip code."
    return None


def _default_zip() -> str:
    """The configured default ZIP (Settings → System → Default ZIP code), or ''."""
    try:
        from app_platform import settings as _settings
        return _clean_zip(_settings.get("default_zip", scope="platform", default="") or "")
    except Exception:
        return ""


def _resolve_zip(zip_code: str) -> str:
    """Use the given ZIP, or fall back to the configured default. Callers that
    get '' should return _NO_ZIP_MSG (no ZIP given and none configured)."""
    return _clean_zip(zip_code) or _default_zip()


_NO_ZIP_MSG = (
    "No ZIP code was provided and no default is configured. Set one in "
    "Settings → System → \"Default ZIP code\", or include a 5-digit US ZIP."
)


def _fetch_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SkipperBot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _lookup_zip(zip_code: str) -> dict:
    url = f"https://api.zippopotam.us/us/{zip_code}"
    data = _fetch_json(url)
    place = data["places"][0]
    return {
        "city": place["place name"],
        "region": place["state abbreviation"],
        "lat": float(place["latitude"]),
        "lon": float(place["longitude"]),
    }


def get_current_weather_by_zip(zip_code: str = "") -> str:
    """
    Get the current weather for a US zip code.

    Args:
        zip_code: US ZIP code (e.g., "90210", "60601"). Optional — if omitted,
            uses the configured default ZIP (Settings → System → Default ZIP code).

    Returns:
        Current weather conditions as a formatted string
    """
    zip_code = _resolve_zip(zip_code)
    if not zip_code:
        return _NO_ZIP_MSG

    error = _validate_zip(zip_code)
    if error:
        return error
    
    try:
        url = f"https://wttr.in/{zip_code}?format=j1"
        data = _fetch_json(url)
        
        current = data["current_condition"][0]
        area = data["nearest_area"][0]
        
        city = area["areaName"][0]["value"]
        region = area["region"][0]["value"]
        temp_f = current["temp_F"]
        temp_c = current["temp_C"]
        desc = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind_mph = current["windspeedMiles"]
        wind_dir = current["winddir16Point"]
        feels_like_f = current["FeelsLikeF"]
        
        return (
            f"Weather for {city}, {region} ({zip_code}):\n"
            f"  Conditions: {desc}\n"
            f"  Temperature: {temp_f}°F ({temp_c}°C)\n"
            f"  Feels like: {feels_like_f}°F\n"
            f"  Humidity: {humidity}%\n"
            f"  Wind: {wind_mph} mph {wind_dir}"
        )
    except Exception as e:
        return f"Error fetching weather: {str(e)}"


def _forecast_for_zip(zip_code: str) -> tuple[dict, dict]:
    place = _lookup_zip(zip_code)
    params = {
        "latitude": place["lat"],
        "longitude": place["lon"],
        "hourly": "precipitation_probability,precipitation,rain,showers",
        "daily": "precipitation_probability_max,precipitation_sum,rain_sum,showers_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "auto",
        "forecast_days": 8,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    return place, _fetch_json(url, timeout=15)


def _hourly_forecast_for_zip(zip_code: str) -> tuple[dict, dict]:
    """Fetch a richer hourly forecast for the next ~48 hours."""
    place = _lookup_zip(zip_code)
    params = {
        "latitude": place["lat"],
        "longitude": place["lon"],
        "hourly": (
            "temperature_2m,apparent_temperature,weathercode,"
            "precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,"
            "relative_humidity_2m"
        ),
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "forecast_days": 3,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    return place, _fetch_json(url, timeout=15)


def _daily_forecast_for_zip(zip_code: str, days: int) -> tuple[dict, dict]:
    """Fetch a multi-day daily forecast (highs/lows, precip, conditions, wind)."""
    place = _lookup_zip(zip_code)
    params = {
        "latitude": place["lat"],
        "longitude": place["lon"],
        "daily": (
            "weathercode,temperature_2m_max,temperature_2m_min,"
            "apparent_temperature_max,precipitation_sum,precipitation_probability_max,"
            "wind_speed_10m_max,wind_direction_10m_dominant"
        ),
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "forecast_days": days,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    return place, _fetch_json(url, timeout=15)


# Open-Meteo / WMO weather codes. Trimmed to the buckets that matter for
# a short text summary; everything else falls back to "code N".
_WMO_DESC = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers", 81: "Heavy rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
}


def _wmo_desc(code) -> str:
    try:
        return _WMO_DESC.get(int(code), f"code {code}")
    except (TypeError, ValueError):
        return "unknown"


def _wind_compass(deg) -> str:
    try:
        d = float(deg)
    except (TypeError, ValueError):
        return ""
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return points[int((d + 11.25) // 22.5) % 16]


def _local_now(forecast: dict) -> datetime:
    tz_name = forecast.get("timezone") or "UTC"
    try:
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return datetime.now(get_timezone()).replace(tzinfo=None)


def _period_window(period: str, now: datetime) -> tuple[datetime, datetime, str]:
    p = (period or "today").strip().lower()
    today = now.date()

    days_match = re.search(r"(?:next|over\s+the\s+next)\s+(\d+)\s+days?", p)
    if days_match:
        days = max(1, min(int(days_match.group(1)), 8))
        return now, now + timedelta(days=days), f"the next {days} day(s)"

    hours_match = re.search(r"(?:next|over\s+the\s+next)\s+(\d+)\s+hours?", p)
    if hours_match:
        hours = max(1, min(int(hours_match.group(1)), 192))
        return now, now + timedelta(hours=hours), f"the next {hours} hour(s)"

    if any(word in p for word in ("overnight", "tonight", "over night")):
        start = datetime.combine(today, time(18, 0))
        if now > start:
            start = now
        end = datetime.combine(today + timedelta(days=1), time(7, 0))
        return start, end, "overnight"

    if "tomorrow" in p:
        day = today + timedelta(days=1)
        return datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min), "tomorrow"

    if "week" in p or "7 day" in p or "seven day" in p:
        return now, now + timedelta(days=7), "the next week"

    if "today" in p or "day" in p:
        end = datetime.combine(today + timedelta(days=1), time.min)
        return now, end, "today"

    return now, datetime.combine(today + timedelta(days=1), time.min), "today"


def _hourly_rows(forecast: dict) -> list[dict]:
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    precip = hourly.get("precipitation") or []
    rain = hourly.get("rain") or []
    showers = hourly.get("showers") or []

    rows = []
    for idx, value in enumerate(times):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            continue
        rows.append({
            "time": dt,
            "probability": int(probs[idx]) if idx < len(probs) and probs[idx] is not None else 0,
            "precipitation": float(precip[idx]) if idx < len(precip) and precip[idx] is not None else 0.0,
            "rain": float(rain[idx]) if idx < len(rain) and rain[idx] is not None else 0.0,
            "showers": float(showers[idx]) if idx < len(showers) and showers[idx] is not None else 0.0,
        })
    return rows


def _daily_rows(forecast: dict, start: datetime, end: datetime) -> list[dict]:
    daily = forecast.get("daily") or {}
    times = daily.get("time") or []
    probs = daily.get("precipitation_probability_max") or []
    precip = daily.get("precipitation_sum") or []
    rows = []
    for idx, value in enumerate(times):
        try:
            day = date.fromisoformat(value)
        except ValueError:
            continue
        if start.date() <= day <= (end - timedelta(seconds=1)).date():
            rows.append({
                "date": day,
                "probability": int(probs[idx]) if idx < len(probs) and probs[idx] is not None else 0,
                "precipitation": float(precip[idx]) if idx < len(precip) and precip[idx] is not None else 0.0,
            })
    return rows


def _fmt_time(dt: datetime) -> str:
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%a')} {hour} {dt.strftime('%p')}"


def _fmt_date(day: date) -> str:
    return f"{day.strftime('%a %b')} {day.day}"


def get_rain_chance_by_zip(zip_code: str = "", period: str = "today") -> str:
    """Get the chance of rain for a US ZIP code over a natural-language period.

    Use this for questions about rain probability or precipitation chance,
    especially phrases like "chance of rain overnight", "will it rain today",
    "rain chance tomorrow", "over the next 24 hours", or "over the next week".
    For a period-based question, answer primarily with the highest hourly
    rain chance found inside that period. The average chance is supporting
    context, not the headline answer, unless the user explicitly asks for it.

    Args:
        zip_code: US ZIP code (e.g., "90210", "60601"). Optional — if omitted,
            uses the configured default ZIP (Settings → System → Default ZIP code).
        period: Natural-language period. Supported examples: "overnight",
            "tonight", "today", "tomorrow", "next 24 hours", "next 3 days",
            "next week", or "over the next week".

    Returns:
        Formatted rain probability summary using Open-Meteo hourly/daily forecast data.

    Ack: Checking rain chances...
    """
    zip_code = _resolve_zip(zip_code)
    if not zip_code:
        return _NO_ZIP_MSG
    error = _validate_zip(zip_code)
    if error:
        return error

    try:
        place, forecast = _forecast_for_zip(zip_code)
        now = _local_now(forecast)
        start, end, label = _period_window(period, now)
        hours = [row for row in _hourly_rows(forecast) if start <= row["time"] < end]
        if not hours:
            return f"No hourly rain forecast was available for {label}."

        max_hour = max(hours, key=lambda row: row["probability"])
        avg_probability = round(mean(row["probability"] for row in hours))
        total_precip = sum(row["precipitation"] for row in hours)
        rainy_hours = sum(1 for row in hours if row["probability"] >= 30 or row["precipitation"] > 0)

        lines = [
            f"Rain chance for {place['city']}, {place['region']} ({zip_code}) — {label}:",
            f"  Highest chance: {max_hour['probability']}% around {_fmt_time(max_hour['time'])}",
            f"  Average chance: {avg_probability}%",
            f"  Forecast precipitation: {total_precip:.2f} in",
            f"  Rain-risk hours: {rainy_hours} of {len(hours)}",
        ]

        if (end - start) >= timedelta(days=2):
            days = _daily_rows(forecast, start, end)
            if days:
                lines.append("  Daily max chances:")
                for day in days[:8]:
                    lines.append(
                        f"    {_fmt_date(day['date'])}: {day['probability']}%"
                        f" ({day['precipitation']:.2f} in)"
                    )

        lines.append("  Source: Open-Meteo forecast via ZIP lookup.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching rain forecast: {str(e)}"


def get_hourly_forecast_by_zip(zip_code: str = "", hours: int = 12) -> str:
    """Get an hour-by-hour weather forecast for a US ZIP code.

    Returns temperature, conditions, precipitation chance, and wind for each
    of the next N hours (default 12, max 48). Use this for questions like
    "what's the weather for the next 12 hours", "hourly forecast", or
    "what will it be like later today".

    Args:
        zip_code: US ZIP code (e.g., "90210", "72956"). Optional — if omitted,
            uses the configured default ZIP (Settings → System → Default ZIP code).
        hours: How many hours ahead to report (1-48). Defaults to 12.

    Returns:
        Formatted hourly forecast pulled from Open-Meteo via ZIP lookup.

    Ack: Pulling the hourly forecast...
    """
    zip_code = _resolve_zip(zip_code)
    if not zip_code:
        return _NO_ZIP_MSG
    error = _validate_zip(zip_code)
    if error:
        return error

    try:
        n = max(1, min(int(hours or 12), 48))
    except (TypeError, ValueError):
        n = 12

    try:
        place, forecast = _hourly_forecast_for_zip(zip_code)
        hourly = forecast.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return f"No hourly forecast was available for {zip_code}."

        temps = hourly.get("temperature_2m") or []
        feels = hourly.get("apparent_temperature") or []
        codes = hourly.get("weathercode") or []
        probs = hourly.get("precipitation_probability") or []
        precip = hourly.get("precipitation") or []
        wind = hourly.get("wind_speed_10m") or []
        wind_dir = hourly.get("wind_direction_10m") or []
        humidity = hourly.get("relative_humidity_2m") or []

        # Drop hours already in the past (Open-Meteo returns the full day).
        now = _local_now(forecast)
        rows: list[dict] = []
        for i, ts in enumerate(times):
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if dt < now.replace(minute=0, second=0, microsecond=0):
                continue
            rows.append({
                "time": dt,
                "temp": temps[i] if i < len(temps) else None,
                "feels": feels[i] if i < len(feels) else None,
                "code": codes[i] if i < len(codes) else None,
                "prob": probs[i] if i < len(probs) else None,
                "precip": precip[i] if i < len(precip) else None,
                "wind": wind[i] if i < len(wind) else None,
                "wind_dir": wind_dir[i] if i < len(wind_dir) else None,
                "humidity": humidity[i] if i < len(humidity) else None,
            })
            if len(rows) >= n:
                break

        if not rows:
            return f"No upcoming hourly forecast hours were available for {zip_code}."

        lines = [
            f"Hourly forecast for {place['city']}, {place['region']} "
            f"({zip_code}) — next {len(rows)} hour(s):"
        ]
        for r in rows:
            temp_str = f"{round(r['temp'])}°F" if r["temp"] is not None else "?"
            feels_str = (
                f" (feels {round(r['feels'])}°F)"
                if r["feels"] is not None and r["temp"] is not None
                and abs(r["feels"] - r["temp"]) >= 3
                else ""
            )
            cond = _wmo_desc(r["code"])
            prob_str = f"{int(r['prob'])}% rain" if r["prob"] is not None else ""
            precip_str = (
                f" ({r['precip']:.2f} in)"
                if r["precip"] is not None and r["precip"] > 0 else ""
            )
            wind_str = ""
            if r["wind"] is not None:
                compass = _wind_compass(r["wind_dir"])
                wind_str = f" wind {round(r['wind'])} mph"
                if compass:
                    wind_str += f" {compass}"
            humidity_str = (
                f" RH {int(r['humidity'])}%" if r["humidity"] is not None else ""
            )

            parts = [temp_str + feels_str, cond]
            if prob_str:
                parts.append(prob_str + precip_str)
            if wind_str:
                parts.append(wind_str.strip())
            if humidity_str:
                parts.append(humidity_str.strip())

            lines.append(f"  {_fmt_time(r['time'])}: " + " | ".join(parts))

        lines.append("  Source: Open-Meteo hourly forecast via ZIP lookup.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching hourly forecast: {str(e)}"


def get_daily_forecast_by_zip(zip_code: str = "", days: int = 7) -> str:
    """Get a multi-day daily forecast (high/low per day) for a US ZIP code.

    Returns one line per day with the high/low temperature, conditions, rain
    chance, precipitation total, and peak wind. Use this for questions like
    "daily forecast", "10-day forecast", "what's the weather this week",
    "highs and lows", "extended forecast", or "forecast for the next few days".

    Args:
        zip_code: US ZIP code (e.g., "90210", "72956"). Optional — if omitted,
            uses the configured default ZIP (Settings → System → Default ZIP code).
        days: How many days ahead to report (1-16). Defaults to 7.

    Returns:
        Formatted day-by-day forecast pulled from Open-Meteo via ZIP lookup.

    Ack: Pulling the daily forecast...
    """
    zip_code = _resolve_zip(zip_code)
    if not zip_code:
        return _NO_ZIP_MSG
    error = _validate_zip(zip_code)
    if error:
        return error

    try:
        n = max(1, min(int(days or 7), 16))
    except (TypeError, ValueError):
        n = 7

    try:
        place, forecast = _daily_forecast_for_zip(zip_code, n)
        daily = forecast.get("daily") or {}
        times = daily.get("time") or []
        if not times:
            return f"No daily forecast was available for {zip_code}."

        codes = daily.get("weathercode") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        precip = daily.get("precipitation_sum") or []
        probs = daily.get("precipitation_probability_max") or []
        wind = daily.get("wind_speed_10m_max") or []
        wind_dir = daily.get("wind_direction_10m_dominant") or []

        lines = [
            f"Daily forecast for {place['city']}, {place['region']} "
            f"({zip_code}) — next {min(n, len(times))} day(s):"
        ]
        for i, ts in enumerate(times[:n]):
            try:
                day = date.fromisoformat(ts)
            except ValueError:
                continue
            hi = f"{round(tmax[i])}°F" if i < len(tmax) and tmax[i] is not None else "?"
            lo = f"{round(tmin[i])}°F" if i < len(tmin) and tmin[i] is not None else "?"
            cond = _wmo_desc(codes[i]) if i < len(codes) else "unknown"
            prob = probs[i] if i < len(probs) and probs[i] is not None else None
            prob_str = f"{int(prob)}% rain" if prob is not None else ""
            pr = precip[i] if i < len(precip) and precip[i] is not None else None
            precip_str = f" ({pr:.2f} in)" if pr is not None and pr > 0 else ""
            wind_str = ""
            if i < len(wind) and wind[i] is not None:
                compass = _wind_compass(wind_dir[i] if i < len(wind_dir) else None)
                wind_str = f"wind {round(wind[i])} mph" + (f" {compass}" if compass else "")

            parts = [f"H {hi} / L {lo}", cond]
            if prob_str:
                parts.append(prob_str + precip_str)
            if wind_str:
                parts.append(wind_str)
            lines.append(f"  {_fmt_date(day)}: " + " | ".join(parts))

        lines.append("  Source: Open-Meteo daily forecast via ZIP lookup.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching daily forecast: {str(e)}"
