# Findings — weather

Survey only; nothing fixed. Corpus 7 → 67 records. Severity labels are the auditing agent's.

**1. HIGH — an alerts outage is indistinguishable from "no severe weather".**
`data.py::nws_alerts` — on any fetch failure: `except Exception: return empty` (an empty
`FeatureCollection` with **no `message`**). `ui/WeatherMap.jsx` then `.catch(() => {})`. So an NWS
outage, a timeout or a malformed response renders exactly like a location with nothing in force. The
module docstring and the non-US branch both explicitly say "never a silent empty result" — the failure
path violates the stated contract of the function it sits in. Expected: an explicit "couldn't check for
warnings" surfaced the way `us_only` is, so calm weather and an unchecked sky are distinguishable. **The
app's most consequential gap.**

**2. HIGH — any weekday-named rain question is silently answered for today.**
`tools.py::_period_window`, sixth branch: `if "today" in p or "day" in p:`. Every English weekday name
ends in "day" — monday, tuesday, wednesday, thursday, friday, saturday, sunday. "Will it rain Saturday?"
returns the window `now → tomorrow midnight`, labelled `"today"`. The label is the only tell and is easy
to miss in a spoken answer. `"this weekend"` hits the earlier `"week" in p` branch and returns a 7-day
window labelled "the next week" — also wrong, less badly. Expected: resolve named weekdays, or say the
question can't be answered rather than answering a different day.

**3. HIGH — the dashboard bypasses the entire caching feature.** `data.py` never imports `cache.py`;
`weather_summary` and `nws_alerts` call `_fetch_json` directly. So (a) every app open and every Refresh
hits Open-Meteo live and `enable_caching` has no effect on the app window at all; (b) the dashboard gets
**no** stale-on-failure degradation — the behaviour the caching feature exists to provide — and shows an
error where chat would have shown a slightly old reading; (c) the background pre-warm never benefits the
surface a person is most likely looking at. The retired spec scoped itself to `tools.py` and never
acknowledged the split.

**4. MODERATE — stale answers are served indefinitely with no age disclosed.**
`cache.py::cached_fetch` — on a fetch exception with an entry present, returns `entry[1]` with no age cap
and no marker. During a multi-day upstream outage someone asking "what's it like outside?" is told a
temperature from days ago in the same words as a live reading. The `stale-serve` WARNING goes to the
operator, not the person asking. The uncapped part is a deliberate operator choice ("stale beats
nothing") and is specced as such; the **undisclosed age** looks like an oversight. Expected: a max-stale
ceiling, or an "as of HH:MM" suffix.

**5. MODERATE — nothing reports UV, yet UV is a routing keyword.** `manifest.yaml`
`tool_category.keywords` includes `uv index`, so "what's the UV index?" routes here. None of the four
tools request or report it — `_current_weather_url` asks for temperature, humidity, apparent temperature,
weather code, wind speed and direction; the hourly and daily builders request no `uv_index` either. Only
the dashboard path fetches UV. Asking in chat or by voice gets a temperature-and-wind answer.

**6. MODERATE (uncertain) — the dashboard's current UV is probably blank most of the time.**
`data.py::weather_summary` does exact string equality between Open-Meteo's `current.time` and an hourly
timestamp (`if cur_iso and cur_iso in htimes`). Open-Meteo returns `current.time` on a 15-minute boundary
(`…T15:15`) while `hourly.time` is on the hour, so the match succeeds only in the first quarter of each
hour; when it fails `cur_uv` stays `None` and the UI drops the UV line silently. *Could not verify the
live payload offline, and granularity may vary by model.* Expected: truncate to the hour, or take the
nearest index. One live call would confirm.

**7. MODERATE — the cache grows without bound and cannot be cleared by an operator.**
`cache.py::_ENTRIES` is never evicted — no TTL sweep, no size cap, no LRU. Every distinct place anyone
asks about leaves up to four entries (four lookup shapes) alive for the process lifetime, each holding a
full Open-Meteo payload. Household use will not exhaust memory, but nothing bounds it. `clear()` exists
and is called only from tests — there is no operator or user path to force a fresh read inside the
freshness window, and the dashboard's Refresh does not clear the tool cache (it does not use it — §3).

**8. MODERATE — `guide.md` and `help.md` document a ZIP-code app that no longer exists.**
`guide.md` says "for a US ZIP code (defaults to the configured home ZIP)" and names
`GET /api/apps/weather/summary?zip=&hours=&days=` — there is **no `zip` parameter** on
`routes.py::api_summary` (its parameters are `location, hours, days, lat, lon, label, cc`), so an agent
following the guide sends something FastAPI ignores. `help.md` — which is user-facing — says "for any US
ZIP code", "It opens to your **home ZIP code** — set in Settings → System → Default ZIP code", "Type a
5-digit US ZIP and press Go". The setting is now Settings → System → Location
(`app_platform/location.py` `_SETTING_KEY = "default_location"`; `default_zip` survives only as a lazily
migrated legacy key) and the app is fully international. **`help.md` actively misinstructs a household.**

**9. MODERATE — the manifest describes the radar map as unbuilt and the app as US-only.**
`manifest.yaml` `description`: "…a 10-day outlook for your ZIP code … **A ~100-mile radar/alerts map is
a planned follow-up.**" The radar map is built and shipping (`ui/WeatherMap.jsx`, `routes.py::api_alerts`,
a Radar tab in `ui/index.js`). `tool_category.description` also says "for a US ZIP code (keyless NOAA /
open-meteo data)" — the app takes no ZIP, and NOAA supplies only the alerts. The manifest description is
what the app-picker and agent context show, so this is visible drift.

