"""Settings — FastAPI routes.

Mounted by the platform loader at ``/api/apps/settings``. The Settings
app discovers every loaded app's ``config:`` schema at runtime via
``app_platform.loader.get_loaded_apps()`` and round-trips values
through ``app_platform.config``.

Endpoints::

    GET    /apps                  — list every loaded app + schema + values
    GET    /apps/{app_id}         — single app's schema + values
    PATCH  /apps/{app_id}         — patch one or more keys
                                    body: {"values": {key: value, ...}}
    GET    /platform              — every key in scope='platform'
    PATCH  /platform              — patch platform-scope keys (no schema gate)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app_platform import config as platform_config

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialise_config_key(ck) -> dict:
    """Convert a ``ConfigKeyDef`` to a JSON-safe dict.

    Defaults are passed through unchanged — the config layer stores
    JSONB and does no coercion.
    """
    return {
        "key": ck.key,
        "type": ck.type,
        "default": ck.default,
        "label": ck.label,
        "description": ck.description,
        "secret": bool(getattr(ck, "secret", False)),
        "choices": list(getattr(ck, "choices", []) or []),
    }


def _current_values(app_id: str, schema: list) -> dict[str, Any]:
    """Return the current value for every key in the schema.

    Falls back to the manifest ``default`` when a key has never been
    written so first-boot installs surface the documented defaults
    rather than ``null``.
    """
    scope = f"app:{app_id}"
    out: dict[str, Any] = {}
    for ck in schema:
        out[ck.key] = platform_config.get(ck.key, ck.default, scope=scope)
    return out


def _loaded_apps_sorted() -> list:
    """Return every loaded app, ordered by id for a stable sidebar."""
    from app_platform.loader import get_loaded_apps
    return sorted(get_loaded_apps().values(), key=lambda m: m.id)


# ---------------------------------------------------------------------------
# Per-app settings
# ---------------------------------------------------------------------------

@router.get("/apps")
async def api_list_app_settings():
    """List every loaded app with its schema and current values.

    Apps without a declared ``config:`` block are still returned —
    they get ``schema: []`` — so the user can see they're
    installed but intentionally not configurable.
    """
    def _do():
        apps = []
        for m in _loaded_apps_sorted():
            schema = [_serialise_config_key(ck) for ck in m.config]
            values = _current_values(m.id, m.config) if m.config else {}
            apps.append({
                "id": m.id,
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "schema": schema,
                "values": values,
                "has_settings": bool(m.config),
            })
        return {"apps": apps, "count": len(apps)}

    return await asyncio.to_thread(_do)


@router.get("/apps/{app_id}")
async def api_get_app_settings(app_id: str):
    """Return one app's schema + current values."""
    def _do():
        from app_platform.loader import get_loaded_apps
        loaded = get_loaded_apps()
        m = loaded.get(app_id)
        if not m:
            return None
        return {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "version": m.version,
            "schema": [_serialise_config_key(ck) for ck in m.config],
            "values": _current_values(m.id, m.config),
            "has_settings": bool(m.config),
        }

    result = await asyncio.to_thread(_do)
    if result is None:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' is not loaded")
    return result


class AppSettingsPatch(BaseModel):
    values: dict[str, Any]


@router.patch("/apps/{app_id}")
async def api_patch_app_settings(app_id: str, req: AppSettingsPatch):
    """Patch one or more keys for an app.

    The manifest's ``config:`` block is the schema contract —
    unknown keys are rejected with 400.
    """
    if not req.values:
        raise HTTPException(status_code=400, detail="No values provided")

    def _do():
        from app_platform.loader import get_loaded_apps
        loaded = get_loaded_apps()
        m = loaded.get(app_id)
        if not m:
            return None, f"App '{app_id}' is not loaded"

        known = {ck.key for ck in m.config}
        unknown = sorted(set(req.values) - known)
        if unknown:
            return None, (
                f"Unknown config keys for app '{app_id}': {unknown}. "
                f"Valid keys: {sorted(known)}"
            )

        scope = f"app:{app_id}"
        for key, value in req.values.items():
            platform_config.set(key, value, scope=scope, by="settings-ui")

        return ({
            "id": m.id,
            "name": m.name,
            "schema": [_serialise_config_key(ck) for ck in m.config],
            "values": _current_values(m.id, m.config),
            "has_settings": True,
        }, None)

    result, err = await asyncio.to_thread(_do)
    if result is None:
        raise HTTPException(
            status_code=400 if (err and "Unknown" in err) else 404,
            detail=err or "App not loaded",
        )
    return result


# ---------------------------------------------------------------------------
# Platform-scope settings
# ---------------------------------------------------------------------------

@router.get("/platform")
async def api_get_platform_settings():
    """Return every key currently in ``scope='platform'``.

    No schema — the agent's startup code is the consumer, so we
    expose raw key/value pairs.
    """
    def _do():
        return {
            "scope": "platform",
            "values": platform_config.list_keys(scope="platform"),
        }
    return await asyncio.to_thread(_do)


class PlatformSettingsPatch(BaseModel):
    values: dict[str, Any]


@router.patch("/platform")
async def api_patch_platform_settings(req: PlatformSettingsPatch):
    """Patch platform-scope keys. No schema gate — the caller is
    trusted to know which keys the platform reads.
    """
    if not req.values:
        raise HTTPException(status_code=400, detail="No values provided")

    def _do():
        for key, value in req.values.items():
            platform_config.set(key, value, scope="platform", by="settings-ui")
        return {
            "scope": "platform",
            "values": platform_config.list_keys(scope="platform"),
        }

    return await asyncio.to_thread(_do)
