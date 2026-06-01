# Weather app

A UI dashboard showing current conditions, a 12-hour hourly forecast, and a
10-day daily outlook for a US ZIP code (defaults to the configured home ZIP).

- The dashboard reads `GET /api/apps/weather/summary?zip=&hours=&days=` which
  returns `{ place, current, hourly[], daily[] }` (keyless open-meteo data).
- For chat answers about weather, use the platform weather tools
  (`get_current_weather_by_zip`, `get_hourly_forecast_by_zip`,
  `get_daily_forecast_by_zip`, `get_rain_chance_by_zip`) — same data source.
- The app stores nothing. A radar/alerts map view is a planned follow-up.
