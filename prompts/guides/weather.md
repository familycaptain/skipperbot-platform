# Weather Tools Guide

Weather is separate from generic web lookup. Prefer these tools over internet search when the user asks about current conditions, forecast, rain chance, precipitation, temperature, wind, or similar weather conditions.

**Default location:** all weather tools accept an optional `zip_code`. If the user doesn't name a location (e.g. just "what's the weather?"), call the tool with **no zip_code** — it falls back to the configured default ZIP (Settings → System → "Default ZIP code"). The user's home ZIP is also given to you in your dynamic context, so you can state it directly (e.g. "your ZIP is 72956") and pass it explicitly if you prefer. Only ask the user for a ZIP if the tool reports none is provided AND none is configured. This is how voice "what's the forecast?" requests resolve a location.

**Never guess a location.** Do not call `api.weather.gov`, `curl`, internet search, or made-up latitude/longitude for weather. Always use the `get_*_by_zip` tools above with the home/given ZIP. If you have no ZIP at all, ask for one — do not substitute a random city's coordinates.

## get_current_weather_by_zip

Current conditions only: temperature, feels-like, humidity, wind, and condition text.
Use this for "what's the weather right now", "how cold is it", "what is the temperature", or similar current-condition questions.

## get_hourly_forecast_by_zip

Hour-by-hour forecast for the next 1-48 hours. Returns temperature, feels-like (when notable), conditions, rain probability, wind, and humidity per hour.

- Use this for "12 hour forecast", "hourly forecast", "what will the weather be like later today", "weather over the next N hours", "forecast for tonight" (when the user wants conditions, not just rain chance).
- The `hours` argument is the lookahead window. Default is 12; clamp to 1-48.
- Prefer this tool over `get_rain_chance_by_zip` when the user wants more than just precipitation probability — e.g., they're asking about temperature, conditions, or wind across the day.
- Prefer this tool over `get_current_weather_by_zip` when the user wants to plan something later, not just check right-now conditions.

## get_rain_chance_by_zip

Rain and precipitation probability forecast by ZIP code.

- Use this for "chance of rain", "percent chance of rain", "will it rain", "rain overnight", "rain today", "rain tomorrow", "rain over the next week", or similar forecast questions.
- Interpret "chance of rain <period>" as the **highest hourly rain chance within that period**. Lead with the tool's "Highest chance" value. Mention the average only as extra context unless the user asks for average chance.
- The `period` argument accepts common phrases: `overnight`, `tonight`, `today`, `tomorrow`, `next 24 hours`, `next 3 days`, `next week`, `over the next week`.
- For "overnight", pass `period="overnight"`. The tool treats that as roughly evening through early morning local time.
- For "over the next week", pass `period="next week"` or `period="over the next week"`.
- If the user asks a rain-probability question and gives only a location you know as a ZIP from context, use that ZIP. If no ZIP/location is available, ask for it.

## Common Patterns

- "What's the chance of rain overnight?" -> `get_rain_chance_by_zip(zip_code="<known zip>", period="overnight")`
- "Will it rain today?" -> `get_rain_chance_by_zip(zip_code="<known zip>", period="today")`
- "What's the rain chance over the next week?" -> `get_rain_chance_by_zip(zip_code="<known zip>", period="next week")`
- "What's the weather right now?" -> `get_current_weather_by_zip(zip_code="<known zip>")`
- "What's the 12 hour forecast?" -> `get_hourly_forecast_by_zip(zip_code="<known zip>", hours=12)`
- "Hourly forecast for the rest of the day" -> `get_hourly_forecast_by_zip(zip_code="<known zip>", hours=12)`
