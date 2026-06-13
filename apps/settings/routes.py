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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app_platform.auth import enforce_admin, require_user
from app_platform import config as platform_config
from app_platform import settings as platform_settings
from app_platform import secrets as platform_secrets

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Platform panels — curated settings that aren't owned by a single app.
# Stored in scope="platform". App settings are authoritative (no .env
# fallback). ``secret`` fields are encrypted at rest and never sent to client.
# ---------------------------------------------------------------------------

PLATFORM_PANELS: dict[str, dict] = {
    "system": {
        "name": "System",
        "description": "Platform-wide behavior — AI models, URLs, display + debug flags.",
        "schema": [
            {"key": "timezone", "type": "string", "label": "Timezone",
             "description": "Used everywhere times are shown. Stored as the IANA name.",
             "default": "", "choices_provider": "timezones"},
            {"key": "default_zip", "type": "string", "label": "Default ZIP code",
             "description": "US ZIP used for weather when none is given. Chat, Discord, and voice all use it by default.",
             "default": ""},
            {"key": "smart_model", "type": "string", "label": "Smart model",
             "description": "Model for complex reasoning.", "default": "", "requires_restart": True},
            {"key": "dumb_model", "type": "string", "label": "Fast model",
             "description": "Cheaper model for light tasks.", "default": "", "requires_restart": True},
            {"key": "realtime_model", "type": "string", "label": "Realtime/voice model",
             "description": "Model used by the voice path.", "default": ""},
            {"key": "embedding_model", "type": "string", "label": "Embedding model",
             "description": "OpenAI model for semantic search (memories + documents). Changing it requires a restart AND re-embedding existing content (vector dimension is fixed).",
             "default": "", "requires_restart": True},
            {"key": "lan_url", "type": "string", "label": "LAN URL",
             "description": "How devices on your network reach this server, e.g. http://skipper.local:8000.", "default": ""},
            {"key": "public_url", "type": "string", "label": "Public URL",
             "description": "External URL if exposed (for links/QR). Leave blank if LAN-only.", "default": ""},
            {"key": "show_entity_ids", "type": "boolean", "label": "Show entity IDs",
             "description": "Surface internal IDs in the UI (debugging).", "default": True,
             "requires_restart": True},
            {"key": "debug_tokens", "type": "boolean", "label": "Log token usage",
             "description": "Verbose token accounting in logs.", "default": True,
             "requires_restart": True},
            {"key": "max_session_turns", "type": "integer", "label": "Max session turns",
             "description": "Chat history cap per session before trimming.", "default": None},
        ],
    },
    "integrations": {
        "name": "Integrations",
        "description": "Cross-cutting service credentials with no single owning app. Secrets are encrypted at rest.",
        "schema": [
            {"key": "discord_enabled", "type": "boolean", "label": "Discord enabled",
             "description": "Turn the Discord chat bridge on/off.", "default": False,
             "requires_restart": True},
            {"key": "discord_token", "type": "string", "secret": True, "label": "Discord bot token",
             "description": "From the Discord developer portal.", "default": "",
             "requires_restart": True},
            {"key": "discord_allowed_channels", "type": "string", "label": "Discord allowed channels",
             "description": "Optional. Channel IDs (comma- or space-separated) where Skipper replies "
                            "WITHOUT being mentioned. Leave blank for DM-only — direct messages always "
                            "work. Map each person's Discord ID under Members.", "default": "",
             "requires_restart": True},
            {"key": "brave_api_key", "type": "string", "secret": True, "label": "Brave Search API key",
             "description": "Powers web search / research.", "default": ""},
            {"key": "openai_admin_key", "type": "string", "secret": True, "label": "OpenAI admin key",
             "description": "Optional — enables the OpenAI cost dashboard.", "default": ""},
            {"key": "default_printer", "type": "string", "label": "Default printer",
             "description": "Where Skipper prints. For a network printer use its IPP URL "
                            "(e.g. ipp://printer.local:631/ipp/print) — works on any OS, no setup. "
                            "Or a local printer name (CUPS queue on macOS/Linux/Docker; Windows "
                            "printer name via Ghostscript). Blank = the host's default printer.",
             "default": ""},
        ],
    },
}


