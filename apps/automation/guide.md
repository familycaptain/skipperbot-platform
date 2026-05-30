# Automation - Tool Guide

Automation uses the Home Assistant REST API through MCP tools. Configure:

- `HOME_ASSISTANT_URL` - base URL, e.g. `https://homeassistant.example.com` or `http://homeassistant.local:8123`
- `HOME_ASSISTANT_TOKEN` - a Home Assistant long-lived access token from the user's Home Assistant profile

## Tools

- `test_home_assistant_connection` - Verify HA URL/token and show basic config/version
- `resolve_home_assistant_entity` - Resolve human names/aliases like "tv" or "garage door" to HA entities
- `list_home_assistant_aliases` - List saved human aliases for HA entities
- `add_home_assistant_alias` - Save a human alias for an HA entity
- `delete_home_assistant_alias` - Remove a saved alias
- `list_home_assistant_entities` - Browse/search HA entities by domain or query
- `get_home_assistant_entity` - Read one entity's current state and key attributes
- `list_home_assistant_services` - See available HA service domains/services
- `call_home_assistant_service` - Generic service call for advanced automation actions
- `turn_on_home_assistant_entity` - Turn on a light/switch/fan/input_boolean/etc.
- `turn_off_home_assistant_entity` - Turn off a light/switch/fan/input_boolean/etc.
- `toggle_home_assistant_entity` - Toggle a controllable entity
- `set_home_assistant_light` - Set light brightness/color
- `find_home_assistant_low_batteries` - Find low/unavailable battery sensors

## Key Rules

1. **Resolve human names first**: When the user gives a normal name like "tv", "living room tv", "office lamp", "garage door", "nas", or "bedroom fan", first use `resolve_home_assistant_entity` or pass the human name directly to `get_home_assistant_entity`. Do not expect users to know entity IDs.
2. **Pass concise object names to the resolver**: For a question like "is the NAS ping sensor up?", resolve `nas ping` or `nas`, not the whole sentence. For "is the garage door closed?", resolve `garage door`.
3. **Aliases are learned on confident resolution**: `resolve_home_assistant_entity`, `get_home_assistant_entity`, and the common control helpers can save confident natural-name matches automatically. Use `add_home_assistant_alias` when the user explicitly identifies or corrects a mapping.
4. **Read before controlling when ambiguous**: If no alias/exact match exists, search by likely domain and query, e.g. `list_home_assistant_entities(domain="light", query="office")`. Ask if multiple plausible matches remain.
5. **Use services for real devices**: To control devices, call services like `light.turn_on`, `switch.turn_off`, `media_player.turn_on`, or `climate.set_temperature`. Do not update `/api/states` for real device control.
6. **Prefer helper tools for common actions**: Use `turn_on_home_assistant_entity`, `turn_off_home_assistant_entity`, `toggle_home_assistant_entity`, or `set_home_assistant_light` before the generic `call_home_assistant_service`. These helpers can accept saved aliases like "tv".
7. **Sensors are read-only**: For "check sensor", "what is the temperature in X", "is the door open", use `resolve_home_assistant_entity`, `list_home_assistant_entities`, or `get_home_assistant_entity`.

7a. **Routing temperature/weather questions: time + location decides the tool**:

    The single most important axis is **time**:
    - **NOW (present moment)** → Home Assistant sensor (this app).
    - **FUTURE (forecast, later, tomorrow, this weekend, "will it...")** → weather voice app (switch with `switch_voice_app(app_name="weather")`).
    - **PAST (yesterday, last week)** → also weather voice app — HA doesn't keep ambient history at that resolution.

    Once time is "NOW", the secondary axis is **location**:
    - **Named location with a plausible household sensor** ("outside", "in the office", "bedroom", "garage", "in the kitchen") → HA sensor here.
    - **No location given, just general atmosphere** ("what's the weather", "is it windy") → weather voice app; HA can't answer atmosphere generally.

    **Use this app's HA sensor tools when ALL of:** present tense, named location, measurable by a household sensor (temperature, humidity, brightness, air quality, motion, door/window state, etc.). Examples:
    - "what is the temperature outside" → HA (now + outside)
    - "how warm is the office" → HA (now + office)
    - "how humid is the bedroom" → HA (now + bedroom)
    - "is the garage door open" → HA (now + garage)

    **Switch to the weather voice app when ANY of:** the question is future/past tense, OR refers to forecast/precipitation/wind/conditions without a sensor-bearing location. Call `switch_voice_app(app_name="weather")` first, then answer with that app's forecast tools loaded. Examples:
    - "what is the temperature tomorrow" → weather (future)
    - "how hot will it be later today" / "tonight" / "this weekend" → weather (future)
    - "will it rain" / "chance of rain" / "rain tonight" / "rain over the next week" → weather (forecast)
    - "what's the weather" / "weather today" / "weather right now" → weather (general atmosphere, no sensor location)
    - "is it windy" / "wind speed" → weather (HA usually has no wind sensor)
    - "what was the temperature yesterday" → weather (past)

    Do NOT try to satisfy a forecast or general-weather question from HA sensors.

    **Ambiguous case — "what is the temperature outside?"** This is the *one* phrase that overlaps. Treat it as an HA sensor query first because the user typically has a sensor named "outside" (or similar) and means *right now, at my house*. Steps:
    1. `list_home_assistant_entities(domain="sensor", query="outside temperature")` — try the verbatim location word first. Widen to `query="outside"` if no match.
    2. If exactly one plausible sensor matches: `get_home_assistant_entity(entity_id="...")` and report the value with its friendly name.
    3. If multiple plausible matches: list them briefly and ask which one. Never guess.
    4. If nothing matches: say "I couldn't find an outside-temperature sensor" and offer to switch to the weather app for the local forecast instead. **NEVER fabricate, estimate, or recall-from-training a sensor value. If a sensor isn't found, say so — do not produce a number.**

    Same shape applies to humidity, brightness, air quality, motion, occupancy, door state, etc. — any sensor type that exists in this home.
