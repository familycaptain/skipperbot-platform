# Weather app

A UI dashboard showing current conditions, a 12-hour hourly forecast, and a
10-day daily outlook for a US ZIP code (defaults to the configured home ZIP).

- The dashboard reads `GET /api/apps/weather/summary?zip=&hours=&days=` which
  returns `{ place, current, hourly[], daily[] }` (keyless open-meteo data).
- For chat answers about weather, use the platform weather tools
  (`get_current_weather`, `get_hourly_forecast`,
  `get_daily_forecast`, `get_rain_chance`) — same data source.
- The dashboard also shows a ~100-mile radar/alerts map (Leaflet + OSM tiles +
  IEM NEXRAD radar WMS + NWS active-alert polygons via GET /api/apps/weather/alerts).
- The app stores nothing.
