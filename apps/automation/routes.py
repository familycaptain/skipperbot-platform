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
