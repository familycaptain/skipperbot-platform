"""Automation — REST API (Home Assistant control). Mounted at /api/apps/automation.

Thin JSON layer over the same helpers the chat tools use (tools.py). Every
endpoint degrades gracefully when Home Assistant isn't configured — the UI
shows a setup card instead of erroring.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from . import tools as _t
from . import devices as _dev

router = APIRouter()

# Domains the dashboard shows as on/off toggles (lights also get brightness).
TOGGLEABLE = {"light", "switch", "fan", "input_boolean"}
# Domains worth surfacing read-only (state shown, no control).
READONLY = {"sensor", "binary_sensor", "climate", "media_player", "cover", "lock"}


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _shape(e: dict) -> dict:
    attrs = e.get("attributes") or {}
    eid = e.get("entity_id", "")
    dom = _domain(eid)
    out = {
        "entity_id": eid,
        "domain": dom,
        "name": attrs.get("friendly_name") or eid,
        "state": e.get("state", ""),
        "toggleable": dom in TOGGLEABLE,
        "on": str(e.get("state", "")).lower() in ("on", "open", "playing", "home", "unlocked"),
    }
    if dom == "light":
        b = attrs.get("brightness")
        if isinstance(b, (int, float)):
            out["brightness_pct"] = round(b / 255 * 100)
    unit = attrs.get("unit_of_measurement")
    if unit:
        out["unit"] = unit
    return out


@router.get("/status")
async def api_status():
    """Is Home Assistant configured + reachable?"""
    err = _t._ha_setup_error()
    if err:
        return {"configured": False, "connected": False, "message": err}

    def _ping():
        try:
            _t._ha_states()
            return True, ""
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    connected, msg = await asyncio.to_thread(_ping)
    return {"configured": True, "connected": connected, "message": msg}


@router.get("/entities")
async def api_entities():
    """Controllable + notable entities, grouped for the dashboard."""
    err = _t._ha_setup_error()
    if err:
        return {"configured": False, "groups": {}, "message": err}

    def _load():
        states = _t._ha_states()
        items = [_shape(e) for e in states if _domain(e.get("entity_id", "")) in (TOGGLEABLE | READONLY)]
        items.sort(key=lambda x: (x["domain"], x["name"].lower()))
        groups: dict[str, list] = {}
        for it in items:
            groups.setdefault(it["domain"], []).append(it)
        return groups

    try:
        groups = await asyncio.to_thread(_load)
        return {"configured": True, "groups": groups}
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "groups": {}, "message": str(exc)}


class ControlIn(BaseModel):
    entity_id: str
    action: str = "toggle"        # on | off | toggle
    brightness_pct: int | None = None


@router.post("/control")
async def api_control(body: ControlIn):
    """Turn an entity on/off/toggle (brightness_pct for lights on 'on')."""
    err = _t._ha_setup_error()
    if err:
        return {"ok": False, "error": err}
    dom = _domain(body.entity_id)
    if dom not in TOGGLEABLE:
        return {"ok": False, "error": f"{dom or 'entity'} is not controllable from the dashboard"}
    action = (body.action or "toggle").lower()
    service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(action)
    if not service:
        return {"ok": False, "error": f"unknown action '{action}'"}

    data: dict = {"entity_id": body.entity_id}
    if dom == "light" and service == "turn_on" and body.brightness_pct is not None:
        data["brightness_pct"] = max(0, min(int(body.brightness_pct), 100))

    def _call():
        _t._ha_request("POST", f"/api/services/{dom}/{service}", data)
        # read back the fresh state
        for e in _t._ha_states():
            if e.get("entity_id") == body.entity_id:
                return _shape(e)
        return None

    try:
        entity = await asyncio.to_thread(_call)
        return {"ok": True, "entity": entity}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ===========================================================================
# Names management — devices + aliases (the "Names" tab; mirrors the chat tools)
# ===========================================================================

@router.get("/all-entities")
async def api_all_entities():
    """Lightweight {entity_id, name} list across all domains, for the alias picker."""
    if _t._ha_setup_error():
        return {"entities": []}

    def _load():
        out = []
        for e in _t._ha_states():
            eid = e.get("entity_id", "")
            if not eid:
                continue
            attrs = e.get("attributes") or {}
            out.append({"entity_id": eid, "name": attrs.get("friendly_name") or eid})
        out.sort(key=lambda x: x["entity_id"])
        return out

    try:
        return {"entities": await asyncio.to_thread(_load)}
    except Exception as exc:  # noqa: BLE001
        return {"entities": [], "message": str(exc)}


@router.get("/aliases")
async def api_list_aliases():
    """Trained entity aliases (was aliases.json; now app_automation.ha_aliases)."""
    aliases = await asyncio.to_thread(_t._load_aliases)
    return {"aliases": [
        {"alias": a, "entity_id": d.get("entity_id", ""), "notes": d.get("notes", "")}
        for a, d in sorted(aliases.items())
    ]}


class AliasIn(BaseModel):
    alias: str
    entity_id: str
    notes: str = ""


@router.post("/aliases")
async def api_add_alias(body: AliasIn):
    """Add/update an alias. Reuses the same validation as the chat tool."""
    msg = await asyncio.to_thread(
        _t.add_home_assistant_alias, body.alias, body.entity_id, body.notes
    )
    return {"ok": not msg.lower().startswith("error"), "message": msg}


@router.delete("/aliases/{alias}")
async def api_delete_alias(alias: str):
    msg = await asyncio.to_thread(_t.delete_home_assistant_alias, alias)
    return {"ok": True, "message": msg}


class AliasEditIn(BaseModel):
    alias: str
    entity_id: str
    notes: str = ""


@router.put("/aliases/{old_alias}")
async def api_edit_alias(old_alias: str, body: AliasEditIn):
    """Edit an existing alias — including renaming it. Atomic: if the alias key
    changes, the old key is dropped and the new one written in one save."""
    def _do():
        old_key = _t._normalize_name(old_alias)
        new_key = _t._normalize_name(body.alias)
        entity = (body.entity_id or "").strip()
        if not new_key:
            return False, "Error: alias is required."
        if "." not in entity:
            return False, "Error: entity_id must be a full Home Assistant entity ID."
        aliases = _t._load_aliases()
        if old_key != new_key:
            aliases.pop(old_key, None)
        aliases[new_key] = {"entity_id": entity, "notes": (body.notes or "").strip()}
        _t._save_aliases(aliases)
        return True, f"Updated alias '{new_key}' -> {entity}."

    ok, msg = await asyncio.to_thread(_do)
    return {"ok": ok, "message": msg}


@router.get("/devices")
async def api_list_devices():
    """Cached HA device registry (app_automation.ha_devices) with their aliases."""
    devices = await asyncio.to_thread(_dev.load_cached)
    return {"devices": [
        {
            "device_id": did,
            "name": d.get("name", ""),
            "manufacturer": d.get("manufacturer", ""),
            "model": d.get("model", ""),
            "aliases": d.get("aliases") or [],
        }
        for did, d in sorted(devices.items(), key=lambda kv: (kv[1].get("name") or "").lower())
    ]}


class DeviceAliasesIn(BaseModel):
    aliases: list[str]


@router.put("/devices/{device_id}/aliases")
async def api_set_device_aliases(device_id: str, body: DeviceAliasesIn):
    """Replace one device's hand-curated aliases."""
    ok = await asyncio.to_thread(_dev.set_device_aliases, device_id, body.aliases)
    return {"ok": bool(ok)}
