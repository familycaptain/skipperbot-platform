"""Automation app tools for Home Assistant.

These tools are a double-hop bridge: Skipper MCP tool -> Home Assistant REST API.
"""

import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from config import logger
from app_platform.db import fetch_all_in_schema, scoped_conn

SCHEMA = "app_automation"

# Legacy on-disk alias cache, pre-DB. Imported once into app_automation.ha_aliases
# on an upgraded install, then ignored. New installs never create it.
_LEGACY_ALIASES_PATH = Path(__file__).with_name("aliases.json")
_aliases_legacy_imported = False


def _ha_base_url() -> str:
    from app_platform import settings as _settings
    url = (_settings.get("home_assistant_url", scope="app:automation", default="") or "").strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url


def _ha_token() -> str:
    from app_platform import settings as _settings
    return (_settings.get("home_assistant_token", scope="app:automation", secret=True, default="") or "").strip()


def _ha_setup_error() -> str:
    missing = []
    if not _ha_base_url():
        missing.append("URL")
    if not _ha_token():
        missing.append("access token")
    if missing:
        return (
            "Home Assistant is not configured. Set the "
            + " and ".join(missing)
            + " in Settings → Automation (use a Home Assistant long-lived access token)."
        )
    return ""


def _ha_request(method: str, path: str, payload: dict | None = None, query: dict | None = None):
    setup_error = _ha_setup_error()
    if setup_error:
        raise RuntimeError(setup_error)

    base = _ha_base_url()
    url = base + path
    if query:
        query_parts = []
        for key, value in query.items():
            if value is None:
                continue
            quoted_key = urllib.parse.quote_plus(str(key))
            if value == "":
                query_parts.append(quoted_key)
            else:
                query_parts.append(f"{quoted_key}={urllib.parse.quote_plus(str(value))}")
        if query_parts:
            url += "?" + "&".join(query_parts)

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {_ha_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SkipperBot/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return json.loads(raw)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Home Assistant API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Home Assistant: {exc.reason}") from exc


def _ha_states() -> list[dict]:
    states = _ha_request("GET", "/api/states")
    return states if isinstance(states, list) else []


def _import_legacy_aliases_once() -> None:
    """One-time: seed ha_aliases from a pre-DB aliases.json if the table is
    empty, so upgraded installs keep trained aliases without committing them."""
    global _aliases_legacy_imported
    if _aliases_legacy_imported:
        return
    _aliases_legacy_imported = True
    try:
        if not _LEGACY_ALIASES_PATH.is_file():
            return
        data = json.loads(_LEGACY_ALIASES_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data:
            return
        if fetch_all_in_schema(SCHEMA, "SELECT 1 FROM ha_aliases LIMIT 1"):
            return  # already have DB state — don't clobber it
        with scoped_conn(SCHEMA) as conn:
            with conn.cursor() as cur:
                for alias, d in data.items():
                    if not isinstance(d, dict):
                        continue
                    entity_id = str(d.get("entity_id") or "").strip()
                    if not alias or not entity_id:
                        continue
                    cur.execute(
                        "INSERT INTO ha_aliases (alias, entity_id, notes) VALUES (%s, %s, %s) "
                        "ON CONFLICT (alias) DO NOTHING",
                        (alias, entity_id, str(d.get("notes") or "")),
                    )
            conn.commit()
        logger.info("AUTOMATION: imported %d alias(es) from legacy aliases.json into ha_aliases", len(data))
    except Exception as exc:
        logger.warning("AUTOMATION: legacy aliases import skipped: %s", exc)


def _load_aliases() -> dict[str, dict]:
    _import_legacy_aliases_once()
    try:
        rows = fetch_all_in_schema(SCHEMA, "SELECT alias, entity_id, notes FROM ha_aliases")
    except Exception as exc:
        logger.warning("AUTOMATION: could not load ha_aliases: %s", exc)
        return {}
    return {
        r["alias"]: {"entity_id": r.get("entity_id") or "", "notes": r.get("notes") or ""}
        for r in rows
    }


def _save_aliases(aliases: dict[str, dict]) -> None:
    """Replace ha_aliases with the given {alias: {entity_id, notes}} map.

    Callers load-modify-save the whole dict, so we rewrite the table atomically.
    """
    with scoped_conn(SCHEMA) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ha_aliases")
            for alias, d in aliases.items():
                entity_id = str((d or {}).get("entity_id") or "").strip()
                if not alias or not entity_id:
                    continue
                cur.execute(
                    "INSERT INTO ha_aliases (alias, entity_id, notes) VALUES (%s, %s, %s) "
                    "ON CONFLICT (alias) DO UPDATE SET "
                    "  entity_id = EXCLUDED.entity_id, notes = EXCLUDED.notes, updated_at = now()",
                    (alias, entity_id, str((d or {}).get("notes") or "")),
                )
        conn.commit()


def _normalize_name(value: str) -> str:
    value = (value or "").lower().strip()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _entity_domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _entity_search_text(entity: dict) -> str:
    attrs = entity.get("attributes") or {}
    parts = [
        entity.get("entity_id") or "",
        attrs.get("friendly_name") or "",
        attrs.get("device_class") or "",
    ]
    return _normalize_name(" ".join(str(part) for part in parts))


def _entity_score(entity: dict, query: str, preferred_domain: str = "") -> int:
    normalized_query = _normalize_name(query)
    if not normalized_query:
        return 0

    entity_id = str(entity.get("entity_id") or "")
    attrs = entity.get("attributes") or {}
    friendly = _normalize_name(str(attrs.get("friendly_name") or ""))
    entity_name = _normalize_name(entity_id.replace(".", " "))
    haystack = _entity_search_text(entity)
    query_tokens = normalized_query.split()

    score = 0
    if normalized_query == friendly:
        score += 100
    if normalized_query == entity_name:
        score += 90
    if normalized_query in friendly:
        score += 60
    if normalized_query in entity_name:
        score += 50
    if normalized_query in haystack:
        score += 35
    score += sum(8 for token in query_tokens if token in haystack)
    if preferred_domain and entity_id.startswith(preferred_domain + "."):
        score += 20
    if entity.get("state") in {"unavailable", "unknown"}:
        score -= 15
    return score


def _rank_entities(
    query: str,
    preferred_domain: str = "",
    include_unavailable: bool = True,
) -> list[tuple[int, dict]]:
    states = _ha_states()
    if preferred_domain:
        states = [
            e for e in states
            if str(e.get("entity_id", "")).startswith(preferred_domain + ".")
        ]
    if not include_unavailable:
        states = [e for e in states if e.get("state") not in {"unavailable", "unknown"}]

    scored = [(_entity_score(entity, query, preferred_domain), entity) for entity in states]
    scored = [(score, entity) for score, entity in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _alias_notes_for_entity(entity: dict) -> str:
    attrs = entity.get("attributes") or {}
    friendly = str(attrs.get("friendly_name") or "").strip()
    return friendly or str(entity.get("entity_id") or "").strip()


def _maybe_learn_alias(
    alias: str,
    entity: dict,
    score: int,
    second_score: int = 0,
    *,
    overwrite: bool = False,
) -> bool:
    raw_alias = (alias or "").strip()
    key = _normalize_name(raw_alias)
    entity_id = str(entity.get("entity_id") or "").strip()
    if not key or not entity_id:
        return False
    if "." in raw_alias or key in {"on", "off", "open", "closed", "up", "down"}:
        return False

    # Learn only when the best match is reasonably strong and not neck-and-neck.
    if score < 50:
        return False
    if second_score and score - second_score < 15 and score < 90:
        return False

    aliases = _load_aliases()
    existing = aliases.get(key)
    if existing and not overwrite:
        return str(existing.get("entity_id") or "") == entity_id

    aliases[key] = {
        "entity_id": entity_id,
        "notes": _alias_notes_for_entity(entity),
    }
    _save_aliases(aliases)
    logger.info("AUTOMATION: Learned Home Assistant alias '%s' -> %s", key, entity_id)
    return True


def _resolve_entity(name_or_entity_id: str, domain: str = "") -> dict | None:
    value = (name_or_entity_id or "").strip()
    if not value:
        return None

    preferred_domain = domain.strip().lower() if domain else ""
    if "." in value and (not preferred_domain or value.startswith(preferred_domain + ".")):
        try:
            entity = _ha_request("GET", f"/api/states/{urllib.parse.quote(value, safe='.')}")
            return entity if isinstance(entity, dict) and entity.get("entity_id") else {"entity_id": value}
        except Exception:
            return {"entity_id": value}

    aliases = _load_aliases()
    normalized = _normalize_name(value)
    alias = aliases.get(normalized)
    if alias:
        entity_id = str(alias.get("entity_id") or "").strip()
        if entity_id and (not preferred_domain or entity_id.startswith(preferred_domain + ".")):
            try:
                entity = _ha_request("GET", f"/api/states/{urllib.parse.quote(entity_id, safe='.')}")
                if isinstance(entity, dict):
                    return entity
            except Exception:
                return {"entity_id": entity_id}

    scored = _rank_entities(value, preferred_domain)
    return scored[0][1] if scored else None


def _resolve_entity_id(name_or_entity_id: str, domain: str = "", learn_alias: bool = True) -> str:
    value = (name_or_entity_id or "").strip()
    preferred_domain = domain.strip().lower() if domain else ""
    entity = _resolve_entity(value, preferred_domain)
    if learn_alias and entity and "." not in value:
        scored = _rank_entities(value, preferred_domain)
        if scored and scored[0][1].get("entity_id") == entity.get("entity_id"):
            second_score = scored[1][0] if len(scored) > 1 else 0
            _maybe_learn_alias(value, entity, scored[0][0], second_score)
    return str(entity.get("entity_id") or "").strip() if entity else (name_or_entity_id or "").strip()


def _entity_display(entity: dict) -> str:
    attrs = entity.get("attributes") or {}
    friendly = attrs.get("friendly_name") or entity.get("entity_id") or "unknown"
    unit = attrs.get("unit_of_measurement") or ""
    state = entity.get("state") or "unknown"
    state_display = f"{state}{unit}" if unit and state not in {"unknown", "unavailable"} else state
    return f"{friendly} ({entity.get('entity_id')}) = {state_display}"


def _matches_entity(entity: dict, query: str) -> bool:
    return _entity_score(entity, query) > 0


def list_home_assistant_aliases(query: str = "") -> str:
    """List saved human aliases for Home Assistant entities.

    Use this when the user asks what names are known, or before resolving
    natural names like "tv", "lamp", "garage door", or "bedroom fan".

    Args:
        query: Optional alias/entity/note search text.

    Returns:
        Saved aliases and their mapped Home Assistant entity IDs.

    Ack: Listing Home Assistant aliases...
    """
    try:
        aliases = _load_aliases()
        rows = []
        normalized_query = _normalize_name(query)
        for alias, data in sorted(aliases.items()):
            entity_id = str(data.get("entity_id") or "")
            notes = str(data.get("notes") or "")
            haystack = _normalize_name(f"{alias} {entity_id} {notes}")
            if normalized_query and normalized_query not in haystack:
                continue
            rows.append((alias, entity_id, notes))

        if not rows:
            return "No Home Assistant aliases found."

        lines = [f"Home Assistant aliases ({len(rows)}):"]
        for alias, entity_id, notes in rows:
            suffix = f" - {notes}" if notes else ""
            lines.append(f"- {alias} -> {entity_id}{suffix}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_home_assistant_aliases: {str(e)}"


def add_home_assistant_alias(alias: str, entity_id: str, notes: str = "") -> str:
    """Save a human-friendly alias for a Home Assistant entity.

    Use this when the user says a normal name should mean a specific entity,
    such as "tv means media_player.lg_webos_tv_oled65c2pua_2".

    Args:
        alias: Human name, e.g. "tv", "living room lamp", "garage door".
        entity_id: Full Home Assistant entity ID.
        notes: Optional description.

    Returns:
        Confirmation of the saved alias.

    Ack: Saving Home Assistant alias...
    """
    try:
        key = _normalize_name(alias)
        entity = entity_id.strip()
        if not key:
            return "Error: alias is required."
        if "." not in entity:
            return "Error: entity_id must be a full Home Assistant entity ID."

        aliases = _load_aliases()
        aliases[key] = {"entity_id": entity, "notes": notes.strip() if notes else ""}
        _save_aliases(aliases)
        logger.info("AUTOMATION: Saved Home Assistant alias '%s' -> %s", key, entity)
        return f"Saved alias '{key}' -> {entity}."
    except Exception as e:
        return f"Error in add_home_assistant_alias: {str(e)}"


def delete_home_assistant_alias(alias: str) -> str:
    """Delete a saved Home Assistant alias.

    Args:
        alias: Human alias to delete.

    Returns:
        Confirmation or not-found message.

    Ack: Deleting Home Assistant alias...
    """
    try:
        key = _normalize_name(alias)
        aliases = _load_aliases()
        if key not in aliases:
            return f"No alias found for '{alias}'."
        aliases.pop(key)
        _save_aliases(aliases)
        return f"Deleted Home Assistant alias '{key}'."
    except Exception as e:
        return f"Error in delete_home_assistant_alias: {str(e)}"


def find_home_device(name: str) -> str:
    """Find a Home Assistant DEVICE by friendly name or alias and list its entities.

    Use this FIRST when the user refers to a physical device by a common name
    (e.g. "tv", "alfred jr", "kitchen lamp") and you need to know what
    sensors/switches/etc. that device has, so you can pick the right entity
    for what the user is asking about.

    Workflow for "is alfred jr charged?":
      1. Call find_home_device("alfred jr") → returns the device + its entities
      2. Look at the entity list, pick the one matching "charged" semantics
         (sensor.alfred_jr_battery in this case)
      3. Call get_home_assistant_entity("sensor.alfred_jr_battery") for the
         live state value

    State values are NOT included in this response — entity state can change
    every second, so always fetch it live with get_home_assistant_entity.

    Args:
        name: The friendly name or alias the user spoke (e.g. "tv",
              "alfred junior", "garage door").

    Returns:
        Device metadata + complete entity list (entity_id, friendly name,
        device_class, domain). The LLM picks which entity matches the user's
        intent and then calls get_home_assistant_entity on it.

    Ack: Looking up device "{name}"...
    """
    try:
        from apps.automation import devices as _dev
        _dev.warm_entities_cache_if_empty()
        match = _dev.find_device(name)
        if not match:
            return (
                f"No device found matching '{name}'. "
                "Try a different alias, or call list_home_assistant_aliases to see known "
                "names. If it's a real entity, you can teach the name with "
                "add_home_assistant_alias(alias, entity_id)."
            )
        device_id, device = match
        entities = _dev.get_entities_for_device(device_id)
        lines = [
            f"**{device['name']}** ({device.get('manufacturer', '')} {device.get('model', '')})".strip(),
            f"  device_id: {device_id}",
            f"  aliases:   {', '.join(device.get('aliases', [])) or '(none)'}",
            f"  entities ({len(entities)}):",
        ]
        for e in entities:
            dc = f" [{e['device_class']}]" if e.get("device_class") else ""
            unit = f" ({e['unit_of_measurement']})" if e.get("unit_of_measurement") else ""
            label = e.get("name") or e.get("entity_id")
            lines.append(f"    - {e['entity_id']:55s} {label}{dc}{unit}")
        lines.append(
            "\nNext: pick the entity_id that matches the user's question and "
            "call get_home_assistant_entity(entity_id) to fetch the live state."
        )
        return "\n".join(lines)
    except Exception as e:
        return f"Error in find_home_device: {str(e)}"


def resolve_home_assistant_entity(
    name: str,
    domain: str = "",
    include_unavailable: bool = False,
    learn_alias: bool = True,
) -> str:
    """Resolve a human name or alias to the best Home Assistant entity.

    Use this before controlling or reading a device when the user gives a
    normal name like "tv", "garage door", "office lamp", or "bedroom fan".
    Alias matches are preferred over fuzzy Home Assistant entity search.

    Args:
        name: Human name, alias, friendly name, or entity ID.
        domain: Optional HA domain filter, e.g. "media_player", "light", "sensor".
        include_unavailable: Whether unavailable/unknown entities may be returned.
        learn_alias: Save the name as an alias when the match is confident.

    Returns:
        Best matching entity with current state, or close candidates if unclear.

    Ack: Resolving Home Assistant entity...
    """
    try:
        if not name or not name.strip():
            return "Error: name is required."

        preferred_domain = domain.strip().lower() if domain else ""
        value = name.strip()
        resolved = _resolve_entity(value, preferred_domain)
        if resolved and (include_unavailable or resolved.get("state") not in {"unavailable", "unknown"}):
            if learn_alias and "." not in value:
                scored = _rank_entities(value, preferred_domain, include_unavailable=include_unavailable)
                if scored and scored[0][1].get("entity_id") == resolved.get("entity_id"):
                    second_score = scored[1][0] if len(scored) > 1 else 0
                    _maybe_learn_alias(value, resolved, scored[0][0], second_score)
            return "Resolved Home Assistant entity:\n" + _entity_display(resolved)

        scored = _rank_entities(value, preferred_domain, include_unavailable=include_unavailable)
        if not scored:
            alias_hint = list_home_assistant_aliases(name)
            return f"No Home Assistant entity found for '{name}'.\n{alias_hint}"

        if learn_alias:
            second_score = scored[1][0] if len(scored) > 1 else 0
            if _maybe_learn_alias(value, scored[0][1], scored[0][0], second_score):
                return "Resolved Home Assistant entity:\n" + _entity_display(scored[0][1])

        lines = [f"Possible Home Assistant entities for '{name}':"]
        for score, entity in scored[:8]:
            lines.append(f"- {_entity_display(entity)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in resolve_home_assistant_entity: {str(e)}"


def test_home_assistant_connection() -> str:
    """Check whether the configured Home Assistant REST API is reachable.

    Requires HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in .env.

    Returns:
        Connection status and basic Home Assistant config if available.

    Ack: Checking Home Assistant...
    """
    try:
        setup_error = _ha_setup_error()
        if setup_error:
            return setup_error
        api = _ha_request("GET", "/api/")
        config = _ha_request("GET", "/api/config")
        return (
            "Home Assistant connection OK.\n"
            f"API: {api.get('message', 'reachable') if isinstance(api, dict) else 'reachable'}\n"
            f"Location: {config.get('location_name', '(unknown)') if isinstance(config, dict) else '(unknown)'}\n"
            f"Version: {config.get('version', '(unknown)') if isinstance(config, dict) else '(unknown)'}"
        )
    except Exception as e:
        return f"Error in test_home_assistant_connection: {str(e)}"


def list_home_assistant_entities(
    domain: str = "",
    query: str = "",
    include_unavailable: bool = False,
    limit: int = 50,
) -> str:
    """List Home Assistant entities, optionally filtered by domain or search text.

    Args:
        domain: Optional HA entity domain, e.g. "light", "sensor", "switch", "binary_sensor".
        query: Optional search text matched against entity_id, friendly_name, or device_class.
        include_unavailable: Include unavailable/unknown entities.
        limit: Maximum number of entities to show.

    Returns:
        Formatted matching entities with current states.

    Ack: Listing Home Assistant entities...
    """
    try:
        entities = _ha_states()
        if domain and domain.strip():
            prefix = domain.strip().lower() + "."
            entities = [e for e in entities if str(e.get("entity_id", "")).startswith(prefix)]
        if query and query.strip():
            entities = [e for e in entities if _matches_entity(e, query.strip())]
        if not include_unavailable:
            entities = [e for e in entities if e.get("state") not in {"unavailable", "unknown"}]

        entities.sort(key=lambda e: ((e.get("attributes") or {}).get("friendly_name") or e.get("entity_id") or ""))
        if not entities:
            return "No matching Home Assistant entities found."

        shown = entities[:max(1, min(limit, 200))]
        lines = [f"Home Assistant entities ({len(entities)} match(es), showing {len(shown)}):\n"]
        for entity in shown:
            lines.append(f"- {_entity_display(entity)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_home_assistant_entities: {str(e)}"


def get_home_assistant_entity(entity_id: str) -> str:
    """Get the current state and attributes for a Home Assistant entity or alias.

    Args:
        entity_id: Full Home Assistant entity ID or saved/human alias, e.g. "sensor.hall_temperature" or "garage door".

    Returns:
        Entity state, timestamps, and key attributes.

    Ack: Reading Home Assistant entity...
    """
    try:
        if not entity_id or not entity_id.strip():
            return "Error: entity_id is required."
        resolved_id = _resolve_entity_id(entity_id.strip())
        entity = _ha_request("GET", f"/api/states/{urllib.parse.quote(resolved_id, safe='.')}")
        if not isinstance(entity, dict):
            return f"No entity found for {entity_id}."
        attrs = entity.get("attributes") or {}
        lines = [
            _entity_display(entity),
            f"Last changed: {entity.get('last_changed', '?')}",
            f"Last updated: {entity.get('last_updated', '?')}",
        ]
        interesting = [
            "device_class", "unit_of_measurement", "battery_level", "brightness",
            "supported_color_modes", "current_temperature", "temperature",
        ]
        shown_attrs = {k: attrs.get(k) for k in interesting if k in attrs}
        if shown_attrs:
            lines.append("Attributes:")
            for key, value in shown_attrs.items():
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in get_home_assistant_entity: {str(e)}"


def list_home_assistant_services(domain: str = "") -> str:
    """List Home Assistant service domains and services.

    Args:
        domain: Optional service domain to filter, e.g. "light", "switch", "climate".

    Returns:
        Service domains with service names.

    Ack: Listing Home Assistant services...
    """
    try:
        services = _ha_request("GET", "/api/services")
        if not isinstance(services, list):
            return "No services returned by Home Assistant."
        if domain and domain.strip():
            domain_value = domain.strip().lower()
            services = [s for s in services if s.get("domain") == domain_value]
        if not services:
            return "No matching Home Assistant services found."
        lines = [f"Home Assistant services ({len(services)} domain(s)):\n"]
        for entry in sorted(services, key=lambda s: s.get("domain", "")):
            names = sorted((entry.get("services") or {}).keys()) if isinstance(entry.get("services"), dict) else entry.get("services", [])
            lines.append(f"- {entry.get('domain')}: {', '.join(names)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in list_home_assistant_services: {str(e)}"


def call_home_assistant_service(
    domain: str,
    service: str,
    entity_id: str = "",
    service_data: str = "{}",
    return_response: bool = False,
) -> str:
    """Call any Home Assistant service.

    Use specific helper tools for common light/switch on/off/toggle actions.
    Use this generic tool when a specific Home Assistant service is needed.

    Args:
        domain: HA service domain, e.g. "light", "switch", "script", "climate".
        service: Service name, e.g. "turn_on", "turn_off", "toggle", "set_temperature".
        entity_id: Optional entity_id to include in service_data.
        service_data: JSON object string of service data.
        return_response: Request HA response data if the service supports it.

    Returns:
        Confirmation and changed states returned by Home Assistant.

    Ack: Calling Home Assistant service...
    """
    try:
        if not domain or not service:
            return "Error: domain and service are required."
        try:
            data = json.loads(service_data) if isinstance(service_data, str) and service_data.strip() else {}
        except (json.JSONDecodeError, TypeError):
            return "Error: service_data must be a JSON object string."
        if not isinstance(data, dict):
            return "Error: service_data must be a JSON object."
        if entity_id and entity_id.strip():
            resolved_entity_id = _resolve_entity_id(entity_id.strip(), domain.strip().lower())
            data.setdefault("entity_id", resolved_entity_id)

        path = f"/api/services/{domain.strip().lower()}/{service.strip()}"
        result = _ha_request("POST", path, data, query={"return_response": "" if return_response else None})
        service_response = None
        if isinstance(result, dict):
            changed = result.get("changed_states") if isinstance(result.get("changed_states"), list) else []
            service_response = result.get("service_response")
        else:
            changed = result if isinstance(result, list) else []
        lines = [f"Called Home Assistant service {domain}.{service}."]
        if entity_id:
            lines.append(f"Entity: {data.get('entity_id', entity_id.strip())}")
        if changed:
            lines.append(f"Changed states: {len(changed)}")
            for entity in changed[:10]:
                if isinstance(entity, dict) and entity.get("entity_id"):
                    lines.append(f"- {_entity_display(entity)}")
        if service_response is not None:
            response_text = json.dumps(service_response, indent=2, default=str)
            if len(response_text) > 2000:
                response_text = response_text[:2000] + "\n..."
            lines.append("Service response:")
            lines.append(response_text)
        return "\n".join(lines)
    except Exception as e:
        return f"Error in call_home_assistant_service: {str(e)}"


def turn_on_home_assistant_entity(entity_id: str) -> str:
    """Turn on a controllable Home Assistant entity or alias.

    Args:
        entity_id: Full HA entity ID or saved alias, e.g. "light.office_lamp" or "tv".

    Returns:
        Confirmation from Home Assistant.

    Ack: Turning on Home Assistant entity...
    """
    resolved = _resolve_entity_id(entity_id)
    domain = _entity_domain(resolved)
    return call_home_assistant_service(domain, "turn_on", entity_id=resolved)


def turn_off_home_assistant_entity(entity_id: str) -> str:
    """Turn off a controllable Home Assistant entity or alias.

    Args:
        entity_id: Full HA entity ID or saved alias, e.g. "light.office_lamp" or "tv".

    Returns:
        Confirmation from Home Assistant.

    Ack: Turning off Home Assistant entity...
    """
    resolved = _resolve_entity_id(entity_id)
    domain = _entity_domain(resolved)
    return call_home_assistant_service(domain, "turn_off", entity_id=resolved)


def toggle_home_assistant_entity(entity_id: str) -> str:
    """Toggle a controllable Home Assistant entity or alias.

    Args:
        entity_id: Full HA entity ID or saved alias, e.g. "switch.christmas_lights" or "tv".

    Returns:
        Confirmation from Home Assistant.

    Ack: Toggling Home Assistant entity...
    """
    resolved = _resolve_entity_id(entity_id)
    domain = _entity_domain(resolved)
    return call_home_assistant_service(domain, "toggle", entity_id=resolved)


def set_home_assistant_light(
    entity_id: str,
    brightness_pct: int = 0,
    color_name: str = "",
) -> str:
    """Set a Home Assistant light's brightness and/or color by entity ID or alias.

    Args:
        entity_id: Light entity ID or saved alias, e.g. "light.office_lamp" or "office lamp".
        brightness_pct: Optional brightness percent 1-100. 0 leaves unchanged.
        color_name: Optional HA color name, e.g. "red", "blue", "warm white".

    Returns:
        Confirmation from Home Assistant.

    Ack: Setting Home Assistant light...
    """
    data = {"entity_id": _resolve_entity_id(entity_id.strip(), "light")}
    if brightness_pct and brightness_pct > 0:
        data["brightness_pct"] = max(1, min(int(brightness_pct), 100))
    if color_name and color_name.strip():
        data["color_name"] = color_name.strip()
    return call_home_assistant_service("light", "turn_on", service_data=json.dumps(data))


def find_home_assistant_low_batteries(threshold: int = 25) -> str:
    """Find Home Assistant battery sensors that are low or need replacement.

    Args:
        threshold: Battery percentage threshold. Default 25.

    Returns:
        Battery entities at or below the threshold, plus unavailable battery entities.

    Ack: Checking Home Assistant batteries...
    """
    try:
        cutoff = max(1, min(int(threshold), 100))
        entities = _ha_states()
        low = []
        unavailable = []
        for entity in entities:
            entity_id = str(entity.get("entity_id") or "")
            attrs = entity.get("attributes") or {}
            device_class = str(attrs.get("device_class") or "").lower()
            friendly = str(attrs.get("friendly_name") or "").lower()
            is_battery = (
                device_class == "battery"
                or "battery" in entity_id.lower()
                or "battery" in friendly
            )
            if not is_battery:
                continue
            state = str(entity.get("state") or "").strip().lower()
            if state in {"unknown", "unavailable"}:
                unavailable.append(entity)
                continue
            if state in {"on", "low", "detected", "problem"}:
                low.append((0.0, entity))
                continue
            if state in {"off", "ok", "normal", "clear"}:
                continue
            try:
                value = float(state)
            except ValueError:
                battery_level = attrs.get("battery_level")
                try:
                    value = float(battery_level)
                except (TypeError, ValueError):
                    continue
            if value <= cutoff:
                low.append((value, entity))

        low.sort(key=lambda item: item[0])
        if not low and not unavailable:
            return f"No Home Assistant battery sensors are at or below {cutoff}%."

        lines = [f"Home Assistant battery check (threshold {cutoff}%):"]
        if low:
            lines.append("\nLow batteries:")
            for value, entity in low:
                lines.append(f"- {_entity_display(entity)}")
        if unavailable:
            lines.append("\nUnavailable battery sensors:")
            for entity in unavailable[:25]:
                lines.append(f"- {_entity_display(entity)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error in find_home_assistant_low_batteries: {str(e)}"
