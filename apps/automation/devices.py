"""Home Assistant device + entity registry cache.

Two layers, kept separate on purpose:

1. **devices.json** — a small, mostly-hand-curated alias dictionary that
   maps a device_id to its display name + the friendly aliases the user
   says in voice chat ("tv" → LG webOS TV OLED65C2PU). It changes only
   when you add/remove physical devices or rename them. Hand-edited
   aliases are preserved across refreshes.

2. **In-memory device→entities mapping** — refreshed alongside devices.json
   on the hourly cycle. Used by the `find_home_device` tool to return the
   list of entities for a given device WITHOUT making a fresh WS roundtrip
   every voice query. Entity *state values* are NEVER cached — those come
   from HA live via the existing `/api/states/<entity_id>` calls.

The HA REST API does not expose device-level info; only the WebSocket API
does. That's why this module is the only WebSocket consumer in the app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from threading import Lock

import websockets

logger = logging.getLogger(__name__)

DEVICES_PATH = Path(__file__).with_name("devices.json")

# In-memory mapping: device_id -> [{entity_id, name, device_class, domain, ...}]
# Populated by fetch_and_save(); read by find_device / get_entities_for_device.
_entities_by_device: dict[str, list[dict]] = {}
_entities_lock = Lock()


# ---------------------------------------------------------------------------
# HA connection helpers
# ---------------------------------------------------------------------------

def _ha_base_url() -> str:
    from app_platform import settings as _settings
    raw = (_settings.get("home_assistant_url", scope="app:automation", default="") or "").strip().rstrip("/")
    if raw.endswith("/api"):
        raw = raw[:-4]
    return raw


def _ha_token() -> str:
    from app_platform import settings as _settings
    return (_settings.get("home_assistant_token", scope="app:automation", secret=True, default="") or "").strip()


def _ws_url() -> str:
    base = _ha_base_url()
    if not base:
        return ""
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/api/websocket"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/api/websocket"
    return base + "/api/websocket"


# ---------------------------------------------------------------------------
# WebSocket fetch
# ---------------------------------------------------------------------------

async def _fetch_registries() -> tuple[list[dict], list[dict]]:
    """Open a WS connection to HA and pull both registries in one session."""
    url = _ws_url()
    token = _ha_token()
    if not url:
        raise RuntimeError("HOME_ASSISTANT_URL is not set")
    if not token:
        raise RuntimeError("HOME_ASSISTANT_TOKEN is not set")

    async with websockets.connect(url, max_size=20 * 1024 * 1024, open_timeout=10) as ws:
        # Auth handshake
        first = json.loads(await ws.recv())
        if first.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected first WS message: {first}")
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        ack = json.loads(await ws.recv())
        if ack.get("type") != "auth_ok":
            raise RuntimeError(f"HA WebSocket auth failed: {ack}")

        # device_registry/list
        await ws.send(json.dumps({"id": 1, "type": "config/device_registry/list"}))
        dev_resp = json.loads(await ws.recv())
        if not dev_resp.get("success"):
            raise RuntimeError(f"device_registry/list failed: {dev_resp}")
        devices = dev_resp.get("result") or []

        # entity_registry/list
        await ws.send(json.dumps({"id": 2, "type": "config/entity_registry/list"}))
        ent_resp = json.loads(await ws.recv())
        if not ent_resp.get("success"):
            raise RuntimeError(f"entity_registry/list failed: {ent_resp}")
        entities = ent_resp.get("result") or []

    return devices, entities


# ---------------------------------------------------------------------------
# Merge + persist
# ---------------------------------------------------------------------------

def _device_name(d: dict) -> str:
    """User-set name takes precedence over the auto-detected name."""
    return (d.get("name_by_user") or d.get("name") or "").strip()


def _normalize(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _build_entities_by_device(devices: list[dict], entities: list[dict]) -> dict[str, list[dict]]:
    """Build the in-memory device→entities mapping. Skips devices with no entities."""
    valid_device_ids = {d.get("id") for d in devices if d.get("id")}
    out: dict[str, list[dict]] = {}
    for e in entities:
        did = e.get("device_id")
        if not did or did not in valid_device_ids:
            continue
        if e.get("disabled_by") or e.get("hidden_by"):
            continue
        entity_id = e.get("entity_id") or ""
        out.setdefault(did, []).append({
            "entity_id": entity_id,
            "name": (e.get("name") or e.get("original_name") or "").strip(),
            "device_class": (e.get("device_class") or e.get("original_device_class") or "").strip(),
            "domain": entity_id.split(".", 1)[0] if "." in entity_id else "",
            "unit_of_measurement": (e.get("unit_of_measurement") or "").strip(),
        })
    return out


def _build_device_aliases(
    devices: list[dict],
    existing: dict[str, dict],
    entity_owners: set[str],
) -> dict[str, dict]:
    """Build the slim devices.json content.

    Preserves any hand-edited aliases for devices that already exist in
    `existing`. New devices get an entry with their normalized name as the
    sole default alias. Devices with no entities are dropped — they're not
    useful for voice queries.
    """
    out: dict[str, dict] = {}
    for d in devices:
        did = d.get("id")
        if not did or did not in entity_owners:
            continue
        name = _device_name(d)
        prior = existing.get(did) or {}
        prior_aliases = prior.get("aliases") if isinstance(prior.get("aliases"), list) else None
        default_alias = _normalize(name)
        aliases = prior_aliases if prior_aliases else ([default_alias] if default_alias else [])
        out[did] = {
            "name": name,
            "manufacturer": (d.get("manufacturer") or "").strip(),
            "model": (d.get("model") or "").strip(),
            "aliases": aliases,
        }
    return out


def fetch_and_save() -> dict:
    """Pull both registries, refresh in-memory entity map, write devices.json.

    Hand-curated aliases in devices.json are PRESERVED — only new devices
    are added; existing entries are not overwritten.

    Returns the slim devices dict (the same shape that's written to disk).
    """
    devices, entities = asyncio.run(_fetch_registries())

    # Refresh in-memory entity map under lock
    new_entities_map = _build_entities_by_device(devices, entities)
    with _entities_lock:
        _entities_by_device.clear()
        _entities_by_device.update(new_entities_map)

    # Merge into devices.json, preserving any hand-edited aliases
    existing = load_cached()
    entity_owners = set(new_entities_map.keys())
    aliases = _build_device_aliases(devices, existing, entity_owners)
    DEVICES_PATH.write_text(
        json.dumps(aliases, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return aliases


def load_cached() -> dict:
    """Return the slim devices.json contents, or empty dict if missing."""
    try:
        return json.loads(DEVICES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def build_voice_alias_block() -> str:
    """Compact alias-only block injected into the automation voice prompt.

    The model needs to know which friendly names are valid HA targets — without
    this, it can't tell the difference between "outside" (a real sensor it
    can read) and "outside" (an interpretive phrase meaning outdoor weather).
    With it, the model recognizes a name is callable and reaches for a tool
    instead of fabricating an answer.

    Format intentionally minimal: one comma-separated line of aliases plus a
    one-paragraph reminder that the list is JUST names — the model still has
    to call tools to read state, control devices, or look up specifics.
    Measured at ~220 tokens against the current 51-alias devices.json.
    """
    devices = load_cached()
    if not devices:
        return ""

    aliases = sorted({
        a for d in devices.values()
        for a in (d.get("aliases") or [])
        if a
    })
    if not aliases:
        return ""

    alias_line = ", ".join(aliases)
    return (
        "\n## Home Assistant Aliases — Names You Can Call Tools With\n"
        "These are real, callable friendly names registered on the home's "
        "Home Assistant. Pass any of them directly to `get_home_assistant_entity`, "
        "`turn_on_home_assistant_entity`, `turn_off_home_assistant_entity`, "
        "`toggle_home_assistant_entity`, `set_home_assistant_light`, or "
        "`resolve_home_assistant_entity`.\n"
        f"{alias_line}\n"
        "\n"
        "This list is ONLY the names. It does not include current state, "
        "values, attributes, entity IDs, room, device class, or whether the "
        "thing is on/off/open/closed. For any of those, you MUST call the "
        "appropriate HA tool — do not guess or recite from training. "
        "If the user asks about something not in this list, search with "
        "`list_home_assistant_entities(query=\"...\")` before saying it "
        "doesn't exist.\n"
    )


# ---------------------------------------------------------------------------
# Lookup APIs (used by tools.py)
# ---------------------------------------------------------------------------

def find_device(name_or_alias: str) -> tuple[str, dict] | None:
    """Resolve a friendly name → (device_id, device_dict).

    Match priority:
      1. Exact alias (case- and punctuation-insensitive)
      2. Exact device-name match
      3. Substring match on alias OR device-name
    Returns None if no match.
    """
    if not name_or_alias:
        return None
    target = _normalize(name_or_alias)
    if not target:
        return None

    devices = load_cached()
    # Pass 1 + 2: exact match on aliases or name
    for did, d in devices.items():
        if _normalize(d.get("name", "")) == target:
            return (did, d)
        for alias in d.get("aliases") or []:
            if _normalize(alias) == target:
                return (did, d)
    # Pass 3: substring fallback
    for did, d in devices.items():
        haystack = _normalize(d.get("name", ""))
        if target in haystack or haystack in target:
            return (did, d)
        for alias in d.get("aliases") or []:
            if target in _normalize(alias):
                return (did, d)
    return None


def get_entities_for_device(device_id: str) -> list[dict]:
    """Return cached entity metadata (no state values) for one device."""
    with _entities_lock:
        return list(_entities_by_device.get(device_id, []))


def warm_entities_cache_if_empty() -> None:
    """If the in-memory entity map is empty (e.g. agent just started, refresh
    thread hasn't run yet), do a synchronous fetch to populate it."""
    with _entities_lock:
        already_warm = bool(_entities_by_device)
    if already_warm:
        return
    try:
        fetch_and_save()
    except Exception as exc:
        logger.warning("AUTOMATION: on-demand entity warm-up failed: %s", exc)
