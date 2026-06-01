# Weather

Your local forecast — current conditions, the next 12 hours, a 10-day outlook,
and a radar/severe-weather map — for any US ZIP code.

## Overview

Weather gives you a quick, at-a-glance picture of conditions where you are (or
anywhere in the US). It opens to your **home ZIP code** — set in
**Settings → System → Default ZIP code** — so most of the time you just open it
and the forecast is already there. Type a different ZIP any time to look
elsewhere.

It's the same weather data Skipper uses when you ask in chat, so the app and the
chat always agree.

## Screens

The whole app is one scrollable dashboard:

- **Search bar (top right).** Type a 5-digit US ZIP and press **Go** to switch
  locations. The **↻ refresh** button re-pulls the latest data for the current
  location. With the box left as your home ZIP, the dashboard loads it on open.
- **Current conditions (top card).** The big number is the current temperature,
  with a weather icon and a short description (e.g. "Partly cloudy"). On the
  right: **feels-like** temperature, **humidity**, **wind** speed, and the
  **UV index** (with a Low/Moderate/High/Very high/Extreme label).
- **Next 12 hours.** A horizontal strip — one tile per hour with the time, an
  icon, the temperature, and the chance of rain (when there is one). Scroll it
  sideways.
- **10-day forecast.** A row per day with the day name, an icon, a short
  description, the rain chance, and the **high / low** temperatures.
- **Radar & severe-weather map (~100 mi).** An interactive map centered on your
  location:
  - **Base map** is OpenStreetMap. Drag to pan, use +/− or pinch to zoom.
  - **Radar (NEXRAD)** overlay shows live precipitation. Toggle it in the layer
    box (top-right of the map).
  - **Severe alerts** overlay outlines any active NWS warnings/watches near you;
    **click an alert area** to see the event, headline, and affected area.
  - The blue dot marks your location.

## Example workflows

**Check today's weather**
- *In the app:* open Weather — the current card and hourly strip are right there.
- *Through chat:* "what's the weather?" or "what's it like outside?"

**Look somewhere else**
- *In the app:* type the ZIP in the search box → **Go**.
- *Through chat:* "what's the weather in 90210?"

**Will it rain?**
- *In the app:* glance at the rain-chance numbers on the hourly strip.
- *Through chat:* "chance of rain today?" or "is it going to rain tonight?"

**Plan the week**
- *In the app:* read the 10-day forecast list.
- *Through chat:* "what's the daily forecast?" or "10-day forecast".

**Check for storms / see the radar**
- *In the app:* scroll to the map, turn on **Radar** and **Severe alerts**, and
  click any highlighted alert area for details.
- *Through chat:* ask "any weather alerts?" (the dashboard map is the richest
  view for radar/severe weather).

## Tips

- Set your home ZIP once in **Settings → System** and the app (and chat) default
  to it everywhere.
- The hourly and daily views are the "two forecasts" — short-term planning and
  the week ahead.
- Radar tiles come from NEXRAD and alerts from the National Weather Service.

## Your data

This app **stores nothing** — it reads live weather from public services
(open-meteo for the forecast, OpenStreetMap/NEXRAD for the map, the National
Weather Service for alerts) and needs no API key. There are no records to save
or recall.