**10. LOW — the `refresh_interval_minutes` help text describes a floor that can never engage.** The
manifest says "values under 30 seconds are floored", but the field is an integer in *minutes* so the
smallest positive value is 60 seconds. `cache.py::effective_ttl`'s 30-second clamp can only fire for `0`,
a negative, or a non-number — and the description says nothing about what happens at `0`. There is also
no declared maximum: `refresh_interval_minutes: 100000` makes the background loop sleep ~69 days and the
freshness window match it, so one fat-fingered setting freezes weather answers indefinitely with no
warning.

**11. LOW — six fetched-and-shipped fields are never displayed.** `weather_summary` requests and returns
`current.wind_dir` (the chat tools show it; `WeatherApp.jsx` shows speed only), `current.is_day` (no
day/night icon variation exists), `hourly[].uv`, `daily[].uv`, `daily[].sunrise`, `daily[].sunset`.
Sunrise/sunset in particular is a natural thing to want, is already paid for on every request, and is
dropped. Either render them or stop requesting them.

**12. LOW — dead import.** `data.py:16` — `from datetime import date, datetime`; neither name is
referenced anywhere in the file.

**13. LOW — renaming spec ids dangles a cross-corpus reference.**
`specs/platform/location/resolver.yaml` (the platform corpus) references
`weather.current-conditions.location-input-comfortable-width` by id at lines 55 and 116 and pins its
placeholder string. This audit renames that spec to
`weather.dashboard.a-full-place-name-fits-in-the-box`, so the platform reference now names a spec that
does not exist. The loader does not resolve cross-capability references, so nothing breaks mechanically —
the platform spec is simply wrong now. Four test-file docstrings also name retired ids in comments.

**14. LOW — background pre-warm never covers the spans people actually ask for.**
`background.py::_refresh_once` warms exactly four entries, including
`_daily_forecast_for_place(place, 7)`. Because `days` enters the request URL and so the cache key, a
"10-day forecast" question — one of the manifest's own routing keywords, and the dashboard's default — is
never warm and always pays a live fetch. Expected: warm the spans the product defaults to, or normalise
the daily request to the maximum span and slice down.

**15. LOW (uncertain) — the label echoed back by `/summary` is caller-supplied and unverified.**
`routes.py::api_summary` accepts `label` and `cc`, and `data.py::_place_from_coords` returns
`label.strip()` as `place.display_label` with no check that it relates to the coordinates. A caller can
make the dashboard render any place name over any location's weather. It is rendered as React text, so
not XSS — a trust boundary worth naming given the endpoint exists to skip re-verifying the place. *Did
not establish whether `/api/apps/*` sits behind household auth;* if not,
`/summary?location=<anything>` is also an open geocoding-and-forecast proxy any LAN client can drive at
the install's IP and rate budget.

**16. INFO — `platform_deps: []` understates the coupling.** The app imports
`app_platform.location`, `.config`, `.time` and `.lifecycle`. Same drift already recorded for email and
others; `specs/APP_PACKAGES.md` documents `platform_deps` as intent only.

**17. INFO — a stale comment names a service the app no longer uses.**
`app_platform/capabilities.py:198` — "the Weather app is fully keyless (open-meteo / **zippopotam** /
weather.gov)". The zippopotam postal lookup was removed when location resolution moved to the platform
service, and `tests/test_weather_tools.py` asserts against its return ever appearing. The substantive
claim (no key needed) is correct.

**18. INFO — ack strings disagree between manifest and docstring.**
`tool_category.ack.get_rain_chance` is "Checking the chance of rain..."; the `Ack:` line in
`get_rain_chance`'s docstring says "Checking rain chances...". Two sources for one user-visible string;
which one `tool_router.get_ack_template` serves was not traced. The other three tools agree.