def _timezone_choices() -> list[dict]:
    """All IANA timezones as ``{value, label}`` pairs, label showing the zone's
    current UTC offset (DST-aware), sorted by offset then name. The stored value
    is the bare IANA name; the offset is display-only."""
    from datetime import datetime
    from zoneinfo import ZoneInfo, available_timezones
    out = []
    for name in available_timezones():
        try:
            off = datetime.now(ZoneInfo(name)).utcoffset()
        except Exception:
            continue
        minutes = int(off.total_seconds() // 60) if off else 0
        sign = "+" if minutes >= 0 else "-"
        am = abs(minutes)
        out.append({"value": name, "label": f"{name} (UTC{sign}{am // 60:02d}:{am % 60:02d})",
                    "_off": minutes})
    out.sort(key=lambda z: (z["_off"], z["value"]))
    return [{"value": z["value"], "label": z["label"]} for z in out]


def _resolve_choices(f: dict) -> list:
    """Static ``choices`` list, or a dynamically-generated one named by
    ``choices_provider`` (e.g. the full timezone list)."""
    if f.get("choices_provider") == "timezones":
        return _timezone_choices()
    return list(f.get("choices", []) or [])


def _panel_field_json(f: dict, *, include_set: bool) -> dict:
    out = {
        "key": f["key"], "type": f.get("type", "string"),
        "label": f.get("label", f["key"]), "description": f.get("description", ""),
        "secret": bool(f.get("secret", False)),
        "default": f.get("default"), "choices": _resolve_choices(f),
        "requires_restart": bool(f.get("requires_restart", False)),
    }
    if include_set and out["secret"]:
        out["set"] = platform_settings.is_configured(f["key"], scope="platform")
    return out


def _panel_payload(panel_id: str) -> dict | None:
    panel = PLATFORM_PANELS.get(panel_id)
    if not panel:
        return None
    schema, values = [], {}
    for f in panel["schema"]:
        schema.append(_panel_field_json(f, include_set=True))
        if f.get("secret"):
            values[f["key"]] = ""   # never expose a secret to the client
        else:
            values[f["key"]] = platform_settings.get(
                f["key"], scope="platform", default=f.get("default"))
    return {
        "id": panel_id, "name": panel["name"], "description": panel["description"],
        "schema": schema, "values": values, "has_settings": True, "is_panel": True,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialise_config_key(ck, *, scope: str | None = None) -> dict:
    """Convert a ``ConfigKeyDef`` to a JSON-safe dict.

    For secret keys, includes a ``set`` flag (is a value stored?) so the UI
    can show "saved" without the value ever leaving the server.
    """
    out = {
        "key": ck.key,
        "type": ck.type,
        "default": ck.default,
        "label": ck.label,
        "description": ck.description,
        "secret": bool(getattr(ck, "secret", False)),
        "choices": list(getattr(ck, "choices", []) or []),
        "requires_restart": bool(getattr(ck, "requires_restart", False)),
    }
    if out["secret"] and scope:
        out["set"] = platform_settings.is_configured(ck.key, scope=scope)
    return out


def _current_values(app_id: str, schema: list) -> dict[str, Any]:
    """Return the current value for every key in the schema.

    Secret values are NEVER returned (blanked); the ``set`` flag on the
    schema entry says whether one is stored. Non-secret values fall back to
    the manifest ``default`` when never written.
    """
    scope = f"app:{app_id}"
    out: dict[str, Any] = {}
    for ck in schema:
        if getattr(ck, "secret", False):
            out[ck.key] = ""
        else:
            out[ck.key] = platform_config.get(ck.key, ck.default, scope=scope)
    return out


def _loaded_apps_sorted() -> list:
    """Return every loaded app (except this Settings app itself), ordered by id
    for a stable sidebar. Settings aggregates other apps' panels — rendering
    itself in that list is recursive and has nothing to configure."""
    from app_platform.loader import get_loaded_apps
    return sorted(
        (m for m in get_loaded_apps().values() if m.id != "settings"),
        key=lambda m: m.id,
    )


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
            schema = [_serialise_config_key(ck, scope=f"app:{m.id}") for ck in m.config]
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
            "schema": [_serialise_config_key(ck, scope=f"app:{app_id}") for ck in m.config],
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
async def api_patch_app_settings(app_id: str, req: AppSettingsPatch, request: Request):
    """Patch one or more keys for an app (admin-only when auth is enforced).

    The manifest's ``config:`` block is the schema contract —
    unknown keys are rejected with 400.
    """
    enforce_admin(request)
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
        secret_keys = {ck.key for ck in m.config if getattr(ck, "secret", False)}
        for key, value in req.values.items():
            if key in secret_keys:
                # Blank means "keep the existing secret" (GET never sends it).
                if value in (None, ""):
                    continue
                platform_settings.set(key, value, scope=scope, secret=True, by="settings-ui")
            else:
                platform_config.set(key, value, scope=scope, by="settings-ui")

        return ({
            "id": m.id,
            "name": m.name,
            "schema": [_serialise_config_key(ck, scope=scope) for ck in m.config],
            "values": _current_values(m.id, m.config),
            "has_settings": True,
        }, None)

    try:
        result, err = await asyncio.to_thread(_do)
    except platform_secrets.SecretKeyMissing as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
async def api_get_platform_settings(request: Request):
    """Return every key currently in ``scope='platform'`` (admin-only when
    auth is enforced).

    No schema — the agent's startup code is the consumer, so we
    expose raw key/value pairs.
    """
    enforce_admin(request)
    def _do():
        return {
            "scope": "platform",
            "values": platform_config.list_keys(scope="platform"),
        }
    return await asyncio.to_thread(_do)


class PlatformSettingsPatch(BaseModel):
    values: dict[str, Any]


@router.patch("/platform")
async def api_patch_platform_settings(req: PlatformSettingsPatch, request: Request):
    """Patch platform-scope keys (admin-only when auth is enforced)."""
    enforce_admin(request)
    if not req.values:
        raise HTTPException(status_code=400, detail="No values provided")

    def _do():
        for key, value in req.values.items():
            platform_config.set(key, value, scope="platform", by="settings-ui")
        # Invalidate in-process caches for keys that are cached by
        # app_platform services. Currently just the timezone — extend
        # this list when other platform settings start being cached.
        if "timezone" in req.values:
            from app_platform.time import invalidate_platform_timezone_cache
            invalidate_platform_timezone_cache()
        return {
            "scope": "platform",
            "values": platform_config.list_keys(scope="platform"),
        }

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# Platform panels (System, Integrations) — schema-driven, like app settings
# ---------------------------------------------------------------------------

@router.get("/panels")
async def api_list_panels():
    """List the curated platform panels (System, Integrations) with values."""
    def _do():
        return {"panels": [_panel_payload(pid) for pid in PLATFORM_PANELS]}
    return await asyncio.to_thread(_do)


@router.get("/panels/{panel_id}")
async def api_get_panel(panel_id: str):
    payload = await asyncio.to_thread(_panel_payload, panel_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Unknown panel '{panel_id}'")
    return payload


@router.patch("/panels/{panel_id}")
async def api_patch_panel(panel_id: str, req: PlatformSettingsPatch, request: Request):
    """Save panel values (admin-only when auth is enforced). Secrets are
    encrypted; blank secret = leave unchanged."""
    enforce_admin(request)
    panel = PLATFORM_PANELS.get(panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail=f"Unknown panel '{panel_id}'")
    if not req.values:
        raise HTTPException(status_code=400, detail="No values provided")

    by_key = {f["key"]: f for f in panel["schema"]}
    unknown = sorted(set(req.values) - set(by_key))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown keys for '{panel_id}': {unknown}")

    def _do():
        for key, value in req.values.items():
            f = by_key[key]
            if f.get("secret"):
                # Blank means "keep the existing secret" (the GET never sent it).
                if value in (None, ""):
                    continue
                platform_settings.set(key, value, scope="platform", secret=True, by="settings-ui")
            else:
                platform_settings.set(key, value, scope="platform", secret=False, by="settings-ui")
        if "timezone" in req.values:
            from app_platform.time import invalidate_platform_timezone_cache
            invalidate_platform_timezone_cache()
        return _panel_payload(panel_id)

    try:
        return await asyncio.to_thread(_do)
    except platform_secrets.SecretKeyMissing as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# My account — self-service per-user fields (NOT admin-gated; every signed-in
# user edits their OWN record). Currently: the Discord ID that links a Discord
# account to this Skipper user so the bot recognises them and can DM them.
# ---------------------------------------------------------------------------

class AccountPatch(BaseModel):
    discord_id: str | None = None


def _account_payload(name: str) -> dict:
    from data_layer.users import get_user
    u = get_user(name)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "name": u["name"],
        "display_name": u.get("display_name") or u["name"],
        "discord_id": u.get("discord_id") or "",
    }


@router.get("/account")
async def api_get_account(request: Request):
    """The signed-in user's own editable account fields."""
    name = require_user(request)["name"]
    return await asyncio.to_thread(_account_payload, name)


@router.patch("/account")
async def api_patch_account(req: AccountPatch, request: Request):
    """Update the signed-in user's own account fields (self-service).

    Discord ID: a numeric snowflake (17–20 digits), or blank to unlink. A given
    Discord ID maps to exactly one Skipper user, so linking one already claimed
    by someone else is rejected.
    """
    name = require_user(request)["name"]
    raw = (req.discord_id or "").strip()
    if raw and (not raw.isdigit() or not (17 <= len(raw) <= 20)):
        raise HTTPException(
            status_code=400,
            detail=("Discord ID must be the numeric user ID (17–20 digits). In "
                    "Discord enable Developer Mode (User Settings → Advanced), "
                    "then right-click your name → Copy User ID."),
        )

    def _do():
        from data_layer.users import get_user_by_discord_id, update_discord_id
        if raw:
            other = get_user_by_discord_id(raw)
            if other and other["name"] != name:
                raise HTTPException(
                    status_code=409,
                    detail=f"That Discord ID is already linked to another user (@{other['name']}).",
                )
        if not update_discord_id(name, raw or None):
            raise HTTPException(status_code=404, detail="User not found")
        return _account_payload(name)

    return await asyncio.to_thread(_do)