8. **Door/opening binary sensors**: If a `binary_sensor` entity has "door", "garage", "gate", "window", "contact", or "opening" in its entity_id, friendly name, or device_class, report `on` as "open" and `off` as "closed". Do not answer with raw "on/off" unless the user specifically asks for the raw Home Assistant state.
9. **Ping/connectivity binary sensors**: If a `binary_sensor` is a ping/connectivity/server sensor, report `on` as "online/up/reachable" and `off` as "offline/down/unreachable" unless the entity's friendly name clearly means the opposite.
10. **Answer the user's question, not the API trace**: For normal automation answers, do not mention entity IDs, device_class, domain names, or raw Home Assistant states. Say the human result plainly, e.g. "Yes, the garage door is closed." Include internal HA details only if the user asks for raw state, diagnostics, entity names, or troubleshooting.
11. **Battery scans**: For "what batteries need replacing", "check low batteries", or "scan for dead batteries", use `find_home_assistant_low_batteries`.
12. **Sensitive actions**: For locks, garage doors, alarms, cameras, or security-affecting services, read state first and confirm before changing state unless the user gives an explicit direct command.

## Common Examples

- "Check Home Assistant" -> `test_home_assistant_connection()`
- "Turn on the TV" -> resolve alias/name "tv", then `turn_on_home_assistant_entity(entity_id="tv")`
- "TV means media_player.lg_webos_tv_oled65c2pua_2" -> `add_home_assistant_alias(alias="tv", entity_id="media_player.lg_webos_tv_oled65c2pua_2")`
- "What sensors do we have?" -> `list_home_assistant_entities(domain="sensor")`
- "What's the office temperature?" -> `list_home_assistant_entities(domain="sensor", query="office temperature")`, then `get_home_assistant_entity(entity_id="...")`
- "What is the temperature outside?" (NOW + outside) -> `list_home_assistant_entities(domain="sensor", query="outside temperature")`, then `get_home_assistant_entity(entity_id="...")`. If nothing matches, widen to `query="outside"`. If still no match, tell the user there's no outside sensor and offer to switch to the weather app for the local forecast. NEVER make up a number.
- "How humid is it in the bedroom?" (NOW + bedroom) -> `list_home_assistant_entities(domain="sensor", query="bedroom humidity")`, then `get_home_assistant_entity(...)`
- "What is the temperature tomorrow?" (FUTURE) -> `switch_voice_app(app_name="weather")`, then use forecast tools — NOT HA sensors.
- "Will it rain tonight?" (FUTURE forecast) -> `switch_voice_app(app_name="weather")`.
- "What's the weather today?" (general atmosphere, no sensor location) -> `switch_voice_app(app_name="weather")`.
- "Is the garage closed?" -> `list_home_assistant_entities(domain="binary_sensor", query="garage")`, then interpret the matched door/opening sensor as `on` = open, `off` = closed
- "Turn on the office lamp" -> find matching `light` entity if needed, then `turn_on_home_assistant_entity(entity_id="light...")`
- "Dim the living room lights to 40%" -> find matching light if needed, then `set_home_assistant_light(entity_id="light...", brightness_pct=40)`
- "Check batteries that need replacing" -> `find_home_assistant_low_batteries(threshold=25)`
