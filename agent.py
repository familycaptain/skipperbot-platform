"""
SkipperBot Agent API
Thin FastAPI routing layer. All logic lives in dedicated modules.
"""

import sys
import os
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr, sys.stdin):
        if _stream and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import logger, discord_enabled
from connections import manager
import mcp_client
import tool_dispatch
from chat import process_chat
import discord_bot
from apps.reminders.scheduler import start_reminder_scheduler
from app_platform.jobs import start_dispatcher
from apps.jobs.runner import start_job_runner
from thinking_scheduler import start_thinking_scheduler
from job_handlers import register_all_handlers
from trello_sync import start_trello_sync
from memory_store import backfill_embeddings
from knowledge_store import migrate_chunk_embeddings
from data_layer.db import close_pool
from app_platform.loader import load_all_apps, get_app_tool_routes
from data_layer.users import authenticate, get_user, update_password, get_all_users, has_role, create_user, update_role, delete_user, parse_roles
from app_platform.auth import principal_from_request, principal_from_ws, ws_bearer_subprotocol, require_user, require_admin, resolve_target, scope_user
from app_platform.ratelimit import check_rate

# Minimum web password length (audit #31/#35).
MIN_PASSWORD_LEN = 8
from apps.goals import data as dl_goals
import app_platform.documents as doc_store
import link_registry

# Unique ID generated at agent startup — used to detect restarts on the client
BUILD_ID = str(int(time.time()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCP connection and (optionally) Discord bot on startup."""
    # Ensure the auth schema (service_tokens table + users.token_version column)
    # exists. Idempotent — lets existing deployments pick it up without a
    # baseline re-run; fresh installs already have it from 000_baseline.sql.
    try:
        from data_layer.service_tokens import ensure_auth_schema
        await asyncio.to_thread(ensure_auth_schema)
    except Exception as e:
        logger.error("STARTUP: ensure_auth_schema failed: %s", e)
    # chat_turns.tool_calls — added after the baseline; idempotent backfill so
    # existing installs persist tool calls without wiping the DB.
    try:
        from data_layer.chatlogs import ensure_chatlog_schema
        await asyncio.to_thread(ensure_chatlog_schema)
    except Exception as e:
        logger.error("STARTUP: ensure_chatlog_schema failed: %s", e)
    # One-time migrations: backfill memory embeddings + migrate knowledge to binary
    await asyncio.to_thread(backfill_embeddings)
    await asyncio.to_thread(migrate_chunk_embeddings)
    await mcp_client.connect_to_mcp()

    # Build direct-call tool registry (bypasses MCP subprocess for execution)
    await asyncio.to_thread(tool_dispatch.init)
    tool_dispatch.verify_against_mcp([t.name for t in mcp_client.mcp_tools])

    # Load app packages from apps/ directory
    # NOTE: called synchronously (not via asyncio.to_thread) because
    # include_router must run on the main thread for Starlette to pick
    # up the new routes before the server starts accepting requests.
    from pathlib import Path
    apps_dir = Path(__file__).parent / "apps"
    load_all_apps(apps_dir, app, None)

    # Move the SPA catch-all route (/{filename:path}) to the very end
    # so that app-package API routes added by include_router above
    # are matched before the catch-all serves index.html.
    for i, route in enumerate(app.routes):
        if hasattr(route, "path") and route.path == "/{filename:path}":
            app.routes.append(app.routes.pop(i))
            break

    discord_enabled_now = discord_enabled()
    discord_task = None
    if discord_enabled_now:
        discord_task = asyncio.create_task(discord_bot.start_discord_bot())
        await discord_bot.wait_until_ready()
        logger.info("STARTUP: Discord ready — starting background tasks")
    else:
        logger.info("STARTUP: Discord disabled (DISCORD_ENABLED=false) — starting background tasks")

    reminder_task = asyncio.create_task(start_reminder_scheduler())
    register_all_handlers()
    job_task = asyncio.create_task(start_dispatcher())
    job_runner_task = asyncio.create_task(start_job_runner())
    trello_task = asyncio.create_task(start_trello_sync())
    thinking_task = asyncio.create_task(start_thinking_scheduler())
    yield
    # Shutdown
    if discord_enabled_now:
        await discord_bot.stop_discord_bot()
        if discord_task:
            discord_task.cancel()
    reminder_task.cancel()
    job_task.cancel()
    job_runner_task.cancel()
    trello_task.cancel()
    thinking_task.cancel()
    # Cancel any in-flight timers so none fire after shutdown begins. Timers
    # ships bundled with the platform (apps/timers/); the import is wrapped only
    # as defensive cleanup in case the folder was deleted (in-memory timer tasks
    # would be cancelled by the loop on shutdown anyway).
    try:
        from apps.timers.scheduler import shutdown_all_timers
        await shutdown_all_timers()
    except Exception as e:
        logger.error("STARTUP: Timer shutdown failed: %s", e)
    close_pool()


app = FastAPI(title="SkipperBot Agent", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Authentication gate (see app_platform/auth.py). Verifies a bearer token,
# attaches request.state.principal, and rejects any unauthenticated request to a
# non-public path with 401. Enforcement is unconditional — there is no off switch.
# ---------------------------------------------------------------------------
_PUBLIC_EXACT = {"/", "/api/health", "/auth/login", "/auth/logout",
                 "/api/onboarding/status", "/api/onboarding/check-openai"}
_PUBLIC_PREFIXES = ("/assets/", "/static/", "/web/")


def _is_public_path(request: Request) -> bool:
    path = request.url.path
    if path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES):
        return True
    # SPA + static assets (anything that isn't an API/auth/ws/chat path).
    if not path.startswith(("/api/", "/auth/", "/ws", "/chat")):
        return True
    # First-run: allow creating the very first user only while none exist.
    if path == "/api/onboarding/create-user":
        try:
            return not any("bot" not in (u.get("role") or "") for u in get_all_users())
        except Exception:
            return False
    return False


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    try:
        request.state.principal = principal_from_request(request)
    except Exception:
        request.state.principal = None
    if request.state.principal is None and not _is_public_path(request):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


# CORS is added AFTER the auth gate so it remains the OUTERMOST middleware —
# that keeps CORS headers on 401 responses. Bearer tokens (not cookies) mean we
# don't need credentialed CORS; pin origins via SKIPPERBOT_ALLOWED_ORIGINS
# (comma-separated) or default to open (safe without credentials).
_allowed_origins = [o.strip() for o in os.getenv("SKIPPERBOT_ALLOWED_ORIGINS", "").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(Exception)
async def _generic_error_handler(request: Request, exc: Exception):
    """Don't leak internals (stack/str(e)) to clients on unhandled errors.

    Log the detail server-side; return a generic 500. HTTPException and
    handler-returned error payloads keep their own messages — this only catches
    exceptions that would otherwise surface str(exc) to the caller. (Audit #38.)
    """
    logger.error("Unhandled error on %s %s: %s",
                 request.method, request.url.path, exc, exc_info=True)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


class ChatRequest(BaseModel):
    message: str
    user_id: str


class ChatResponse(BaseModel):
    response: str
    user_id: str


class LoginRequest(BaseModel):
    username: str
    password: str = ""


@app.get("/api/health")
async def health():
    return {"status": "ok", "agent": "SkipperBot", "version": "0.1.0"}


@app.get("/")
async def root():
    index = Path(__file__).resolve().parent / "web" / "dist" / "index.html"
    if index.is_file():
        # no-cache: always revalidate the entry point so a new build is picked
        # up without a manual hard refresh (see the SPA serving block below).
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return {"status": "ok", "agent": "SkipperBot", "version": "0.1.0"}


# Returned to the client when we authenticated the user but could not mint a
# session token (the auth signing key is unavailable). Auth is unconditional, so
# a tokenless session is useless — surfacing a clear error keeps the client on
# the login/onboarding screen instead of saving a half-session that can only
# 401/403 (which previously left the desktop stuck on "Reconnecting").
_NO_SESSION_ERR = ("Could not establish a session: the server's auth signing "
                   "key is not configured. Set SKIPPERBOT_SECRET_KEY (or "
                   "SKIPPERBOT_AUTH_KEY) in .env and restart the agent.")


def _set_session_cookie(response: JSONResponse, token: str, http_request: Request) -> None:
    """Mirror the session token into the httpOnly ``sb_session`` cookie.

    Same token returned in the body; httpOnly + SameSite=Lax + Path=/ +
    Max-Age=SESSION_TTL. Secure is set IFF the request scheme is https (omitted on
    plain HTTP so self-hosters on http:// still receive the cookie). This is what
    lets top-level browser navigations / pop-out media windows authenticate without
    a header — the cookie is honored ONLY for safe methods (see
    principal_from_request). The token never appears in any URL or access log."""
    from app_platform.auth import SESSION_TTL
    response.set_cookie(
        key="sb_session",
        value=token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        path="/",
        secure=(http_request.url.scheme == "https"),
    )


def _issue_token(user: dict) -> str:
    """Mint a session token for a just-authenticated user.

    Returns "" if the auth key is unavailable (or minting otherwise fails);
    callers MUST treat an empty token as a hard failure and return
    ``_NO_SESSION_ERR`` rather than reporting success — a session with no token
    cannot make any authenticated request."""
    try:
        from app_platform.auth import mint_session_token
        # Re-fetch so token_version is included even if the passed dict predates it.
        fresh = get_user(user["name"]) or user
        return mint_session_token(fresh)
    except Exception as e:
        logger.warning("AUTH: could not mint session token for %s: %s",
                       user.get("name"), e)
        return ""


@app.post("/auth/login")
async def login(request: LoginRequest, http_request: Request):
    """Authenticate a web user. Returns canonical user_id + a session token."""
    name = request.username.lower().strip()
    # Throttle brute force: cap attempts per account (audit #31).
    wait = check_rate(f"login:{name}", max_events=10, window_seconds=300)
    if wait:
        return JSONResponse(
            {"ok": False, "error": f"Too many login attempts. Try again in ~{wait}s."},
            status_code=429,
        )
    user = await asyncio.to_thread(get_user, name)
    if not user:
        return {"ok": False, "error": "Unknown user."}
    if has_role(user, "bot"):
        return {"ok": False, "error": "Unknown user."}
    if not user.get("password_hash"):
        # User exists but has no password yet — prompt to set one
        return {"ok": False, "error": "no_password", "name": user["name"], "display_name": user["display_name"]}
    if not request.password:
        # User exists and has a password — tell frontend to show password field
        return {"ok": False, "error": "password_required", "name": user["name"], "display_name": user["display_name"]}
    authed = await asyncio.to_thread(authenticate, name, request.password)
    if not authed:
        return {"ok": False, "error": "Wrong password."}
    token = _issue_token(authed)
    if not token:
        return {"ok": False, "error": _NO_SESSION_ERR}
    response = JSONResponse({
        "ok": True,
        "user": {"name": authed["name"], "display_name": authed["display_name"], "role": authed["role"]},
        "token": token,
    })
    _set_session_cookie(response, token, http_request)
    return response


@app.get("/auth/logout")
async def logout(http_request: Request):
    """Clear the httpOnly ``sb_session`` cookie (public — reachable unauthenticated).

    The SPA's forceLogout() also calls this so the server-side cookie is cleared
    (JS can't clear an httpOnly cookie). Same attributes + Max-Age=0."""
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        key="sb_session",
        path="/",
        httponly=True,
        samesite="lax",
        secure=(http_request.url.scheme == "https"),
    )
    return response


# NOTE: there is deliberately NO public "set a password for a passwordless
# account" endpoint. Every account is created WITH a password (onboarding and
# admin "Add member" both require one), so a self-service claim flow would only
# be a way to seize a passwordless account by knowing its username. If an account
# ever ends up without a password, an admin sets a temporary one via
# POST /api/users/{name}/reset-password (admin-only) — see api_reset_password.


# ---------------------------------------------------------------------------
# Onboarding wizard (first-run setup)
# ---------------------------------------------------------------------------

class OnboardingCreateUserRequest(BaseModel):
    username: str
    display_name: str = ""
    password: str = ""
    timezone: str = "Etc/UTC"


@app.get("/api/onboarding/status")
async def onboarding_status():
    """Tell the frontend whether onboarding has been completed.

    The signal is simply 'are there any non-bot users in public.users'.
    First-boot installs return ``needs_onboarding=true``; once a user
    exists, ``needs_onboarding=false`` and the regular LoginScreen
    takes over.
    """
    def _do():
        users = get_all_users()
        non_bot = [u for u in users if "bot" not in (u.get("role") or "")]
        return {
            "needs_onboarding": len(non_bot) == 0,
            "user_count": len(non_bot),
            "openai_key_present": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "db_ok": True,  # The fact this endpoint replied means the DB is up.
        }
    return await asyncio.to_thread(_do)


class DisabledAppsRequest(BaseModel):
    disabled: list[str]


@app.get("/api/apps/disabled")
async def api_get_disabled_apps():
    """Return the list of app ids the operator has disabled.

    A disabled app is fully off: hidden from the desktop AND not loaded by the
    backend (no routes, tools, jobs, or thinking handler) on the next start.
    Stored in app_config(scope='platform'). Takes effect after a restart.
    """
    def _do():
        from app_platform import config as platform_config
        return {"disabled": platform_config.get("disabled_apps", [], scope="platform") or []}
    return await asyncio.to_thread(_do)


@app.post("/api/apps/disabled")
async def api_set_disabled_apps(request: DisabledAppsRequest, http_request: Request):
    """Replace the set of disabled app ids (admin action).

    Required (core) apps can't be disabled — the platform won't boot without them.
    A full disable (backend not loaded) takes effect on the next restart.
    """
    if not _is_admin_req(http_request):
        return JSONResponse({"ok": False, "error": "Admin access required."}, status_code=403)
    def _do():
        from app_platform import config as platform_config
        from app_platform.loader import REQUIRED_APPS
        ids = sorted({str(x).strip() for x in request.disabled if str(x).strip()})
        blocked = sorted(set(ids) & set(REQUIRED_APPS))
        if blocked:
            return {"ok": False, "error": f"These are required apps and cannot be disabled: {', '.join(blocked)}"}
        platform_config.set("disabled_apps", ids, scope="platform", by="settings-ui")
        return {"ok": True, "disabled": ids, "restart_required": True}
    return await asyncio.to_thread(_do)


class HiddenAppsRequest(BaseModel):
    hidden: list[str]


@app.get("/api/apps/required")
async def api_get_required_apps():
    """App ids that are required (core) and can't be disabled — for the admin Apps UI."""
    from app_platform.loader import REQUIRED_APPS
    return {"required": list(REQUIRED_APPS)}


@app.get("/api/apps/hidden")
async def api_get_hidden_apps(request: Request):
    """The CURRENT user's hidden launcher tiles (per-user, opt-out list).

    Empty = show everything — a newly installed app is shown by default because
    it's in nobody's hidden list. Identity is the verified principal.
    """
    user = require_user(request)["name"]
    def _do():
        from app_platform import config as platform_config
        return {"hidden": platform_config.get("hidden_apps", [], scope=f"user:{user}") or []}
    return await asyncio.to_thread(_do)


@app.post("/api/apps/hidden")
async def api_set_hidden_apps(req: HiddenAppsRequest, request: Request):
    """Replace the current user's hidden launcher tiles (per-user, self-only).

    Hiding only affects THIS user's desktop — it doesn't unload the app and
    doesn't touch anyone else. Takes effect immediately (no restart).
    """
    user = require_user(request)["name"]
    def _do():
        from app_platform import config as platform_config
        ids = sorted({str(x).strip() for x in req.hidden if str(x).strip()})
        platform_config.set("hidden_apps", ids, scope=f"user:{user}", by=user)
        return {"ok": True, "hidden": ids}
    return await asyncio.to_thread(_do)


class OpenableAppsRequest(BaseModel):
    apps: list


@app.post("/api/apps/openable")
async def api_set_openable_apps(req: OpenableAppsRequest, request: Request):
    """The web client reports its app-type registry (id, name, subview, tabs) so
    the ``open_app`` tool's app list is built **dynamically** from installed +
    enabled apps — never a hardcoded enum. Cache is global (enabled apps are
    platform-wide) and intentionally includes hidden/sub-view apps (still openable).
    """
    require_user(request)
    from local_tools import set_openable_apps
    set_openable_apps(req.apps)
    return {"ok": True, "count": len(req.apps or [])}


@app.post("/api/onboarding/check-openai")
async def onboarding_check_openai():
    """Verify the current OPENAI_API_KEY against the OpenAI API.

    We use the key already set in the agent's env (set in .env by the
    operator before `docker compose up`). This endpoint does not accept
    a key in the request body — that would mean writing back to .env
    from the container, which adds a bind-mount requirement we don't
    want to assume.
    """
    def _do():
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "OPENAI_API_KEY is not set in .env. Set it and restart the agent."}
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                if resp.status == 200:
                    return {"ok": True}
                return {"ok": False, "error": f"OpenAI returned HTTP {resp.status}"}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"ok": False, "error": "OpenAI rejected the key (HTTP 401). Check OPENAI_API_KEY in .env."}
            return {"ok": False, "error": f"OpenAI returned HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "error": f"Could not reach OpenAI: {e}"}
    return await asyncio.to_thread(_do)


@app.post("/api/onboarding/create-user")
async def onboarding_create_user(request: OnboardingCreateUserRequest, http_request: Request):
    """Create the primary admin user and write the chosen timezone into
    `public.app_config` (scope=platform, key=timezone) so the rest of
    the platform can pick it up after the next restart.

    Refuses if any non-bot user already exists — onboarding is one-shot.
    """
    from data_layer.users import create_user

    def _do():
        # Refuse if onboarding has already been done.
        users = get_all_users()
        non_bot = [u for u in users if "bot" not in (u.get("role") or "")]
        if non_bot:
            return {"ok": False, "error": "Onboarding has already been completed. Use the login page."}

        import re as _re
        name = (request.username or "").strip().lower()
        if not _re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name):
            return {"ok": False, "error": "Username must be 2-31 lowercase letters / digits / underscores, starting with a letter."}
        if len(request.password or "") < MIN_PASSWORD_LEN:
            return {"ok": False, "error": f"A password is required and must be at least {MIN_PASSWORD_LEN} characters."}

        display = (request.display_name or "").strip() or name.capitalize()
        password = request.password or None

        # The first user is the household admin AND a parent by default, and is
        # the 'primary' user (the installer/owner). 'parent' unlocks PM
        # behaviour, family-rules, and child-account management that 'admin'
        # alone doesn't grant; 'primary' is the authoritative marker that
        # get_primary_user() prefers (onboarding + proactive outreach target
        # this person). Operators can adjust roles later in Settings → Members
        # (note: 'primary' is shown there as a read-only badge, not a toggle).
        user = create_user(
            name=name,
            display_name=display,
            password=password,
            role="admin,member,parent,primary",
        )
        if not user:
            return {"ok": False, "error": f"Could not create user '{name}' (already exists?)."}

        # Persist the chosen timezone to the platform-scope settings.
        # app_platform.time.get_timezone() reads from this app_config
        # row, with a per-process cache that the Settings app
        # invalidates when it rewrites the value.
        tz = (request.timezone or "Etc/UTC").strip() or "Etc/UTC"
        try:
            from app_platform import config as platform_config
            platform_config.set("timezone", tz, scope="platform", by="onboarding")
        except Exception as exc:
            logger.warning("ONBOARDING: could not persist timezone: %s", exc)

        # Seed the onboarding goal NOW — after the primary admin exists — so its
        # descriptions can name them (get_primary_user() resolves to this user).
        # Best-effort: a failure here must never block account creation.
        try:
            from apps.goals.onboarding import ensure_onboarding
            logger.info("ONBOARDING: %s", ensure_onboarding())
        except Exception as exc:
            logger.warning("ONBOARDING: could not seed onboarding goal: %s", exc, exc_info=True)

        token = _issue_token(user)
        if not token:
            # The admin account was created, but we can't hand back a usable
            # session. Don't report success with an empty token (that traps the
            # client). Once the key is configured + the agent restarted, the
            # login screen takes over for this already-created user.
            return {"ok": False, "error": _NO_SESSION_ERR}
        return {
            "ok": True,
            "user": {
                "name": user["name"],
                "display_name": user["display_name"],
                "role": user["role"],
            },
            "token": token,
        }

    result = await asyncio.to_thread(_do)
    # On a successful onboarding auto-login, mirror the token into the session
    # cookie (same as /auth/login) so the new admin's browser navigations are
    # authenticated. Failures (no Set-Cookie) pass through as the plain dict.
    if isinstance(result, dict) and result.get("ok") and result.get("token"):
        response = JSONResponse(result)
        _set_session_cookie(response, result["token"], http_request)
        return response
    return result


class MobileRegisterRequest(BaseModel):
    user_id: str
    fcm_token: str
    device_id: str
    device_name: str = ""
    app_version: str = ""


class MobileUnregisterRequest(BaseModel):
    user_id: str
    device_id: str


@app.post("/api/mobile/register")
async def mobile_register(request: MobileRegisterRequest):
    """Register or update a mobile device's FCM token for push notifications."""
    from data_layer.mobile_devices import register_device
    device = await asyncio.to_thread(
        register_device,
        user_id=request.user_id,
        device_id=request.device_id,
        fcm_token=request.fcm_token,
        device_name=request.device_name,
        app_version=request.app_version,
    )
    if device:
        logger.info("MOBILE: Registered device %s for %s", request.device_id[:12], request.user_id)
        return {"success": True, "device_id": device["device_id"]}
    return {"success": False, "error": "Registration failed"}


@app.delete("/api/mobile/register")
async def mobile_unregister(request: MobileUnregisterRequest):
    """Unregister a mobile device (logout or uninstall cleanup)."""
    from data_layer.mobile_devices import unregister_device
    removed = await asyncio.to_thread(unregister_device, request.user_id, request.device_id)
    logger.info("MOBILE: Unregistered device %s for %s (found=%s)", request.device_id[:12], request.user_id, removed)
    return {"success": True}


@app.get("/tools")
async def list_tools():
    """List available MCP tools."""
    return {"tools": [{"name": t.name, "description": t.description} for t in mcp_client.mcp_tools]}


# ── Voice Session Endpoints ────────────────────────────────────────────────

class VoiceSessionRequest(BaseModel):
    user_id: str
    device_info: dict = {}


class VoiceSwitchAppRequest(BaseModel):
    session_id: str
    app: str


class VoiceEndRequest(BaseModel):
    session_id: str


@app.get("/api/config/picovoice")
async def get_picovoice_config():
    """Return Picovoice API key for wake word detection."""
    key = os.getenv("PICOVOICE_API_KEY", "")
    return {"access_key": key}


@app.post("/api/voice/session")
async def voice_create_session(request: VoiceSessionRequest):
    """Mint an ephemeral OpenAI Realtime token for a voice session."""
    from app_platform.voice.session import mint_ephemeral_token
    result = await asyncio.to_thread(mint_ephemeral_token, request.user_id, request.device_info)
    if result:
        return result
    return {"error": "Failed to create voice session"}


@app.post("/api/voice/switch-app")
async def voice_switch_app(request: VoiceSwitchAppRequest):
    """Build a session.update payload for switching to an app."""
    from app_platform.voice.session import build_switch_app_payload, build_exit_app_payload
    from app_platform.voice.prompting import is_exit_app_name
    app_name = request.app.lower().strip()
    if is_exit_app_name(app_name):
        result = build_exit_app_payload(request.session_id)
    else:
        result = build_switch_app_payload(request.session_id, app_name)
    if result:
        return result
    return {"error": "Session not found"}


@app.post("/api/voice/end")
async def voice_end_session(request: VoiceEndRequest):
    """End a voice session."""
    from app_platform.voice.session import end_session
    end_session(request.session_id)
    return {"success": True}


@app.websocket("/ws/voice/{session_id}")
async def voice_tool_relay(websocket: WebSocket, session_id: str):
    """Sideband WebSocket for relaying tool calls from Android to backend.

    Protocol:
    - Android sends: {type: "tool_call", call_id, name, arguments}
    - Backend executes the tool and returns: {type: "tool_result", call_id, output}
    - Backend may also return: {type: "confirmation_required", call_id, action, prompt}
    """
    from app_platform.voice.session import get_session
    session = get_session(session_id)
    if not session:
        await websocket.close(code=4001, reason="Unknown session")
        return

    principal = principal_from_ws(websocket)
    if not principal:
        await websocket.close(code=4401, reason="Authentication required")
        return
    # A service token (voice satellite), the session's own user, or an admin may connect.
    if (not principal.get("is_service")
            and principal.get("name") != session.get("user_id")
            and not has_role(principal, "admin")):
        await websocket.close(code=4403, reason="Forbidden")
        return

    await websocket.accept()
    user_id = session["user_id"]
    logger.info("VOICE: Sideband WS connected for session %s (user=%s)", session_id, user_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "tool_call":
                call_id = data.get("call_id", "")
                tool_name = data.get("name", "")
                arguments = data.get("arguments", {})

                logger.info("VOICE: Tool call %s: %s(%s)", call_id[:8], tool_name, list(arguments.keys()))

                from app_platform.voice.tool_runtime import handle_voice_tool_call

                events = await handle_voice_tool_call(
                    session_id=session_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
                for event in events:
                    await websocket.send_json(event)
                    if event.get("type") == "tool_result":
                        logger.info(
                            "VOICE: Tool result for %s: %s",
                            tool_name,
                            event.get("output", "")[:100],
                        )

            elif msg_type == "transcript":
                text = data.get("text", "")
                role = data.get("role", "user")
                logger.debug("VOICE: Transcript [%s] %s: %s", session_id[:8], role, text[:100])
                from app_platform.voice.chatlog import record_voice_transcript

                turn_id = await record_voice_transcript(
                    session_id,
                    role,
                    text,
                    user_id=user_id,
                )
                if turn_id:
                    logger.info("VOICE: Queued chat turn %s from session %s", turn_id, session_id[:8])

    except WebSocketDisconnect:
        logger.info("VOICE: Sideband WS disconnected for session %s", session_id)


@app.websocket("/ws/voice/audio/{session_id}")
async def voice_audio_relay(websocket: WebSocket, session_id: str):
    """Audio relay: bridge a voice satellite's 2-way PCM to a server-side OpenAI
    Realtime session (the platform holds the model session + runs tools). The
    satellite streams mic PCM (binary) and plays returned PCM (binary); see
    app_platform/voice/relay.py for the protocol. Mint the session first via
    POST /api/voice/session, then connect here with the same session_id.
    """
    from app_platform.voice.session import get_session
    from app_platform.voice.relay import relay_session

    session = get_session(session_id)
    if not session:
        await websocket.close(code=4001, reason="Unknown session")
        return

    principal = principal_from_ws(websocket)
    if not principal:
        await websocket.close(code=4401, reason="Authentication required")
        return
    # A service token (voice satellite), the session's own user, or an admin may connect.
    if (not principal.get("is_service")
            and principal.get("name") != session.get("user_id")
            and not has_role(principal, "admin")):
        await websocket.close(code=4403, reason="Forbidden")
        return

    await websocket.accept()
    logger.info("VOICE: Audio relay connected for session %s (user=%s)",
                session_id, session.get("user_id"))
    try:
        await relay_session(websocket, session_id, session)
    except WebSocketDisconnect:
        logger.info("VOICE: Audio relay disconnected for session %s", session_id)
    except Exception as exc:
        logger.error("VOICE: Audio relay error for session %s: %s", session_id, exc, exc_info=True)


@app.post("/tools/refresh")
async def refresh_tools():
    """Refresh the tools list from MCP server (call after creating new tools)."""
    await mcp_client.connect_to_mcp()
    # Rebuild direct-call registry to pick up new tools
    tool_dispatch._initialized = False
    await asyncio.to_thread(tool_dispatch.init)
    tool_dispatch.verify_against_mcp([t.name for t in mcp_client.mcp_tools])
    return {"status": "refreshed", "tool_count": len(mcp_client.mcp_tools)}


# Active app context per user — updated by WebSocket app_context messages
_user_app_context: dict[str, dict] = {}


def get_user_app_context(user_id: str) -> dict | None:
    """Get the current app context for a user (used by chat engine)."""
    return _user_app_context.get(user_id)


@app.websocket("/ws/{user_id}")
async def websocket_chat(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for real-time chat per user."""
    principal = principal_from_ws(websocket)
    if not principal:
        await websocket.close(code=4401, reason="Authentication required")
        return
    user_id = principal["name"]  # authoritative identity — ignore the path param
    # Browsers authenticate via the Sec-WebSocket-Protocol header; RFC 6455 requires
    # the server to echo back the selected subprotocol or the handshake fails. Native/
    # voice clients (Authorization header) offer no subprotocol, so this is None there.
    await manager.connect(user_id, websocket, subprotocol=ws_bearer_subprotocol(websocket))
    # Send build ID so client can detect agent restarts
    await websocket.send_json({"type": "build_id", "build_id": BUILD_ID})
    try:
        while True:
            data = await websocket.receive_json()

            # Handle keepalive pings (no-op)
            if data.get("type") == "ping":
                continue

            # Handle app context updates (non-chat messages)
            if data.get("type") == "app_context":
                _user_app_context[user_id] = data.get("context", {})
                continue

            message = data.get("message", "")
            if not message:
                continue

            await websocket.send_json({"type": "typing", "status": True})

            async def _ws_progress(text: str):
                await websocket.send_json({
                    "type": "progress",
                    "message": text,
                    "user_id": user_id
                })

            async def _ws_event(event: dict):
                await websocket.send_json(event)

            try:
                response_text = await process_chat(
                    user_id, message,
                    send_progress=_ws_progress,
                    channel="web",
                    app_context=_user_app_context.get(user_id),
                    send_event=_ws_event,
                )
                from datetime import datetime as _now_dt, timezone as _now_tz
                await websocket.send_json({
                    "type": "chat_response",
                    "response": response_text,
                    "user_id": user_id,
                    "ts": _now_dt.now(_now_tz.utc).isoformat(),  # issue #8: bubble timestamp
                })
            except Exception as e:
                import traceback
                logger.error("Chat error [%s]: %s\n%s", user_id, str(e), traceback.format_exc())
                await websocket.send_json({
                    "type": "chat_response",
                    "response": f"Error: {str(e)}",
                    "user_id": user_id
                })
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        _user_app_context.pop(user_id, None)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """HTTP chat endpoint - fallback for non-WebSocket clients."""
    try:
        response_text = await process_chat(request.user_id, request.message)
        return ChatResponse(response=response_text, user_id=request.user_id)
    except Exception as e:
        return ChatResponse(response=f"Error: {str(e)}", user_id=request.user_id)


@app.get("/api/chat/history")
async def chat_history(request: Request, limit: int = 20, tz: str = ""):
    """Recent conversation turns for the authed user — lets the web client
    resume a session on page load instead of starting cold.

    Identity is the verified principal (never a client-supplied id), so a user
    only ever gets their own history. Returns a flat, render-ready message list
    ordered oldest→newest: each turn expands to the user message, any tool calls
    the model made that turn, then the assistant reply. Bot-initiated turns
    (proactive DMs / fired notifications, stored with a ``[marker]`` pseudo
    user_message) render as notifications so they don't look like the user typed.
    """
    principal = require_user(request)
    user_id = (principal["name"] or "").lower().strip()
    limit = max(1, min(limit, 50))

    def _load():
        from data_layer.chatlogs import get_recent_turns
        return get_recent_turns(user_id, limit=limit)

    turns = await asyncio.to_thread(_load)

    # Flatten + stamp ts + insert date separators in the client's timezone (issue #8).
    # The grouping/label logic lives in the pure chat_render.render_chat_history so it's
    # deterministically unit-tested; tz is untrusted client input (falls back to UTC).
    from chat_render import render_chat_history
    from datetime import datetime, timezone
    messages = render_chat_history(turns, datetime.now(timezone.utc), tz)

    return {"messages": messages}


# ---------------------------------------------------------------------------
# App API endpoints — Goals
# ---------------------------------------------------------------------------

@app.get("/api/apps/goals/summary")
async def goals_summary():
    """Get all goals with progress for the Goals app."""
    def _fetch():
        all_goals = dl_goals.list_entities("g-")
        result = []
        for g in all_goals:
            projects = dl_goals.get_projects_for_goal(g["id"])
            total_tasks = 0
            done_tasks = 0
            for p in projects:
                tasks = dl_goals.get_tasks_for_project(p["id"])
                total_tasks += len(tasks)
                done_tasks += sum(1 for t in tasks if t.get("status") == "done")
                total_tasks -= sum(1 for t in tasks if t.get("status") in ("deferred", "cancelled"))
            progress = done_tasks / total_tasks if total_tasks > 0 else 0.0
            result.append({
                "id": g["id"],
                "name": g["name"],
                "owners": g.get("owners", []),
                "collaborators": g.get("collaborators", []),
                "status": g.get("status", "not_started"),
                "target_date": g.get("target_date", ""),
                "progress": progress,
                "project_count": len(projects),
                "task_count": total_tasks,
            })
        return result
    goals = await asyncio.to_thread(_fetch)
    return {"goals": goals}


@app.get("/api/apps/goals/tasks/{task_id}")
async def task_detail(task_id: str):
    """Get a task with its subtasks, notes, and parent context."""
    def _fetch():
        task = dl_goals.load_entity(task_id)
        if not task:
            return None
        subtasks = dl_goals.get_subtasks(task_id)
        notes = dl_goals.load_notes(task_id)
        # Get parent project + goal names for breadcrumb
        project_name = ""
        goal_id = ""
        goal_name = ""
        if task.get("project_id"):
            project = dl_goals.load_entity(task["project_id"])
            if project:
                project_name = project["name"]
                goal_id = project.get("goal_id", "")
                if goal_id:
                    goal = dl_goals.load_entity(goal_id)
                    if goal:
                        goal_name = goal["name"]
        def _assignee(t):
            a = t.get("assigned_to", [])
            return a[0] if a else ""
        subtask_list = [{
            "id": s["id"],
            "name": s["name"],
            "status": s.get("status", "not_started"),
            "priority": s.get("priority", "medium"),
            "assigned_to": _assignee(s),
            "due_date": s.get("due_date", ""),
        } for s in subtasks]
        result = {
            "id": task["id"],
            "name": task["name"],
            "project_id": task.get("project_id", ""),
            "project_name": project_name,
            "goal_id": goal_id,
            "goal_name": goal_name,
            "status": task.get("status", "not_started"),
            "priority": task.get("priority", "medium"),
            "assigned_to": _assignee(task),
            "due_date": task.get("due_date", ""),
            "depends_on": task.get("depends_on", []),
            "notes": notes,
            "definition_of_done": task.get("definition_of_done", ""),
            "subtasks": subtask_list,
            "history": task.get("history", [])[-10:],  # last 10 history entries
            "created_by": task.get("created_by", ""),
            "created_at": task.get("created_at", ""),
        }
        # Trello card info for linked tasks
        trello_card_id = task.get("trello_card_id", "")
        if trello_card_id and task.get("trello_linked"):
            result["trello_card_id"] = trello_card_id
            result["trello_board"] = ""
            result["trello_labels"] = []
            try:
                if task.get("project_id"):
                    proj = dl_goals.load_entity(task["project_id"])
                    if proj:
                        from trello_task_sync import get_project_trello_config
                        config = get_project_trello_config(proj)
                        if config:
                            board_name = config["board"]
                            result["trello_board"] = board_name
                            from trello_client import get_board_config, _request
                            account = get_board_config(board_name)["account"]
                            card_data = _request("GET", f"/cards/{trello_card_id}", account, {"fields": "labels"})
                            result["trello_labels"] = [
                                {"id": lb["id"], "name": lb.get("name", ""), "color": lb.get("color", "")}
                                for lb in card_data.get("labels", [])
                            ]
            except Exception:
                pass  # non-fatal: show task even if Trello API fails
        return result
    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"error": "Task not found"}, 404
    return result


@app.get("/api/apps/goals/trello/board-labels/{board_name}")
async def trello_board_labels_api(board_name: str):
    """Get all labels for a Trello board."""
    def _fetch():
        from trello_client import get_labels
        return get_labels(board_name.strip().lower())
    labels = await asyncio.to_thread(_fetch)
    return {"labels": labels}


class CardLabelRequest(BaseModel):
    board_name: str
    label_id: str = ""
    label_name: str = ""
    label_color: str = "sky"


@app.post("/api/apps/goals/trello/card-labels/{card_id}/add")
async def trello_card_add_label_api(card_id: str, req: CardLabelRequest):
    """Add a label to a Trello card."""
    def _do():
        from trello_client import get_board_config, _request, ensure_label
        account = get_board_config(req.board_name)["account"]
        if req.label_id:
            _request("POST", f"/cards/{card_id}/idLabels", account, {"value": req.label_id})
            return {"ok": True}
        elif req.label_name:
            label = ensure_label(req.board_name, req.label_name.strip(), req.label_color.strip())
            _request("POST", f"/cards/{card_id}/idLabels", account, {"value": label["id"]})
            return {"ok": True, "label": label}
        return {"error": "label_id or label_name required"}
    return await asyncio.to_thread(_do)


@app.post("/api/apps/goals/trello/card-labels/{card_id}/remove")
async def trello_card_remove_label_api(card_id: str, req: CardLabelRequest):
    """Remove a label from a Trello card."""
    def _do():
        from trello_client import get_board_config, _request
        account = get_board_config(req.board_name)["account"]
        if req.label_id:
            _request("DELETE", f"/cards/{card_id}/idLabels/{req.label_id}", account)
            return {"ok": True}
        return {"error": "label_id required"}
    return await asyncio.to_thread(_do)


@app.get("/api/apps/goals/projects/{project_id}")
async def project_detail(project_id: str):
    """Get a project with all its tasks for the Goals app."""
    def _fetch():
        project = dl_goals.load_entity(project_id)
        if not project:
            return None
        tasks = dl_goals.get_tasks_for_project(project_id)
        notes = dl_goals.load_notes(project_id)
        # Get parent goal name for breadcrumb
        goal_name = ""
        if project.get("goal_id"):
            goal = dl_goals.load_entity(project["goal_id"])
            if goal:
                goal_name = goal["name"]
        def _assignee_str(t):
            a = t.get("assigned_to", [])
            return a[0] if a else ""
        task_list = [{
            "id": t["id"],
            "name": t["name"],
            "status": t.get("status", "not_started"),
            "priority": t.get("priority", "medium"),
            "assigned_to": _assignee_str(t),
            "due_date": t.get("due_date", ""),
            "parent_task_id": t.get("parent_task_id"),
            "stack_rank": t.get("stack_rank", 0),
            "trello_linked": bool(t.get("trello_linked")),
        } for t in tasks]
        return {
            "id": project["id"],
            "name": project["name"],
            "goal_id": project.get("goal_id", ""),
            "goal_name": goal_name,
            "owners": project.get("owners", []),
            "status": project.get("status", "not_started"),
            "priority": project.get("priority", "medium"),
            "due_date": project.get("due_date", ""),
            "notes": notes,
            "definition_of_done": project.get("definition_of_done", ""),
            "history": project.get("history", [])[-10:],
            "created_by": project.get("created_by", ""),
            "created_at": project.get("created_at", ""),
            "pm_cadence_minutes": project.get("pm_cadence_minutes"),
            "trello_board": (project.get("trello") or {}).get("board", ""),
            "tasks": task_list,
        }
    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"error": "Project not found"}, 404
    return result


@app.get("/api/apps/goals/search")
async def search_goals_api(q: str = ""):
    """Search across goals, projects, and tasks by keyword."""
    def _fetch():
        if not q.strip():
            return []
        query = q.strip().lower()
        results = []
        for prefix, etype in [("g-", "goal"), ("p-", "project"), ("t-", "task")]:
            entities = dl_goals.list_entities(prefix)
            for e in entities:
                name = e.get("name", "").lower()
                if query in name:
                    results.append({
                        "id": e["id"],
                        "name": e["name"],
                        "type": etype,
                        "status": e.get("status", "not_started"),
                    })
        # Also search notes
        for prefix, etype in [("g-", "goal"), ("p-", "project"), ("t-", "task")]:
            entities = dl_goals.list_entities(prefix)
            for e in entities:
                notes = dl_goals.load_notes(e["id"])
                if notes and query in notes.lower():
                    if not any(r["id"] == e["id"] for r in results):
                        results.append({
                            "id": e["id"],
                            "name": e["name"],
                            "type": etype,
                            "status": e.get("status", "not_started"),
                            "match": "notes",
                        })
        return results[:30]  # cap results
    results = await asyncio.to_thread(_fetch)
    return {"results": results, "count": len(results)}


@app.get("/api/apps/goals/{goal_id}")
async def goal_detail(goal_id: str):
    """Get a goal with its projects for the Goals app."""
    def _fetch():
        goal = dl_goals.load_entity(goal_id)
        if not goal:
            return None
        projects = dl_goals.get_projects_for_goal(goal_id)
        proj_list = []
        for p in projects:
            tasks = dl_goals.get_tasks_for_project(p["id"])
            active_tasks = [t for t in tasks if t.get("status") not in ("deferred", "cancelled")]
            done = sum(1 for t in active_tasks if t.get("status") == "done")
            trello_cfg = p.get("trello") or {}
            proj_list.append({
                "id": p["id"],
                "name": p["name"],
                "owners": p.get("owners", []),
                "status": p.get("status", "not_started"),
                "priority": p.get("priority", "medium"),
                "due_date": p.get("due_date", ""),
                "task_summary": f"{done}/{len(active_tasks)} tasks done" if active_tasks else "No tasks",
                "trello_board": trello_cfg.get("board", ""),
            })
        notes = dl_goals.load_notes(goal_id)
        return {
            "id": goal["id"],
            "name": goal["name"],
            "owners": goal.get("owners", []),
            "collaborators": goal.get("collaborators", []),
            "status": goal.get("status", "not_started"),
            "target_date": goal.get("target_date", ""),
            "notes": notes,
            "definition_of_done": goal.get("definition_of_done", ""),
            "history": goal.get("history", [])[-10:],
            "created_by": goal.get("created_by", ""),
            "created_at": goal.get("created_at", ""),
            "projects": proj_list,
        }
    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"error": "Goal not found"}, 404
    return result


# ---------------------------------------------------------------------------
# App API endpoints — Goals inline actions
# ---------------------------------------------------------------------------

class InlineUpdateRequest(BaseModel):
    updated_by: str
    status: str = ""
    priority: str = ""
    name: str = ""
    assigned_to: str = ""  # comma-separated
    owners: str = ""  # comma-separated
    collaborators: str = ""  # comma-separated
    due_date: str = ""
    target_date: str = ""
    definition_of_done: str | None = None
    pm_cadence_minutes: int | None = None
    note: str = ""


@app.patch("/api/apps/goals/entities/{entity_id}")
async def patch_entity(entity_id: str, req: InlineUpdateRequest, http_request: Request):
    """Inline field update for any goal/project/task from the Goals app UI."""
    req.updated_by = _actor_name(http_request)
    from apps.goals.store import update_item as _update_item
    fields = {}
    if req.priority:
        fields["priority"] = req.priority
    if req.name:
        fields["name"] = req.name
    if req.assigned_to:
        fields["assigned_to"] = req.assigned_to
    if req.owners:
        fields["owners"] = req.owners
    if req.collaborators:
        fields["collaborators"] = req.collaborators
    if req.due_date:
        fields["due_date"] = req.due_date
    if req.target_date:
        fields["target_date"] = req.target_date
    if req.definition_of_done is not None:
        fields["definition_of_done"] = req.definition_of_done
    if req.pm_cadence_minutes is not None:
        fields["pm_cadence_minutes"] = req.pm_cadence_minutes if req.pm_cadence_minutes > 0 else None
    logger.info("PATCH_ENTITY: id=%s fields=%s status=%r", entity_id, fields, req.status)
    def _do():
        return _update_item(
            item_id=entity_id,
            updated_by=req.updated_by,
            status=req.status,
            history_note=req.note,
            fields=fields if fields else None,
        )
    result = await asyncio.to_thread(_do)
    logger.info("PATCH_ENTITY result: %s", result)
    if result.startswith("Error"):
        return {"error": result}
    # Auto-manage thinking domain when ownership or status changes on any entity
    if req.owners or req.assigned_to or req.status:
        try:
            from apps.goals.lifecycle import sync_entity_domain
            lifecycle = await asyncio.to_thread(sync_entity_domain, entity_id)
            if lifecycle:
                logger.info("PATCH_ENTITY: goal domain lifecycle → %s", lifecycle)
        except Exception as e:
            logger.error("PATCH_ENTITY: goal domain lifecycle error: %s", e)
    return {"ok": True, "message": result}


class CreateGoalRequest(BaseModel):
    name: str
    created_by: str
    owners: str = ""
    target_date: str = ""
    initial_notes: str = ""


@app.post("/api/apps/goals")
async def create_goal_api(req: CreateGoalRequest, http_request: Request):
    """Create a new goal from the Goals app UI."""
    req.created_by = _actor_name(http_request)
    from apps.goals.store import create_goal as _create_goal
    owner_list = (
        [o.strip().lower() for o in req.owners.split(",") if o.strip()]
        if req.owners else None
    )
    def _do():
        return _create_goal(
            name=req.name.strip(),
            created_by=req.created_by.strip().lower(),
            description=req.initial_notes.strip() if req.initial_notes else "",
            owners=owner_list,
            target_date=req.target_date.strip() if req.target_date else "",
        )
    result = await asyncio.to_thread(_do)
    if isinstance(result, str):
        return {"error": result}
    # Auto-create thinking domain for every new active goal
    try:
        from apps.goals.lifecycle import sync_goal_domain
        lifecycle = await asyncio.to_thread(sync_goal_domain, result["id"])
        if lifecycle:
            logger.info("CREATE_GOAL: goal domain lifecycle → %s", lifecycle)
    except Exception as e:
        logger.error("CREATE_GOAL: goal domain lifecycle error: %s", e)
    return {"ok": True, "id": result["id"], "name": result["name"]}


class CreateProjectRequest(BaseModel):
    goal_id: str
    name: str
    created_by: str
    owners: str = ""
    priority: str = "medium"
    due_date: str = ""


@app.post("/api/apps/goals/projects")
async def create_project_api(req: CreateProjectRequest, http_request: Request):
    """Create a new project from the Goals app UI."""
    req.created_by = _actor_name(http_request)
    from apps.goals.store import create_project as _create_project
    owner_list = (
        [o.strip().lower() for o in req.owners.split(",") if o.strip()]
        if req.owners else None
    )
    def _do():
        return _create_project(
            goal_id=req.goal_id.strip(),
            name=req.name.strip(),
            created_by=req.created_by.strip().lower(),
            owners=owner_list,
            due_date=req.due_date.strip() if req.due_date else "",
            priority=req.priority.strip().lower() if req.priority else "medium",
        )
    result = await asyncio.to_thread(_do)
    if isinstance(result, str):
        return {"error": result}
    return {"ok": True, "id": result["id"], "name": result["name"]}


class CreateTaskRequest(BaseModel):
    project_id: str
    name: str
    created_by: str
    assigned_to: str = ""
    priority: str = "medium"
    due_date: str = ""
    parent_task_id: str = ""


@app.post("/api/apps/goals/tasks")
async def create_task_api(req: CreateTaskRequest, http_request: Request):
    """Create a new task from the Goals app UI."""
    req.created_by = _actor_name(http_request)
    from apps.goals.store import create_task as _create_task
    assignee_list = (
        [a.strip().lower() for a in req.assigned_to.split(",") if a.strip()]
        if req.assigned_to else None
    )
    def _do():
        return _create_task(
            project_id=req.project_id.strip() if req.project_id else "",
            name=req.name.strip(),
            created_by=req.created_by.strip().lower(),
            assigned_to=assignee_list,
            due_date=req.due_date.strip() if req.due_date else "",
            priority=req.priority.strip().lower() if req.priority else "medium",
            parent_task_id=req.parent_task_id.strip() if req.parent_task_id else None,
        )
    result = await asyncio.to_thread(_do)
    if isinstance(result, str):
        return {"error": result}
    return {"ok": True, "id": result["id"], "name": result["name"]}


class ReorderTaskRequest(BaseModel):
    task_id: str
    direction: str  # "up" or "down"
    updated_by: str = "web"


@app.post("/api/apps/goals/tasks/reorder")
async def reorder_task_api(req: ReorderTaskRequest):
    """Move a task up or down within its status group in the project."""
    def _do():
        task = dl_goals.load_entity(req.task_id)
        if not task:
            return {"error": "Task not found"}
        project_id = task.get("project_id")
        if not project_id:
            return {"error": "Task has no project"}
        all_tasks = dl_goals.get_tasks_for_project(project_id)
        # Group by status, preserving stack_rank order
        same_status = [t for t in all_tasks if t.get("status") == task.get("status")]
        idx = next((i for i, t in enumerate(same_status) if t["id"] == req.task_id), -1)
        if idx < 0:
            return {"error": "Task not found in status group"}
        if req.direction == "up" and idx == 0:
            return {"ok": True, "message": "Already at top"}
        if req.direction == "down" and idx >= len(same_status) - 1:
            return {"ok": True, "message": "Already at bottom"}
        # Swap stack_ranks with neighbor
        swap_idx = idx - 1 if req.direction == "up" else idx + 1
        a, b = same_status[idx], same_status[swap_idx]
        a_rank, b_rank = a.get("stack_rank", 0), b.get("stack_rank", 0)
        # If they happen to have the same rank, force a difference
        if a_rank == b_rank:
            b_rank = a_rank + (1 if req.direction == "up" else -1)
        a["stack_rank"] = b_rank
        b["stack_rank"] = a_rank
        dl_goals.save_entity(a)
        dl_goals.save_entity(b)
        return {"ok": True}
    return await asyncio.to_thread(_do)


class SaveNotesRequest(BaseModel):
    content: str
    updated_by: str = ""


@app.put("/api/apps/goals/entities/{entity_id}/notes")
async def save_entity_notes_inline(entity_id: str, req: SaveNotesRequest, http_request: Request):
    """Save notes for any entity from the Goals app inline editor."""
    req.updated_by = _actor_name(http_request)
    from apps.goals.store import update_notes as _update_notes
    def _do():
        return _update_notes(
            item_id=entity_id,
            content=req.content,
            updated_by=req.updated_by,
        )
    result = await asyncio.to_thread(_do)
    if result.startswith("Error"):
        return {"error": result}
    return {"ok": True}


@app.get("/api/users")
async def list_users(include_bots: bool = False):
    """Get users for dropdowns + the Settings → Members panel. Excludes bots by default."""
    def _fetch():
        from data_layer.users import get_human_users
        users = get_all_users() if include_bots else get_human_users()
        return [{
            "name": u["name"],
            "display_name": u.get("display_name", u["name"]),
            "role": u.get("role", "member"),
            "sort_order": u.get("sort_order", 99),
            "has_password": bool(u.get("password_hash")),
            "discord_id": u.get("discord_id") or "",
        } for u in users]
    return await asyncio.to_thread(_fetch)


# ---------------------------------------------------------------------------
# Household member management (Settings → Members)
# ---------------------------------------------------------------------------
# Auth model matches the rest of the platform: write actions take an ``actor``
# (the caller's canonical username) and are gated on the actor's ``admin`` role.
# Self-service password change verifies the user's current password instead.

import re as _re_users

_ALLOWED_ROLES = ("admin", "member", "parent")
# Valid roles that the Members roster does NOT offer as toggles (they aren't
# user-grantable here): `primary` is the single owner, `kid`/`bot` are special.
# They're preserved as-is when an admin edits a user's editable roles, so a
# round-trip through the role pickers never silently drops them.
_PRESERVED_ROLES = ("primary", "kid", "bot")
_USERNAME_RE = _re_users.compile(r"^[a-z][a-z0-9_]{1,30}$")


def _is_admin(name: str) -> bool:
    u = get_user((name or "").lower().strip())
    return bool(u and has_role(u, "admin"))


def _principal(request: Request) -> dict | None:
    """The authenticated principal attached by the auth middleware, or None."""
    return getattr(request.state, "principal", None)


def _is_admin_req(request: Request, fallback_actor: str = "") -> bool:
    """Admin check from the authenticated principal. Auth is unconditional, so the
    principal is always present on a mounted route; the client-supplied actor is
    never trusted."""
    p = _principal(request)
    return bool(p and has_role(p, "admin"))


def _actor_name(request: Request, fallback: str = "") -> str:
    """The acting user's canonical name, taken from the verified principal. The
    client-supplied value is never trusted."""
    p = _principal(request)
    return ((p["name"] if p else "")).lower().strip()


def _admin_count() -> int:
    return sum(1 for u in get_all_users() if has_role(u, "admin"))


def _normalize_roles(role_str: str) -> str | None:
    """Validate + normalize a comma-separated role string. Returns None if it
    contains anything outside the known set (editable + preserved). Roles in
    _PRESERVED_ROLES (e.g. `primary`) aren't offered as roster toggles but are
    kept intact when present, so editing a user's roles doesn't drop them."""
    roles = [r for r in parse_roles(role_str)] or ["member"]
    known = set(_ALLOWED_ROLES) | set(_PRESERVED_ROLES)
    if any(r not in known for r in roles):
        return None
    # Keep a stable, de-duped order (editable first, then preserved).
    order = ("admin", "parent", "member", "primary", "kid", "bot")
    return ",".join([r for r in order if r in roles])


class CreateUserRequest(BaseModel):
    actor: str
    username: str
    display_name: str = ""
    role: str = "member"
    password: str = ""


class UpdateRoleRequest(BaseModel):
    actor: str
    role: str


class ResetPasswordRequest(BaseModel):
    actor: str
    new_password: str


class UpdateDiscordIdRequest(BaseModel):
    actor: str = ""
    discord_id: str | None = None


class ChangePasswordRequest(BaseModel):
    username: str
    current_password: str
    new_password: str


@app.post("/api/users")
async def api_create_user(req: CreateUserRequest, request: Request):
    """Admin-only: create a household member with a temporary password.

    The new member logs in with the temp password, then changes it via
    POST /api/auth/change-password.
    """
    def _do():
        if not _is_admin_req(request, req.actor):
            return {"ok": False, "error": "Admin access required."}
        name = (req.username or "").lower().strip()
        if not _USERNAME_RE.match(name):
            return {"ok": False, "error": "Username must be 2–31 chars: lowercase letters/digits/underscores, starting with a letter."}
        if get_user(name):
            return {"ok": False, "error": f"User '{name}' already exists."}
        roles = _normalize_roles(req.role)
        if roles is None:
            return {"ok": False, "error": f"Invalid role. Allowed: {', '.join(_ALLOWED_ROLES)}."}
        if len(req.password or "") < MIN_PASSWORD_LEN:
            return {"ok": False, "error": f"A temporary password is required and must be at least {MIN_PASSWORD_LEN} characters."}
        user = create_user(
            name=name,
            display_name=(req.display_name or "").strip() or name.capitalize(),
            password=req.password or None,
            role=roles,
        )
        if not user:
            return {"ok": False, "error": f"Could not create user '{name}'."}
        return {"ok": True, "user": {"name": user["name"], "display_name": user["display_name"], "role": user["role"]}}
    return await asyncio.to_thread(_do)


@app.patch("/api/users/{name}/role")
async def api_update_user_role(name: str, req: UpdateRoleRequest, request: Request):
    """Admin-only: change a member's roles. Won't drop the last admin."""
    def _do():
        if not _is_admin_req(request, req.actor):
            return {"ok": False, "error": "Admin access required."}
        target = (name or "").lower().strip()
        user = get_user(target)
        if not user:
            return {"ok": False, "error": f"User '{target}' not found."}
        roles = _normalize_roles(req.role)
        if roles is None:
            return {"ok": False, "error": f"Invalid role. Allowed: {', '.join(_ALLOWED_ROLES)}."}
        # Don't strip admin from the last remaining admin.
        if has_role(user, "admin") and "admin" not in parse_roles(roles) and _admin_count() <= 1:
            return {"ok": False, "error": "Can't remove the last admin. Promote another member first."}
        update_role(target, roles)
        return {"ok": True}
    return await asyncio.to_thread(_do)


@app.post("/api/users/{name}/reset-password")
async def api_reset_user_password(name: str, req: ResetPasswordRequest, request: Request):
    """Admin-only: set a new temporary password for a member (no current
    password needed). The member can change it afterwards."""
    def _do():
        if not _is_admin_req(request, req.actor):
            return {"ok": False, "error": "Admin access required."}
        target = (name or "").lower().strip()
        if not get_user(target):
            return {"ok": False, "error": f"User '{target}' not found."}
        if len(req.new_password or "") < MIN_PASSWORD_LEN:
            return {"ok": False, "error": f"Password must be at least {MIN_PASSWORD_LEN} characters."}
        update_password(target, req.new_password)
        return {"ok": True}
    return await asyncio.to_thread(_do)


@app.patch("/api/users/{name}/discord-id")
async def api_update_user_discord_id(name: str, req: UpdateDiscordIdRequest, request: Request):
    """Admin-only: link/unlink ANOTHER member's Discord account.

    Members can self-link via Settings → Members ("My Discord link"); this lets an
    admin set it for someone else (e.g. a kid who won't do it themselves). Same
    rules as self-service: a Discord ID is a 17–20 digit numeric snowflake and maps
    to exactly one Skipper user. Blank unlinks.
    """
    def _do():
        if not _is_admin_req(request, req.actor):
            return {"ok": False, "error": "Admin access required."}
        target = (name or "").lower().strip()
        if not get_user(target):
            return {"ok": False, "error": f"User '{target}' not found."}
        raw = (req.discord_id or "").strip()
        if raw and (not raw.isdigit() or not (17 <= len(raw) <= 20)):
            return {"ok": False, "error": (
                "Discord ID must be the numeric user ID (17–20 digits). In Discord: "
                "User Settings → Advanced → Developer Mode, then right-click a name → "
                "Copy User ID.")}
        from data_layer.users import get_user_by_discord_id, update_discord_id
        if raw:
            other = get_user_by_discord_id(raw)
            if other and other["name"] != target:
                return {"ok": False, "error": f"That Discord ID is already linked to @{other['name']}."}
        if not update_discord_id(target, raw or None):
            return {"ok": False, "error": f"Could not update '{target}'."}
        return {"ok": True, "discord_id": raw}
    return await asyncio.to_thread(_do)


@app.delete("/api/users/{name}")
async def api_delete_user(name: str, request: Request, actor: str = ""):
    """Admin-only: remove a member. Can't remove yourself or the last admin."""
    def _do():
        if not _is_admin_req(request, actor):
            return {"ok": False, "error": "Admin access required."}
        target = (name or "").lower().strip()
        if target == _actor_name(request, actor):
            return {"ok": False, "error": "You can't remove your own account."}
        user = get_user(target)
        if not user:
            return {"ok": False, "error": f"User '{target}' not found."}
        if has_role(user, "admin") and _admin_count() <= 1:
            return {"ok": False, "error": "Can't remove the last admin."}
        delete_user(target)
        return {"ok": True}
    return await asyncio.to_thread(_do)


@app.post("/api/auth/change-password")
async def api_change_password(req: ChangePasswordRequest, request: Request):
    """Self-service: a logged-in member changes their own password by proving
    their current one. When authenticated, the target is the principal (you can
    only change your OWN password); the request username is a legacy fallback."""
    def _do():
        name = _actor_name(request, req.username)
        user = get_user(name)
        if not user:
            return {"ok": False, "error": "Unknown user."}
        if len(req.new_password or "") < MIN_PASSWORD_LEN:
            return {"ok": False, "error": f"New password must be at least {MIN_PASSWORD_LEN} characters."}
        # Verify the current password (unless none is set yet — first password).
        if user.get("password_hash") and not authenticate(name, req.current_password or ""):
            return {"ok": False, "error": "Current password is incorrect."}
        update_password(name, req.new_password)
        return {"ok": True}
    return await asyncio.to_thread(_do)


@app.delete("/api/apps/goals/entities/{entity_id}")
async def delete_entity_api(entity_id: str, updated_by: str = ""):
    """Delete a goal, project, or task from the Goals app UI."""
    from apps.goals.store import delete_item as _delete_item
    def _do():
        return _delete_item(entity_id, updated_by or "web")
    result = await asyncio.to_thread(_do)
    if isinstance(result, str) and result.startswith("Error"):
        return {"error": result}
    return {"ok": True, "message": result}


@app.get("/api/apps/goals/my-tasks/{user_id}")
async def my_tasks_api(user_id: str, http_request: Request, status_filter: str = ""):
    """Get all tasks assigned to a user across all projects."""
    user_id = scope_user(http_request, user_id)
    def _fetch():
        all_tasks = dl_goals.list_entities("t-")
        user_lower = user_id.lower().strip()
        matched = []
        for t in all_tasks:
            assignees = [a.lower() for a in t.get("assigned_to", [])]
            if user_lower in assignees:
                if status_filter and status_filter != "all" and t.get("status") != status_filter:
                    continue
                if not status_filter and t.get("status") in ("done", "cancelled"):
                    continue
                # Get parent names
                project = dl_goals.load_entity(t.get("project_id", ""))
                project_name = project["name"] if project else ""
                goal_id = project.get("goal_id", "") if project else ""
                goal = dl_goals.load_entity(goal_id) if goal_id else None
                goal_name = goal["name"] if goal else ""
                # Skip tasks whose parent project or goal is inactive
                _inactive = ("done", "blocked", "deferred", "cancelled")
                if project and project.get("status") in _inactive:
                    continue
                if goal and goal.get("status") in _inactive:
                    continue
                matched.append({
                    "id": t["id"],
                    "name": t["name"],
                    "status": t.get("status", "not_started"),
                    "priority": t.get("priority", "medium"),
                    "due_date": t.get("due_date", ""),
                    "assigned_to": (t.get("assigned_to", []) or [""])[0],
                    "project_id": t.get("project_id", ""),
                    "project_name": project_name,
                    "goal_name": goal_name,
                    "trello_linked": bool(t.get("trello_linked")),
                })
        # Sort: blocked first, then in_progress, then not_started, then deferred
        order = {"blocked": 0, "in_progress": 1, "not_started": 2, "deferred": 3, "done": 4, "cancelled": 5}
        matched.sort(key=lambda x: (order.get(x["status"], 5), x.get("priority") != "high"))
        return matched
    tasks = await asyncio.to_thread(_fetch)
    return {"tasks": tasks, "count": len(tasks)}


# NOTE: search_goals_api moved above /api/apps/goals/{goal_id} to avoid route conflict


# ---------------------------------------------------------------------------
# App API endpoints — Document Editor
# ---------------------------------------------------------------------------

@app.get("/api/apps/documents/entity-notes/{entity_id}")
async def get_entity_notes(entity_id: str):
    """Get the notes content for a goal/project/task."""
    def _fetch():
        entity = dl_goals.load_entity(entity_id)
        if not entity:
            return None
        notes = dl_goals.load_notes(entity_id)
        return {"content": notes, "title": entity.get("name", entity_id)}
    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"error": "Entity not found"}, 404
    return result


class UpdateNotesRequest(BaseModel):
    content: str
    updated_by: str = ""


@app.put("/api/apps/documents/entity-notes/{entity_id}")
async def put_entity_notes(entity_id: str, request: UpdateNotesRequest):
    """Save notes content for a goal/project/task."""
    def _save():
        entity = dl_goals.load_entity(entity_id)
        if not entity:
            return False
        dl_goals.save_notes(entity_id, request.content)
        return True
    ok = await asyncio.to_thread(_save)
    if not ok:
        return {"error": "Entity not found"}, 404
    return {"ok": True}


# ---------------------------------------------------------------------------
# App API endpoints — Documents (standalone d-* docs)
# ---------------------------------------------------------------------------

@app.get("/api/apps/documents")
async def api_list_documents(tag: str = "", created_by: str = "", related_entity_id: str = ""):
    """List all documents (metadata only, no content)."""
    def _fetch():
        return doc_store.list_docs(
            tag=tag.strip() if tag else "",
            created_by=created_by.strip() if created_by else "",
            related_entity_id=related_entity_id.strip() if related_entity_id else "",
        )
    docs = await asyncio.to_thread(_fetch)
    return {"documents": docs, "count": len(docs)}


@app.get("/api/apps/documents/search")
async def api_search_documents(q: str = ""):
    """Search documents by keyword."""
    if not q.strip():
        return {"results": [], "count": 0}
    def _fetch():
        return doc_store.search_docs(q.strip())
    results = await asyncio.to_thread(_fetch)
    return {"results": results, "count": len(results)}


@app.get("/api/apps/documents/{doc_id}")
async def api_get_document(doc_id: str):
    """Get a single document with full content."""
    def _fetch():
        return doc_store.get_doc(doc_id)
    doc = await asyncio.to_thread(_fetch)
    if not doc:
        return {"error": "Document not found"}, 404
    # Also fetch linked entities
    def _links():
        return link_registry.get_linked_ids(doc_id)
    linked = await asyncio.to_thread(_links)
    doc["linked_entities"] = linked
    return doc


class CreateDocRequest(BaseModel):
    title: str
    created_by: str
    content: str = ""
    tags: str = ""
    related_entity_id: str = ""


@app.post("/api/apps/documents")
async def api_create_document(request: CreateDocRequest, http_request: Request):
    """Create a new standalone document."""
    request.created_by = _actor_name(http_request)
    def _create():
        tag_list = [t.strip() for t in request.tags.split(",") if t.strip()] if request.tags else []
        return doc_store.create_doc(
            title=request.title.strip(),
            created_by=request.created_by.strip(),
            content=request.content.strip() if request.content else "",
            tags=tag_list,
            related_entity_id=request.related_entity_id.strip() if request.related_entity_id else "",
        )
    doc = await asyncio.to_thread(_create)
    return doc


class UpdateDocRequest(BaseModel):
    content: str
    updated_by: str
    title: str = ""
    tags: str | None = None


@app.put("/api/apps/documents/{doc_id}")
async def api_update_document(doc_id: str, request: UpdateDocRequest, http_request: Request):
    """Update a document's content (and optionally title/tags)."""
    request.updated_by = _actor_name(http_request)
    def _update():
        tag_list = [t.strip() for t in request.tags.split(",") if t.strip()] if request.tags is not None else None
        return doc_store.update_doc(
            doc_id=doc_id,
            content=request.content,
            updated_by=request.updated_by.strip(),
            title=request.title.strip() if request.title else "",
            tags=tag_list,
        )
    result = await asyncio.to_thread(_update)
    if isinstance(result, str):
        return {"error": result}, 400
    return result


class PatchDocMetaRequest(BaseModel):
    updated_by: str
    title: str = ""
    tags: str | None = None
    related_entity_id: str | None = None


@app.patch("/api/apps/documents/{doc_id}")
async def api_patch_document_meta(doc_id: str, request: PatchDocMetaRequest, http_request: Request):
    """Update document metadata (title, tags, linked entity) without changing content."""
    request.updated_by = _actor_name(http_request)
    def _patch():
        tag_list = [t.strip() for t in request.tags.split(",") if t.strip()] if request.tags is not None else None
        entity_ref = None
        if request.related_entity_id is not None:
            entity_ref = "" if request.related_entity_id.strip().lower() == "none" else request.related_entity_id.strip()
        return doc_store.update_doc_meta(
            doc_id=doc_id,
            updated_by=request.updated_by.strip(),
            title=request.title.strip() if request.title else "",
            tags=tag_list,
            related_entity_id=entity_ref,
        )
    result = await asyncio.to_thread(_patch)
    if isinstance(result, str):
        return {"error": result}, 400
    return result


@app.delete("/api/apps/documents/{doc_id}")
async def api_delete_document(doc_id: str):
    """Delete a document permanently."""
    def _delete():
        ok = doc_store.delete_doc(doc_id)
        if ok:
            link_registry.delete_links_for_entity(doc_id)
        return ok
    ok = await asyncio.to_thread(_delete)
    if not ok:
        return {"error": "Document not found"}, 404
    return {"ok": True}


@app.get("/api/artifacts/for-entity/{entity_id}")
async def api_artifacts_for_entity(entity_id: str):
    """Get artifacts linked to a goal/project/task (metadata only, no content)."""
    def _fetch():
        from artifact_store import list_artifacts
        arts = list_artifacts(related_entity_id=entity_id)
        # Strip content from response to keep it lightweight
        for a in arts:
            a.pop("content", None)
        return arts
    arts = await asyncio.to_thread(_fetch)
    return {"artifacts": arts, "count": len(arts)}


@app.get("/api/artifacts/{artifact_id}")
async def api_get_artifact(artifact_id: str):
    """Get a single artifact with content."""
    def _fetch():
        from artifact_store import get_artifact_meta, get_artifact_content
        meta = get_artifact_meta(artifact_id)
        if not meta:
            return None
        content = get_artifact_content(artifact_id)
        if content:
            meta["content"] = content
        return meta
    art = await asyncio.to_thread(_fetch)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return art


@app.get("/api/apps/documents/for-entity/{entity_id}")
async def api_docs_for_entity(entity_id: str):
    """Get all documents linked to a goal/project/task."""
    def _fetch():
        linked_ids = link_registry.get_linked_ids(entity_id)
        doc_ids = [lid for lid in linked_ids if lid.startswith("d-")]
        docs = []
        for did in doc_ids:
            meta = doc_store.get_doc_meta(did)
            if meta:
                docs.append(meta)
        docs.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
        return docs
    docs = await asyncio.to_thread(_fetch)
    return {"documents": docs, "count": len(docs)}


class LinkDocRequest(BaseModel):
    entity_id: str
    created_by: str = ""


@app.post("/api/apps/documents/{doc_id}/link")
async def api_link_doc_to_entity(doc_id: str, request: LinkDocRequest, http_request: Request):
    """Link a document to a goal/project/task."""
    request.created_by = _actor_name(http_request)
    def _link():
        return link_registry.create_link(
            source_id=request.entity_id.strip(),
            target_id=doc_id,
            relation="has_doc",
            created_by=request.created_by.strip() if request.created_by else "",
        )
    result = await asyncio.to_thread(_link)
    if isinstance(result, str):
        return {"error": result}, 400
    return result


class UnlinkDocRequest(BaseModel):
    entity_id: str


@app.post("/api/apps/documents/{doc_id}/unlink")
async def api_unlink_doc_from_entity(doc_id: str, request: UnlinkDocRequest):
    """Remove the link between a document and an entity."""
    def _unlink():
        links = link_registry.get_links(doc_id)
        for link in links:
            pair = {link["source_id"], link["target_id"]}
            if pair == {doc_id, request.entity_id.strip()}:
                link_registry.delete_link(link["id"])
                return True
        return False
    ok = await asyncio.to_thread(_unlink)
    if not ok:
        return {"error": "Link not found"}, 404
    return {"ok": True}


# ---------------------------------------------------------------------------
# App API endpoints — Recipes
# Recipes routes are now provided by apps/recipes/routes.py (loaded by app_platform)
# ---------------------------------------------------------------------------

from data_layer import images as _dl_images


# ---------------------------------------------------------------------------
# App API endpoints — Item Locator
# Locator routes are now provided by apps/home/routes.py (loaded by app_platform)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# App API endpoints — Auto Maintenance
# Auto routes are now provided by apps/auto/routes.py (loaded by app_platform)
# ---------------------------------------------------------------------------


# Homeopathy routes are now provided by apps/homeopathy/routes.py (loaded by app_platform)


# Timeline routes are provided by apps/timeline/routes.py
# (auto-mounted by app_platform.loader at /api/apps/timeline).


# Image upload + management
import uuid as _uuid

UPLOAD_DIR = Path("uploads/images")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Upload hardening (audit #25): cap size, allowlist real image types by sniffing
# magic bytes, and derive the stored extension ourselves — never trust the
# client-supplied filename/extension or Content-Type.
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 15 MB


def _sniff_image_ext(data: bytes) -> str | None:
    """Return a safe extension if `data` is a recognized image, else None."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heif", b"hevc", b"mif1", b"heix"):
        return ".heic"
    return None


@app.get("/api/apps/images")
async def api_list_images():
    """List all image records ordered by newest first."""
    return await asyncio.to_thread(_dl_images.get_all_images)


@app.post("/api/apps/images/upload")
async def api_upload_image(request: Request):
    """Upload an image file. Accepts multipart form data.

    Optional linking params:
      recipe_id   — link to a recipe (legacy form field)
      entity_type — any entity_type registered via image_link_registry
                    (e.g. 'home_issue', 'auto_issue', 'meal', 'recipe').
                    Apps register their own handlers from handlers.py on load.
      entity_id   — the entity ID to link to
    """
    from fastapi.responses import JSONResponse
    from image_link_registry import link_image_to_entity, get_registered_entity_types

    form = await request.form()
    file = form.get("file")
    uploaded_by = form.get("uploaded_by", "")
    title = form.get("title", "")
    recipe_id = form.get("recipe_id", "")
    entity_type = form.get("entity_type", "")
    entity_id = form.get("entity_id", "")

    if not file:
        return JSONResponse({"error": "No file uploaded"}, status_code=400)

    # Legacy recipe_id form field maps to entity_type="recipe"
    if recipe_id and not entity_type:
        entity_type = "recipe"
        entity_id = recipe_id

    if entity_type and entity_id and entity_type not in get_registered_entity_types():
        return JSONResponse(
            {"error": f"No image link handler registered for entity_type '{entity_type}'. "
                      f"Registered: {get_registered_entity_types()}"},
            status_code=400,
        )

    # Read at most the cap + 1 byte so an oversized upload can't exhaust memory.
    contents = await file.read(MAX_IMAGE_BYTES + 1)
    if len(contents) > MAX_IMAGE_BYTES:
        return JSONResponse(
            {"error": f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit."},
            status_code=413,
        )

    # Validate it's actually an image by content, not by the client's extension
    # or Content-Type, and derive the stored extension ourselves.
    ext = _sniff_image_ext(contents)
    if not ext:
        return JSONResponse(
            {"error": "Unsupported file type — only JPEG/PNG/GIF/WebP/HEIC images are allowed."},
            status_code=415,
        )

    image_id = f"i-{_uuid.uuid4().hex[:8]}"
    storage_name = f"{image_id}{ext}"
    storage_path = UPLOAD_DIR / storage_name

    with open(storage_path, "wb") as f:
        f.write(contents)

    _mime_for_ext = {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
                     ".webp": "image/webp", ".heic": "image/heic"}
    image = {
        "id": image_id,
        "title": title or "",
        "filename": file.filename or "",
        "mime_type": _mime_for_ext.get(ext, "application/octet-stream"),
        "size_bytes": len(contents),
        "storage_path": f"uploads/images/{storage_name}",
        "uploaded_by": uploaded_by or "",
    }
    await asyncio.to_thread(_dl_images.save_image, image)

    if entity_type and entity_id:
        await link_image_to_entity(entity_type, entity_id, image_id)

    return _dl_images.get_image(image_id)


@app.get("/api/apps/images/{image_id}")
async def api_get_image_meta(image_id: str):
    img = await asyncio.to_thread(_dl_images.get_image, image_id)
    if not img:
        return {"error": "Image not found"}, 404
    return img


@app.get("/api/apps/images/{image_id}/file")
async def api_serve_image_by_id(image_id: str):
    """Serve an uploaded image by its image ID."""
    img = await asyncio.to_thread(_dl_images.get_image, image_id)
    if not img or not img.get("storage_path"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Image not found"}, status_code=404)
    path = Path(img["storage_path"])
    if not path.exists():
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(path)


@app.get("/uploads/images/{filename}")
async def api_serve_image(filename: str):
    """Serve uploaded image files."""
    path = UPLOAD_DIR / filename
    if not path.exists():
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(path)


class UpdateImageTitleRequest(BaseModel):
    title: str


@app.put("/api/apps/images/{image_id}")
async def api_update_image_title(image_id: str, request: UpdateImageTitleRequest):
    ok = await asyncio.to_thread(_dl_images.update_image_title, image_id, request.title.strip())
    if not ok:
        return {"error": "Image not found"}, 404
    return {"ok": True}


@app.delete("/api/apps/images/{image_id}")
async def api_delete_image(image_id: str):
    # Get storage path to delete file
    img = await asyncio.to_thread(_dl_images.get_image, image_id)
    if img and img.get("storage_path"):
        file_path = Path(img["storage_path"])
        if file_path.exists():
            file_path.unlink()
    ok = await asyncio.to_thread(_dl_images.delete_image, image_id)
    if not ok:
        return {"error": "Image not found"}, 404
    return {"ok": True}


# Recipe image link/unlink routes moved to apps/recipes/routes.py


# ---------------------------------------------------------------------------
# Investment Analyst routes moved to apps/investment/routes.py
# (auto-mounted by app platform loader at /api/apps/investment/)
# ---------------------------------------------------------------------------


# ── Job Queue API ──

@app.get("/api/jobs")
async def api_list_jobs(status: str = "", job_type: str = "", limit: int = 50,
                        user_id: str = ""):
    """List jobs with optional filters."""
    from app_platform.jobs import list_jobs, list_running
    if status == "running":
        return await asyncio.to_thread(list_running)
    return await asyncio.to_thread(list_jobs, status, job_type, limit)


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str, user_id: str = ""):
    """Get a specific job by ID."""
    from app_platform.jobs import get_job
    job = await asyncio.to_thread(get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: str, request: Request, user_id: str = ""):
    """Cancel a queued or running job."""
    from app_platform.jobs import cancel_job
    result = await asyncio.to_thread(cancel_job, job_id, _actor_name(request))
    if not result:
        raise HTTPException(status_code=404, detail="Job not found or already finished")
    return result


@app.get("/api/jobs/{job_id}/logs")
async def api_get_job_logs(job_id: str, after: int = 0, limit: int = 500,
                           user_id: str = ""):
    """Get log lines for a specific job. Supports polling via after=<last_id>."""
    from app_platform.jobs import get_logs
    return await asyncio.to_thread(get_logs, job_id, limit, after)


@app.post("/api/jobs/{job_id}/rerun")
async def api_rerun_job(job_id: str, request: Request, user_id: str = ""):
    """Re-run a completed/failed job by creating a new child job."""
    from app_platform.jobs import get_job
    from app_platform.jobs import submit_job
    original = await asyncio.to_thread(get_job, job_id)
    if not original:
        raise HTTPException(status_code=404, detail="Job not found")
    new_job = submit_job(
        job_type=original["job_type"],
        name=original["name"],
        config=original.get("config"),
        created_by=_actor_name(request) or original.get("created_by", ""),
        notify_user=original.get("notify_user", ""),
        description=original.get("description", ""),
    )
    return new_job


# Tools-browser routes moved to apps/tools/routes.py
# (auto-mounted by the loader at /api/apps/tools).


# ---------------------------------------------------------------------------
# App API endpoints — Reminders
# ---------------------------------------------------------------------------

@app.get("/api/apps/reminders")
async def api_list_reminders(request: Request, user_id: str = "", include_inactive: str = "false"):
    """List reminders for a user, or all reminders if user_id is empty."""
    user_id = scope_user(request, user_id)
    def _fetch():
        from app_platform.reminders import list_reminders as _list, _load_reminders
        inc = include_inactive.strip().lower() == "true"
        if user_id and user_id.strip():
            return _list(user_id.strip(), include_inactive=inc)
        else:
            all_r = _load_reminders()
            if not inc:
                all_r = [r for r in all_r if r.get("active", True)]
            return all_r
    reminders = await asyncio.to_thread(_fetch)
    return {"reminders": reminders, "count": len(reminders)}


@app.post("/api/apps/reminders/{reminder_id}/cancel")
async def api_cancel_reminder(reminder_id: str):
    """Cancel (deactivate) a reminder."""
    from app_platform.reminders import cancel_reminder as _cancel
    result = await asyncio.to_thread(_cancel, reminder_id)
    return {"ok": "not found" not in result.lower(), "message": result}


@app.patch("/api/apps/reminders/{reminder_id}")
async def api_modify_reminder(reminder_id: str, request: Request):
    """Modify a reminder (message, remind_at, recurrence, time_slot)."""
    from app_platform.reminders import modify_reminder as _modify
    body = await request.json()
    def _do():
        return _modify(
            reminder_id=reminder_id,
            message=body.get("message"),
            remind_at=body.get("remind_at"),
            recurrence=body.get("recurrence"),
            clear_recurrence=body.get("clear_recurrence", False),
            time_slot=body.get("time_slot"),
            clear_time_slot=body.get("clear_time_slot", False),
        )
    result = await asyncio.to_thread(_do)
    return {"ok": "not found" not in result.lower(), "message": result}


@app.post("/api/apps/reminders/{reminder_id}/reorder")
async def api_reorder_reminder(reminder_id: str, request: Request):
    """Move a reminder up or down in sort order."""
    import data_layer.reminders as _dl_rem
    body = await request.json()
    direction = body.get("direction", "down")
    user_id = body.get("user_id", "")
    active_only = body.get("active_only", True)
    ok = await asyncio.to_thread(
        _dl_rem.reorder_reminder, reminder_id, direction,
        user_id=user_id, active_only=active_only,
    )
    return {"ok": ok}


# ---------------------------------------------------------------------------
# App API endpoints — Prioritize
# ---------------------------------------------------------------------------

import app_platform.prioritize as _dl_prioritize


@app.get("/api/apps/prioritize/focus")
async def api_get_focus(request: Request, user_id: str = ""):
    """Get focus slots for a user. Also runs stale cleanup."""
    user_id = scope_user(request, user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    await asyncio.to_thread(_dl_prioritize.cleanup_stale_focus, user_id)
    slots = await asyncio.to_thread(_dl_prioritize.get_focus_slots, user_id)
    # Enrich each slot with the source item details
    for slot in slots:
        item = await asyncio.to_thread(_resolve_source_item, slot["source_type"], slot["source_id"])
        slot["item"] = item
    nag_enabled = await asyncio.to_thread(_dl_prioritize.get_focus_nag_enabled, user_id)
    return {"slots": slots, "focus_nag_enabled": nag_enabled}


@app.get("/api/apps/prioritize/family")
async def api_get_family_focus():
    """Get focus slots for all users."""
    import data_layer.users as _dl_users
    users = await asyncio.to_thread(_dl_users.get_all_users)
    result = []
    for u in users:
        uid = u["name"]
        await asyncio.to_thread(_dl_prioritize.cleanup_stale_focus, uid)
        slots = await asyncio.to_thread(_dl_prioritize.get_focus_slots, uid)
        for slot in slots:
            item = await asyncio.to_thread(_resolve_source_item, slot["source_type"], slot["source_id"])
            slot["item"] = item
        nag_on = await asyncio.to_thread(_dl_prioritize.get_focus_nag_enabled, uid)
        result.append({
            "user_id": uid,
            "display_name": u.get("display_name") or uid,
            "slots": slots,
            "focus_nag_enabled": nag_on,
        })
    return {"family": result}


@app.get("/api/apps/prioritize/backlog")
async def api_get_backlog(request: Request, user_id: str = ""):
    """Get all actionable items for a user, grouped by source app."""
    user_id = scope_user(request, user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    backlog = await asyncio.to_thread(_dl_prioritize.get_backlog, user_id)
    # Mark items that are already in focus
    focused_ids = {s["source_id"] for s in await asyncio.to_thread(_dl_prioritize.get_focus_slots, user_id)}
    # Mark flat groups
    for key in ("reminders", "nags", "auto_issues", "schedules", "todo"):
        for item in backlog.get(key, []):
            item["in_focus"] = item["source_id"] in focused_ids
    # Mark nested goals tree
    for goal in backlog.get("goals_tree", []):
        goal["in_focus"] = goal["source_id"] in focused_ids
        for proj in goal.get("projects", []):
            proj["in_focus"] = proj["source_id"] in focused_ids
            for task in proj.get("tasks", []):
                task["in_focus"] = task["source_id"] in focused_ids
    return backlog


class PromoteFocusRequest(BaseModel):
    user_id: str
    source_type: str
    source_id: str
    slot_number: int | None = None


@app.post("/api/apps/prioritize/focus")
async def api_promote_focus(request: PromoteFocusRequest, http_request: Request):
    """Promote an item to a focus slot."""
    request.user_id = scope_user(http_request, request.user_id)
    if request.slot_number:
        result = await asyncio.to_thread(
            _dl_prioritize.set_focus,
            request.user_id, request.slot_number, request.source_type, request.source_id,
        )
    else:
        result = await asyncio.to_thread(
            _dl_prioritize.promote_to_focus,
            request.user_id, request.source_type, request.source_id,
        )
    if not result:
        raise HTTPException(status_code=409, detail="All focus slots are full")
    return result


@app.delete("/api/apps/prioritize/focus/{slot_number}")
async def api_clear_focus(slot_number: int, request: Request, user_id: str = ""):
    """Remove an item from a focus slot."""
    user_id = scope_user(request, user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    ok = await asyncio.to_thread(_dl_prioritize.clear_focus, user_id, slot_number)
    return {"ok": ok}


class ReorderFocusRequest(BaseModel):
    user_id: str
    ordered_source_ids: list[str]


@app.post("/api/apps/prioritize/focus/reorder")
async def api_reorder_focus(request: ReorderFocusRequest, http_request: Request):
    """Reorder focus slots."""
    request.user_id = scope_user(http_request, request.user_id)
    ok = await asyncio.to_thread(
        _dl_prioritize.reorder_focus, request.user_id, request.ordered_source_ids,
    )
    return {"ok": ok}


@app.post("/api/apps/prioritize/nag-toggle")
async def api_toggle_focus_nag(request: Request):
    """Toggle focus nag for a user."""
    body = await request.json()
    user_id = scope_user(request, body.get("user_id", ""))
    enabled = body.get("enabled", True)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    ok = await asyncio.to_thread(_dl_prioritize.set_focus_nag_enabled, user_id, enabled)
    return {"ok": ok, "focus_nag_enabled": enabled}


def _resolve_source_item(source_type: str, source_id: str) -> dict:
    """Load a source item's display details for focus slot enrichment."""
    if source_type == "goal":
        from apps.goals.data import load_entity
        e = load_entity(source_id)
        return {"title": e["name"], "status": e["status"], "detail": e.get("target_date", "")} if e else {}
    elif source_type == "project":
        from apps.goals.data import load_entity
        e = load_entity(source_id)
        return {"title": e["name"], "status": e["status"], "priority": e.get("priority", ""),
                "detail": ""} if e else {}
    elif source_type == "task":
        from apps.goals.data import load_entity
        e = load_entity(source_id)
        if not e:
            return {}
        # Get project name
        proj_name = ""
        if e.get("project_id"):
            p = load_entity(e["project_id"])
            proj_name = p["name"] if p else ""
        return {"title": e["name"], "status": e["status"], "priority": e.get("priority", ""),
                "detail": proj_name, "due_date": e.get("due_date", "")}
    elif source_type in ("reminder", "nag"):
        from app_platform.reminders import get_reminder
        r = get_reminder(source_id)
        if not r:
            return {}
        return {"title": r["message"], "detail": r.get("remind_at", ""),
                "recurrence": r.get("recurrence") or "", "time_slot": r.get("time_slot", "")}
    elif source_type == "auto_issue":
        from apps.auto.data import get_issue
        issue = get_issue(source_id)
        if not issue:
            return {}
        return {"title": issue["title"], "severity": issue["severity"],
                "status": issue["status"], "detail": issue.get("vehicle_name", "")}
    elif source_type == "todo":
        from apps.lists.data import get_item
        item = get_item(source_id)
        if not item:
            return {}
        return {"title": item["text"], "detail": "To-Do list item"}
    return {}


# ---------------------------------------------------------------------------
# App API endpoints — Lists
# ---------------------------------------------------------------------------

from apps.lists.store import (
    get_all_lists as _get_all_lists,
    get_list as _get_list_by_id,
    find_list_by_name as _find_list_by_name,
    create_list as _create_list_store,
    delete_list as _delete_list_store,
    add_item as _add_list_item,
    remove_item as _remove_list_item,
    move_item as _move_list_item,
    update_item_text as _update_item_text,
    update_aliases as _update_list_aliases,
    sync_from_trello as _sync_list_from_trello,
    reorder_item as _reorder_list_item,
)


@app.get("/api/apps/lists")
async def api_list_lists(source: str = "", q: str = ""):
    """Get all lists, optionally filtered by source (board name) or search query."""
    def _fetch():
        # Exclude boards linked to projects (those are task columns, not general lists)
        try:
            from trello_task_sync import get_boards_linked_to_projects
            project_boards = get_boards_linked_to_projects()
        except Exception:
            project_boards = set()

        all_lists = _get_all_lists()
        results = []
        for lst in all_lists:
            board = (lst.get("trello") or {}).get("board", "") if lst.get("trello") else ""
            if board and board.lower() in project_boards:
                continue
            # Source filter
            if source:
                if source.lower() == "standalone" and lst.get("trello"):
                    continue
                if source.lower() != "standalone" and (not lst.get("trello") or board.lower() != source.lower()):
                    continue
            items = lst.get("items", [])
            active = [i for i in items if not i.get("archived")]
            archived = [i for i in items if i.get("archived")]
            # Search filter
            if q:
                query = q.strip().lower()
                name_match = query in lst["name"].lower()
                alias_match = any(query in a for a in lst.get("aliases", []))
                item_match = any(query in i["text"].lower() for i in active)
                if not (name_match or alias_match or item_match):
                    continue
            results.append({
                "id": lst["id"],
                "name": lst["name"],
                "aliases": lst.get("aliases", []),
                "trello": lst.get("trello"),
                "created_by": lst.get("created_by", ""),
                "created_at": lst.get("created_at", ""),
                "item_count": len(active),
                "archived_count": len(archived),
                "items": [{
                    "id": i["id"],
                    "text": i["text"],
                    "position": idx,
                    "trello_card_id": i.get("trello_card_id", ""),
                    "added_by": i.get("added_by", ""),
                    "added_at": i.get("added_at", ""),
                } for idx, i in enumerate(active)],
            })
        return results
    lists = await asyncio.to_thread(_fetch)
    # Collect unique boards for filter bubbles
    boards = sorted(set(
        (l.get("trello") or {}).get("board", "")
        for l in lists if l.get("trello")
    ))
    return {"lists": lists, "count": len(lists), "boards": boards}


@app.get("/api/apps/lists/{list_id}")
async def api_get_list(list_id: str):
    """Get a single list with all items."""
    def _fetch():
        lst = _get_list_by_id(list_id)
        if not lst:
            return None
        items = lst.get("items", [])
        active = [i for i in items if not i.get("archived")]
        archived = [i for i in items if i.get("archived")]
        return {
            "id": lst["id"],
            "name": lst["name"],
            "aliases": lst.get("aliases", []),
            "trello": lst.get("trello"),
            "created_by": lst.get("created_by", ""),
            "created_at": lst.get("created_at", ""),
            "item_count": len(active),
            "archived_count": len(archived),
            "items": [{
                "id": i["id"],
                "text": i["text"],
                "position": idx,
                "archived": False,
                "trello_card_id": i.get("trello_card_id", ""),
                "added_by": i.get("added_by", ""),
                "added_at": i.get("added_at", ""),
            } for idx, i in enumerate(active)],
            "archived_items": [{
                "id": i["id"],
                "text": i["text"],
                "archived": True,
            } for i in archived],
        }
    result = await asyncio.to_thread(_fetch)
    if not result:
        raise HTTPException(status_code=404, detail="List not found")
    return result


class CreateListRequest(BaseModel):
    name: str
    created_by: str
    trello_board: str = ""
    trello_list_name: str = ""


@app.post("/api/apps/lists")
async def api_create_list(req: CreateListRequest, http_request: Request):
    """Create a new list."""
    req.created_by = _actor_name(http_request)
    def _do():
        return _create_list_store(
            name=req.name.strip(),
            created_by=req.created_by.strip(),
            trello_board=req.trello_board.strip() if req.trello_board else "",
            trello_list_name=req.trello_list_name.strip() if req.trello_list_name else "",
        )
    result = await asyncio.to_thread(_do)
    return {"ok": True, "id": result["id"], "name": result["name"]}


@app.delete("/api/apps/lists/{list_id}")
async def api_delete_list(list_id: str):
    """Delete a list."""
    result = await asyncio.to_thread(_delete_list_store, list_id)
    if "not found" in result.lower():
        raise HTTPException(status_code=404, detail=result)
    return {"ok": True, "message": result}


class AddListItemRequest(BaseModel):
    text: str
    added_by: str


@app.post("/api/apps/lists/{list_id}/items")
async def api_add_list_item(list_id: str, req: AddListItemRequest):
    """Add an item to a list."""
    def _do():
        return _add_list_item(list_id, req.text.strip(), req.added_by.strip())
    result = await asyncio.to_thread(_do)
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)
    return {"ok": True, "item": result}


class UpdateListItemRequest(BaseModel):
    text: str


@app.patch("/api/apps/lists/{list_id}/items/{item_id}")
async def api_update_list_item(list_id: str, item_id: str, req: UpdateListItemRequest):
    """Update the text of a list item."""
    result = await asyncio.to_thread(_update_item_text, list_id, item_id, req.text.strip())
    if "not found" in result.lower():
        raise HTTPException(status_code=404, detail=result)
    return {"ok": True, "message": result}


@app.delete("/api/apps/lists/{list_id}/items/{item_id}")
async def api_remove_list_item(list_id: str, item_id: str):
    """Archive an item from a list."""
    result = await asyncio.to_thread(_remove_list_item, list_id, item_id)
    if "not found" in result.lower():
        raise HTTPException(status_code=404, detail=result)
    return {"ok": True, "message": result}


class UpdateAliasesRequest(BaseModel):
    aliases: list[str]


@app.patch("/api/apps/lists/{list_id}/aliases")
async def api_update_list_aliases(list_id: str, req: UpdateAliasesRequest):
    """Update aliases on a list."""
    result = await asyncio.to_thread(_update_list_aliases, list_id, req.aliases)
    if "not found" in result.lower():
        raise HTTPException(status_code=404, detail=result)
    return {"ok": True, "message": result}


class ReorderItemRequest(BaseModel):
    new_position: int


@app.patch("/api/apps/lists/{list_id}/items/{item_id}/position")
async def api_reorder_list_item(list_id: str, item_id: str, req: ReorderItemRequest):
    """Move an item to a new position within the list."""
    result = await asyncio.to_thread(_reorder_list_item, list_id, item_id, req.new_position)
    if "not found" in result.lower():
        raise HTTPException(status_code=404, detail=result)
    return {"ok": True, "message": result}


@app.post("/api/apps/lists/{list_id}/sync")
async def api_sync_list(list_id: str):
    """Force Trello sync on a list."""
    result = await asyncio.to_thread(_sync_list_from_trello, list_id)
    if "error" in result.lower():
        raise HTTPException(status_code=400, detail=result)
    return {"ok": True, "message": result}


# ---------------------------------------------------------------------------
# App API endpoints — To-Do
# ---------------------------------------------------------------------------

# Todo helpers — config CRUD lives in apps.todo.data, list+items joining
# helpers in apps.todo.store. Bundle into a SimpleNamespace so the
# existing `dl_todo.X` callsites in this file don't need to change.
from types import SimpleNamespace as _SimpleNamespace
from apps.todo import data as _dl_todo_data
from apps.todo import store as _dl_todo_store
dl_todo = _SimpleNamespace(
    get_config          = _dl_todo_data.get_config,
    upsert_config       = _dl_todo_data.upsert_config,
    get_all_configs     = _dl_todo_data.get_all_configs,
    ensure_default_list = _dl_todo_store.ensure_default_list,
    get_todo_items      = _dl_todo_store.get_todo_items,
    get_backlog_items   = _dl_todo_store.get_backlog_items,
)


@app.get("/api/apps/todo/config")
async def api_get_todo_config(request: Request, user_id: str = ""):
    """Get to-do config for a user.  Auto-creates default list if needed."""
    user_id = scope_user(request, user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    def _fetch():
        return dl_todo.ensure_default_list(user_id)
    cfg = await asyncio.to_thread(_fetch)
    # Also fetch the list name
    def _list_names():
        from apps.lists.data import get_list
        todo_name = ""
        backlog_name = ""
        if cfg.get("default_list_id"):
            lst = get_list(cfg["default_list_id"])
            todo_name = lst["name"] if lst else ""
        if cfg.get("backlog_list_id"):
            lst = get_list(cfg["backlog_list_id"])
            backlog_name = lst["name"] if lst else ""
        return todo_name, backlog_name
    todo_name, backlog_name = await asyncio.to_thread(_list_names)
    return {**cfg, "list_name": todo_name, "backlog_list_name": backlog_name}


class UpdateTodoConfigRequest(BaseModel):
    user_id: str
    default_list_id: str | None = None
    backlog_list_id: str | None = None
    nudge_enabled: bool | None = None
    nudge_day: str | None = None
    nudge_time: str | None = None
    show_on_calendar: bool | None = None


@app.put("/api/apps/todo/config")
async def api_update_todo_config(req: UpdateTodoConfigRequest, request: Request):
    """Update to-do config for a user."""
    req.user_id = scope_user(request, req.user_id)
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    def _update():
        return dl_todo.upsert_config(
            req.user_id,
            default_list_id=req.default_list_id,
            backlog_list_id=req.backlog_list_id,
            nudge_enabled=req.nudge_enabled,
            nudge_day=req.nudge_day,
            nudge_time=req.nudge_time,
            show_on_calendar=req.show_on_calendar,
        )
    cfg = await asyncio.to_thread(_update)
    return cfg


@app.get("/api/apps/todo/items")
async def api_get_todo_items(request: Request, user_id: str = "", include_archived: bool = False):
    """Get the user's default to-do list items."""
    user_id = scope_user(request, user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    def _fetch():
        # Ensure config exists first
        dl_todo.ensure_default_list(user_id)
        return dl_todo.get_todo_items(user_id, include_archived=include_archived)
    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"items": [], "list_id": "", "list_name": "", "count": 0}
    return result


@app.get("/api/apps/todo/backlog")
async def api_get_backlog_items(request: Request, user_id: str = "", include_archived: bool = False):
    """Get the user's backlog list items."""
    user_id = scope_user(request, user_id)
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    def _fetch():
        return dl_todo.get_backlog_items(user_id, include_archived=include_archived)
    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"items": [], "list_id": "", "list_name": "", "count": 0}
    return result


class AddTodoItemBacklogRequest(BaseModel):
    user_id: str
    text: str
    list_type: str = "todo"  # "todo" or "backlog"


@app.post("/api/apps/todo/items")
async def api_add_todo_item(req: AddTodoItemBacklogRequest, request: Request):
    """Add an item to the user's to-do or backlog list (at the top)."""
    req.user_id = scope_user(request, req.user_id)
    if not req.user_id or not req.text.strip():
        raise HTTPException(status_code=400, detail="user_id and text required")
    def _do():
        cfg = dl_todo.ensure_default_list(req.user_id)
        if req.list_type == "backlog":
            list_id = cfg.get("backlog_list_id")
            if not list_id:
                return None
        else:
            list_id = cfg["default_list_id"]
        # Use apps.lists.store.add_item for Trello write-through
        result = _add_list_item(list_id, req.text.strip(), req.user_id, position=0)
        if isinstance(result, str):
            return None  # error string
        return result
    item = await asyncio.to_thread(_do)
    if item is None:
        raise HTTPException(status_code=400, detail="No backlog list configured")
    return {"ok": True, "item": item}


class BatchReorderTodoRequest(BaseModel):
    user_id: str
    item_ids: list[str]
    list_type: str = "todo"  # "todo" or "backlog"


class MoveTodoItemRequest(BaseModel):
    user_id: str
    item_id: str
    direction: str  # "to_backlog" or "to_todo"


@app.post("/api/apps/todo/move-item")
async def api_move_todo_item(req: MoveTodoItemRequest, request: Request):
    """Move an item between to-do and backlog lists."""
    req.user_id = scope_user(request, req.user_id)
    if not req.user_id or not req.item_id:
        raise HTTPException(status_code=400, detail="user_id and item_id required")
    if req.direction not in ("to_backlog", "to_todo"):
        raise HTTPException(status_code=400, detail="direction must be 'to_backlog' or 'to_todo'")
    cfg = await asyncio.to_thread(dl_todo.get_config, req.user_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="No to-do config found")
    todo_id = cfg.get("default_list_id")
    backlog_id = cfg.get("backlog_list_id")
    if not todo_id or not backlog_id:
        raise HTTPException(status_code=400, detail="Both to-do and backlog lists must be configured")
    if req.direction == "to_backlog":
        from_id, to_id = todo_id, backlog_id
    else:
        from_id, to_id = backlog_id, todo_id
    result = await asyncio.to_thread(_move_list_item, from_id, req.item_id, to_id)
    if isinstance(result, str) and result.startswith("Error"):
        raise HTTPException(status_code=404, detail=result)
    return {"ok": True}


@app.post("/api/apps/todo/reorder")
async def api_batch_reorder_todo(req: BatchReorderTodoRequest, request: Request):
    """Batch reorder to-do items by providing the full ordered list of item IDs."""
    req.user_id = scope_user(request, req.user_id)
    if not req.user_id or not req.item_ids:
        raise HTTPException(status_code=400, detail="user_id and item_ids required")
    cfg = await asyncio.to_thread(dl_todo.get_config, req.user_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="No to-do config found")
    if req.list_type == "backlog":
        list_id = cfg.get("backlog_list_id")
        if not list_id:
            raise HTTPException(status_code=400, detail="No backlog list configured")
    else:
        list_id = cfg.get("default_list_id")
        if not list_id:
            raise HTTPException(status_code=404, detail="No default to-do list configured")
    from apps.lists.data import batch_reorder
    await asyncio.to_thread(batch_reorder, list_id, req.item_ids)
    # Trello write-through: sync card positions if list is Trello-backed
    def _trello_sync():
        from apps.lists.store import _load_list
        lst = _load_list(list_id)
        if not lst or not lst.get("trello"):
            return
        items = lst.get("items", [])
        # Build id→item lookup for Trello card IDs
        id_to_item = {it["id"]: it for it in items}
        ordered = [id_to_item[iid] for iid in req.item_ids if iid in id_to_item]
        trello_items = [it for it in ordered if it.get("trello_card_id")]
        if not trello_items:
            return
        try:
            from trello_client import _board_request, get_cards
            board = lst["trello"]["board"]
            trello_list = lst["trello"]["list_name"]
            # Assign evenly-spaced positions to all Trello-backed items in new order
            for i, it in enumerate(trello_items):
                target_pos = (i + 1) * 16384.0
                _board_request(
                    "PUT", f"/cards/{it['trello_card_id']}", board,
                    {"pos": str(target_pos)}
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("TODO reorder Trello sync failed: %s", e)
    await asyncio.to_thread(_trello_sync)
    return {"ok": True}


@app.get("/api/apps/todo/lists")
async def api_get_all_lists_for_todo(request: Request, user_id: str = ""):
    """Get lists owned by user (for config picker — choose default list)."""
    user_id = scope_user(request, user_id)
    def _fetch():
        from apps.lists.data import get_all_lists
        all_lists = get_all_lists()
        uid = user_id.lower().strip()
        result = []
        for l in all_lists:
            if uid and (l.get("created_by") or "").lower().strip() != uid:
                continue
            entry = {
                "id": l["id"],
                "name": l["name"],
                "item_count": len(l.get("items", [])),
            }
            if l.get("trello"):
                entry["trello_board"] = l["trello"].get("board", "")
            result.append(entry)
        result.sort(key=lambda x: ((x.get("trello_board") or "zzz").lower(), x["name"].lower()))
        return result
    lists = await asyncio.to_thread(_fetch)
    return {"lists": lists}


# ---------------------------------------------------------------------------
# App API endpoints — Brainstorming
# ---------------------------------------------------------------------------

import data_layer.brainstorming as dl_brainstorm


class CreateIdeaRequest(BaseModel):
    title: str
    summary: str = ""
    tags: list[str] = []
    priority: str = "medium"
    created_by: str = ""


class UpdateIdeaRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    status: str | None = None
    priority: str | None = None
    tags: list[str] | None = None
    project_id: str | None = None


class AddPartRequest(BaseModel):
    type: str = "document"
    title: str = ""
    content: str = ""
    meta: dict | None = None


class UpdatePartRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    meta: dict | None = None
    sort_order: int | None = None


@app.get("/api/apps/brainstorming")
async def api_list_ideas(status: str = "", tag: str = "", q: str = "", user: str = ""):
    """List ideas with optional filters."""
    return await asyncio.to_thread(dl_brainstorm.list_ideas, status, tag, q, user)


@app.post("/api/apps/brainstorming")
async def api_create_idea(req: CreateIdeaRequest, http_request: Request):
    """Create a new idea with a main document part."""
    req.created_by = _actor_name(http_request)
    result = await asyncio.to_thread(
        dl_brainstorm.create_idea, req.title, req.summary, req.tags, req.priority, req.created_by
    )
    return result


@app.get("/api/apps/brainstorming/{idea_id}")
async def api_get_idea(idea_id: str):
    """Get an idea with all its parts."""
    result = await asyncio.to_thread(dl_brainstorm.get_idea, idea_id)
    if not result:
        raise HTTPException(status_code=404, detail="Idea not found")
    return result


@app.put("/api/apps/brainstorming/{idea_id}")
async def api_update_idea(idea_id: str, req: UpdateIdeaRequest):
    """Update idea metadata."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    result = await asyncio.to_thread(dl_brainstorm.update_idea, idea_id, **fields)
    if not result:
        raise HTTPException(status_code=404, detail="Idea not found")
    return result


@app.delete("/api/apps/brainstorming/{idea_id}")
async def api_delete_idea(idea_id: str):
    """Delete an idea and all its parts."""
    deleted = await asyncio.to_thread(dl_brainstorm.delete_idea, idea_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Idea not found")
    return {"ok": True}


@app.post("/api/apps/brainstorming/{idea_id}/graduate")
async def api_graduate_idea(idea_id: str):
    """Graduate an idea to a project (placeholder — updates status)."""
    result = await asyncio.to_thread(dl_brainstorm.update_idea, idea_id, status="graduated")
    if not result:
        raise HTTPException(status_code=404, detail="Idea not found")
    return result


@app.post("/api/apps/brainstorming/{idea_id}/parts")
async def api_add_part(idea_id: str, req: AddPartRequest):
    """Add a new part to an idea."""
    result = await asyncio.to_thread(
        dl_brainstorm.add_part, idea_id, req.type, req.title, req.content, req.meta
    )
    if not result:
        raise HTTPException(status_code=404, detail="Idea not found or part creation failed")
    return result


@app.put("/api/apps/brainstorming/{idea_id}/parts/{part_id}")
async def api_update_part(idea_id: str, part_id: str, req: UpdatePartRequest):
    """Update a part's content or metadata."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    result = await asyncio.to_thread(dl_brainstorm.update_part, part_id, **fields)
    if not result:
        raise HTTPException(status_code=404, detail="Part not found")
    return result


@app.delete("/api/apps/brainstorming/{idea_id}/parts/{part_id}")
async def api_delete_part(idea_id: str, part_id: str):
    """Delete a part (cannot delete main doc)."""
    result = await asyncio.to_thread(dl_brainstorm.delete_part, part_id)
    if "error" in result.lower():
        raise HTTPException(status_code=400, detail=result)
    return {"ok": True, "message": result}


class AcceptEditRequest(BaseModel):
    content: str


@app.post("/api/apps/brainstorming/{idea_id}/parts/{part_id}/accept-edit")
async def api_accept_edit(idea_id: str, part_id: str, req: AcceptEditRequest):
    """Accept a proposed revision — saves the revised content to the part."""
    result = await asyncio.to_thread(dl_brainstorm.update_part, part_id, content=req.content)
    if not result:
        raise HTTPException(status_code=404, detail="Part not found")
    return result


# ---------------------------------------------------------------------------
# App API endpoints — Evolution Feed
# ---------------------------------------------------------------------------

import data_layer.evolution as dl_evolution


class CreateEvolutionItemRequest(BaseModel):
    type: str  # finding | proposal | question | goal | work_item | status_update
    title: str
    body: str
    impact: str | None = None
    effort: str | None = None
    category: str | None = None
    parent_id: str | None = None
    created_by: str = "skipper"


class UpdateEvolutionItemRequest(BaseModel):
    status: str | None = None
    title: str | None = None
    body: str | None = None
    impact: str | None = None
    effort: str | None = None
    category: str | None = None
    parent_id: str | None = None
    deferred_until: str | None = None
    meta: dict | None = None
    priority_pin: str | None = None


class AddThreadMessageRequest(BaseModel):
    author: str
    body: str


class TriggerEvolveRequest(BaseModel):
    cycle_type: str = "deep"  # deep | feedback | assessment | planning | vision


@app.get("/api/apps/evolve/items")
async def api_list_evolution_items(
    status: str = "",
    type: str = "",
    category: str = "",
    parent_id: str = "",
    include_completed: bool = False,
    limit: int = 100,
):
    """List evolution items with optional filters."""
    return {
        "items": await asyncio.to_thread(
            dl_evolution.list_items,
            status=status or None,
            item_type=type or None,
            category=category or None,
            parent_id=parent_id or None,
            include_completed=include_completed,
            limit=limit,
        )
    }


@app.post("/api/apps/evolve/items")
async def api_create_evolution_item(req: CreateEvolutionItemRequest, http_request: Request):
    """Create a new evolution item."""
    req.created_by = _actor_name(http_request)
    item = await asyncio.to_thread(
        dl_evolution.create_item,
        item_type=req.type,
        title=req.title,
        body=req.body,
        impact=req.impact,
        effort=req.effort,
        category=req.category,
        parent_id=req.parent_id,
        created_by=req.created_by,
    )
    return item


@app.get("/api/apps/evolve/items/{item_id}")
async def api_get_evolution_item(item_id: str):
    """Get an evolution item with its thread and children."""
    item = await asyncio.to_thread(dl_evolution.get_item_with_thread, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")
    return item


@app.put("/api/apps/evolve/items/{item_id}")
async def api_update_evolution_item(item_id: str, req: UpdateEvolutionItemRequest):
    """Update an evolution item's fields."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    item = await asyncio.to_thread(dl_evolution.update_item, item_id, **fields)
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")
    return item


@app.post("/api/apps/evolve/items/{item_id}/status/{status}")
async def api_set_evolution_status(item_id: str, status: str):
    """Set an evolution item's status (approve, redirect, defer, reject, etc.)."""
    valid = {"new", "reviewed", "approved", "redirected", "deferred",
             "rejected", "dismissed", "in_progress", "completed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    item = await asyncio.to_thread(dl_evolution.set_status, item_id, status)
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")
    return item


@app.delete("/api/apps/evolve/items/{item_id}")
async def api_delete_evolution_item(item_id: str):
    """Delete an evolution item and its threads."""
    deleted = await asyncio.to_thread(dl_evolution.delete_item, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Evolution item not found")
    return {"ok": True}


@app.get("/api/apps/evolve/items/{item_id}/thread")
async def api_get_evolution_thread(item_id: str):
    """Get all messages in an evolution item's conversation thread."""
    messages = await asyncio.to_thread(dl_evolution.get_thread, item_id)
    return {"messages": messages}


@app.post("/api/apps/evolve/items/{item_id}/thread")
async def api_add_thread_message(item_id: str, req: AddThreadMessageRequest):
    """Add a message to an evolution item's conversation thread."""
    item = await asyncio.to_thread(dl_evolution.get_item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")
    msg = await asyncio.to_thread(
        dl_evolution.add_thread_message, item_id, req.author, req.body
    )
    return msg


@app.get("/api/apps/evolve/stats")
async def api_evolution_stats():
    """Get Evolution Feed dashboard statistics."""
    return await asyncio.to_thread(dl_evolution.get_stats)


@app.get("/api/apps/evolve/items/{item_id}/children")
async def api_get_evolution_children(item_id: str):
    """Get all child items of an evolution item (hierarchy)."""
    children = await asyncio.to_thread(dl_evolution.get_children, item_id)
    return {"children": children}


class PriorityDirectiveRequest(BaseModel):
    text: str  # Free-text strategic guidance, e.g. "Focus on reliability before new features"


@app.get("/api/apps/evolve/priority-directives")
async def api_get_priority_directives():
    """Get the current strategic priority directives."""
    from domain_evolve import _load_working_memory
    wm = _load_working_memory()
    directives = wm.get("priority_directives")
    if isinstance(directives, dict):
        return directives
    elif directives:
        return {"text": str(directives)}
    return {"text": ""}


@app.put("/api/apps/evolve/priority-directives")
async def api_set_priority_directives(req: PriorityDirectiveRequest):
    """Set strategic priority directives (free-text guidance for ranking)."""
    from domain_evolve import _save_working_memory
    await _save_working_memory("priority_directives", {"text": req.text})
    return {"ok": True, "text": req.text}


@app.put("/api/apps/evolve/items/{item_id}/pin/{pin}")
async def api_set_priority_pin(item_id: str, pin: str):
    """Set a priority pin on an evolution item. Valid pins: top, high, low, bottom, lock, clear."""
    valid_pins = {"top", "high", "low", "bottom", "lock"}
    if pin == "clear":
        item = await asyncio.to_thread(dl_evolution.update_item, item_id, priority_pin=None)
    elif pin in valid_pins:
        item = await asyncio.to_thread(dl_evolution.update_item, item_id, priority_pin=pin)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid pin: {pin}. Use: top, high, low, bottom, lock, clear")
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")
    return item


class DiscussRequest(BaseModel):
    message: str
    author: str = "alice"


@app.post("/api/apps/evolve/items/{item_id}/discuss")
async def api_discuss_evolution_item(item_id: str, req: DiscussRequest):
    """Live discussion with Skipper about an evolution item.

    Saves the user message, calls the LLM with full item + thread context,
    saves Skipper's response, and returns it.
    """
    import agent_loop
    from config import SMART_MODEL

    # Load item
    item = await asyncio.to_thread(dl_evolution.get_item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")

    # Load thread history
    thread = await asyncio.to_thread(dl_evolution.get_thread, item_id)

    # Save user message first
    await asyncio.to_thread(
        dl_evolution.add_thread_message, item_id, req.author, req.message
    )

    # Build system prompt
    import os
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "evolve", "discuss.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        system_prompt = "You are Skipper, a helpful AI assistant. Discuss this evolution item with Alice."

    # Load parent goal if this is a proposal under a goal
    parent_context = ""
    if item.get("parent_id"):
        try:
            parent = await asyncio.to_thread(dl_evolution.get_item, item["parent_id"])
            if parent:
                parent_context = (
                    f"## Parent Goal: {parent['title']}\n"
                    f"- **Status:** {parent.get('status', '?')}\n"
                    f"- **Impact:** {parent.get('impact', '?')}\n"
                    f"- **Priority rank:** {parent.get('priority', 'unranked')}\n"
                    f"- **Category:** {parent.get('category', '?')}\n\n"
                    f"### Goal Description\n{parent.get('body', '(no description)')}\n\n"
                    f"---\n\n"
                )
        except Exception:
            pass

    # Build item context
    type_info = TYPE_LABELS_BACKEND.get(item.get("type", ""), item.get("type", "unknown"))
    item_context = parent_context + (
        f"## Item: {item['title']}\n"
        f"- **Type:** {type_info}\n"
        f"- **Status:** {item.get('status', '?')}\n"
        f"- **Impact:** {item.get('impact', '?')} | **Effort:** {item.get('effort', '?')}\n"
        f"- **Category:** {item.get('category', '?')}\n"
        f"- **Priority rank:** {item.get('priority', 'unranked')}\n\n"
        f"### Description\n{item.get('body', '(no description)')}\n"
    )

    # Build conversation history as messages
    messages = [{"role": "system", "content": system_prompt}]
    messages.append({"role": "user", "content": item_context})
    messages.append({"role": "assistant", "content": "I've reviewed the item. Let's discuss."})

    for msg in (thread or []):
        role = "assistant" if msg["author"] == "skipper" else "user"
        messages.append({"role": role, "content": msg["body"]})

    # Add the new user message
    messages.append({"role": "user", "content": req.message})

    # Call LLM
    result = await agent_loop.run(
        messages=messages,
        tools=[],
        model=SMART_MODEL,
        max_turns=1,
        tool_dispatch=None,
    )

    response_text = result.response_text or "I wasn't able to formulate a response."

    # Save Skipper's response to thread
    await asyncio.to_thread(
        dl_evolution.add_thread_message, item_id, "skipper", response_text
    )

    return {
        "response": response_text,
        "tokens": result.prompt_tokens + result.completion_tokens,
    }


TYPE_LABELS_BACKEND = {
    "goal": "Goal",
    "proposal": "Proposal",
    "finding": "Finding",
    "work_item": "Work Item",
    "question": "Question",
    "status_update": "Status Update",
}


class PromoteRequest(BaseModel):
    target_goal_id: str | None = None  # For proposals: which goal to create project under


@app.post("/api/apps/evolve/items/{item_id}/promote")
async def api_promote_evolution_item(item_id: str, req: PromoteRequest = PromoteRequest()):
    """Promote an evolution item to the Goals system.

    - Goal items → create a new goal in the goals system
    - Proposals → create a new project under a specified goal
    """
    import uuid
    from datetime import datetime
    from app_platform.time import get_timezone
    from apps.goals.data import save_entity

    item = await asyncio.to_thread(dl_evolution.get_item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evolution item not found")

    item_type = item.get("type", "")
    now = datetime.now(get_timezone()).isoformat()

    if item_type == "goal":
        goal_id = f"g-{uuid.uuid4().hex[:8]}"
        goal = {
            "id": goal_id,
            "name": item["title"],
            "owners": ["alice"],
            "collaborators": [],
            "target_date": "",
            "status": "not_started",
            "stack_rank": 0,
            "notes": item.get("body", ""),
            "definition_of_done": "",
            "history": [{"event": "promoted_from_evolve", "item_id": item_id, "at": now}],
            "artifacts": [],
            "created_by": "skipper",
            "created_at": now,
        }
        await asyncio.to_thread(save_entity, goal)

        # Update evolve item meta to link back
        meta = item.get("meta") or {}
        meta["promoted_to"] = goal_id
        await asyncio.to_thread(dl_evolution.update_item, item_id, meta=meta, status="approved")

        return {"ok": True, "promoted_to": goal_id, "type": "goal", "name": item["title"]}

    elif item_type in ("proposal", "work_item", "finding"):
        if not req.target_goal_id:
            # Return available goals so UI can ask user to pick one
            from apps.goals.data import list_entities
            all_goals = await asyncio.to_thread(list_entities, "g-")
            goals = [{"id": g["id"], "name": g["name"], "status": g.get("status", "")}
                     for g in all_goals]
            return {"needs_goal": True, "goals": goals}

        project_id = f"p-{uuid.uuid4().hex[:8]}"
        project = {
            "id": project_id,
            "name": item["title"],
            "goal_id": req.target_goal_id,
            "owners": ["alice"],
            "due_date": "",
            "priority": item.get("impact", "medium"),
            "status": "not_started",
            "stack_rank": 0,
            "notes": item.get("body", ""),
            "definition_of_done": "",
            "history": [{"event": "promoted_from_evolve", "item_id": item_id, "at": now}],
            "artifacts": [],
            "auto_nag": None,
            "trello": None,
            "pm_cadence_minutes": None,
            "created_by": "skipper",
            "created_at": now,
        }
        await asyncio.to_thread(save_entity, project)

        meta = item.get("meta") or {}
        meta["promoted_to"] = project_id
        await asyncio.to_thread(dl_evolution.update_item, item_id, meta=meta, status="approved")

        return {"ok": True, "promoted_to": project_id, "type": "project", "name": item["title"],
                "goal_id": req.target_goal_id}

    else:
        raise HTTPException(status_code=400, detail=f"Cannot promote item of type '{item_type}'")


@app.get("/api/apps/evolve/cycles")
async def api_evolve_cycles(limit: int = 5):
    """Get recent evolve cycles with full phase/unit progress tree."""
    from data_layer.db import fetch_all

    def _build_cycles():
        # Get recent cycles
        cycles = fetch_all(
            "SELECT * FROM jobs WHERE job_type = 'evolve_cycle' "
            "ORDER BY created_at DESC LIMIT %s", (limit,)
        )
        result = []
        for cycle in cycles:
            cycle_id = cycle["id"]
            config = cycle.get("config") or {}
            cycle_type = config.get("cycle_type", "unknown")

            # Get phases for this cycle
            phases = fetch_all(
                "SELECT * FROM jobs WHERE parent_job_id = %s "
                "AND job_type = 'evolve_phase' ORDER BY config->>'phase_index'",
                (cycle_id,)
            )

            phase_list = []
            for phase in phases:
                phase_id = phase["id"]
                phase_config = phase.get("config") or {}

                # Get unit counts by status for this phase
                unit_rows = fetch_all(
                    "SELECT status, COUNT(*) as cnt FROM jobs "
                    "WHERE parent_job_id = %s AND job_type = 'evolve_unit' "
                    "GROUP BY status", (phase_id,)
                )
                unit_counts = {r["status"]: r["cnt"] for r in unit_rows}
                total_units = sum(unit_counts.values())

                # Get synthesis findings (compact titles) for completed phases
                synthesis_findings = []
                if phase["status"] in ("completed", "failed"):
                    synth = fetch_all(
                        "SELECT output FROM jobs WHERE parent_job_id = %s "
                        "AND job_type = 'evolve_unit' "
                        "AND (config->>'is_synthesis')::boolean = true "
                        "AND status = 'completed' LIMIT 1",
                        (phase_id,)
                    )
                    if synth:
                        s_output = synth[0].get("output") or {}
                        if isinstance(s_output, str):
                            import json as _json
                            try: s_output = _json.loads(s_output)
                            except Exception: s_output = {}
                        for f in (s_output.get("findings") or [])[:20]:
                            synthesis_findings.append({
                                "title": f.get("title", f.get("summary", "Untitled")),
                                "impact": f.get("impact", ""),
                                "category": f.get("category", ""),
                                "type": f.get("type", ""),
                            })

                phase_list.append({
                    "id": phase_id,
                    "name": phase.get("name", ""),
                    "phase_key": phase_config.get("phase_key", ""),
                    "phase_index": phase_config.get("phase_index", 0),
                    "status": phase["status"],
                    "progress_pct": phase.get("progress_pct", 0),
                    "progress": phase.get("progress") or "",
                    "started_at": phase["started_at"].isoformat() if phase.get("started_at") else "",
                    "completed_at": phase["completed_at"].isoformat() if phase.get("completed_at") else "",
                    "total_units": total_units,
                    "units_completed": unit_counts.get("completed", 0),
                    "units_running": unit_counts.get("running", 0),
                    "units_queued": unit_counts.get("queued", 0),
                    "units_failed": unit_counts.get("failed", 0),
                    "synthesis_findings": synthesis_findings,
                })

            total_phases = len(phase_list)
            phases_done = sum(1 for p in phase_list if p["status"] in ("completed", "failed"))
            active_phase = next((p for p in phase_list if p["status"] == "running"), None)

            result.append({
                "id": cycle_id,
                "name": cycle.get("name", ""),
                "cycle_type": cycle_type,
                "status": cycle["status"],
                "created_at": cycle["created_at"].isoformat() if cycle.get("created_at") else "",
                "started_at": cycle["started_at"].isoformat() if cycle.get("started_at") else "",
                "completed_at": cycle["completed_at"].isoformat() if cycle.get("completed_at") else "",
                "total_phases": total_phases,
                "phases_done": phases_done,
                "active_phase": active_phase["name"] if active_phase else None,
                "phases": phase_list,
            })

        return result

    cycles = await asyncio.to_thread(_build_cycles)
    return {"cycles": cycles}


@app.get("/api/apps/evolve/phases/{phase_id}/units")
async def api_evolve_phase_units(phase_id: str):
    """Get all units for a phase with their findings — for drill-down."""
    from data_layer.db import fetch_all

    def _build():
        units = fetch_all(
            "SELECT id, name, status, config, output, error, "
            "started_at, completed_at FROM jobs "
            "WHERE parent_job_id = %s AND job_type = 'evolve_unit' "
            "ORDER BY created_at", (phase_id,)
        )
        result = []
        for u in units:
            config = u.get("config") or {}
            output = u.get("output") or {}
            if isinstance(output, str):
                import json as _json
                try: output = _json.loads(output)
                except Exception: output = {}

            findings = output.get("findings") or []
            # Compact each finding to title + summary + impact
            compact_findings = []
            for f in findings[:30]:
                # Build from structured fields (e.g. vision outputs)
                if f.get("relevance"):
                    title = f"Relevance: {f['relevance']}"
                    if f.get("priority_change") and f["priority_change"] != "unchanged":
                        title += f" (priority {f['priority_change']})"
                elif f.get("progress_summary"):
                    title = f.get("progress_summary", "")[:120]
                elif f.get("summary"):
                    title = f.get("summary", "")[:120]
                else:
                    # Last resort: first string value in the dict
                    for v in f.values():
                        if isinstance(v, str) and len(v) > 5:
                            title = v[:120]
                            break
                    else:
                        title = "Untitled"
                # Extract best summary
                summary = (
                    f.get("summary")
                    or f.get("body")
                    or f.get("progress_summary")
                    or f.get("description")
                    or f.get("family_impact")
                    or f.get("feasibility_notes")
                    or f.get("project_status")
                    or f.get("reason")
                    or ""
                )[:300]
                compact_findings.append({
                    "title": title,
                    "summary": summary,
                    "impact": f.get("impact", f.get("relevance", "")),
                    "category": f.get("category", ""),
                    "type": f.get("type", ""),
                    "action": f.get("action", f.get("priority_change", "")),
                })

            result.append({
                "id": u["id"],
                "name": u.get("name", ""),
                "status": u["status"],
                "is_synthesis": config.get("is_synthesis", False),
                "prompt_template": config.get("prompt_template", ""),
                "error": u.get("error") or "",
                "tokens_used": output.get("tokens_used", 0),
                "started_at": u["started_at"].isoformat() if u.get("started_at") else "",
                "completed_at": u["completed_at"].isoformat() if u.get("completed_at") else "",
                "findings": compact_findings,
                "response_preview": (output.get("response") or "")[:500],
            })
        return result

    units = await asyncio.to_thread(_build)
    return {"units": units}


@app.get("/api/apps/evolve/cycle-types")
async def api_evolve_cycle_types():
    """Get available cycle types with their phase definitions."""
    from domain_evolve import CYCLE_PHASES
    result = []
    descriptions = {
        "deep": "Full strategic analysis — audits everything, finds gaps, plans, and proposes items",
        "feedback": "Daily maintenance — processes your replies and reconciles active items",
        "assessment": "Audit-only — self-assessment + gap analysis without planning or proposing",
        "planning": "Planning cycle — takes existing findings and creates plans + proposals",
        "vision": "Vision-only — re-evaluates goals and explores opportunities",
        "solo_vision": "Solo — re-evaluate goals and ambitions, evolve vision items",
        "solo_assessment": "Solo — audit tools, apps, and domains against current state",
        "solo_gap": "Solo — compare specs to implementation, find deficiencies",
        "solo_planning": "Solo — create plans from existing findings and gap items",
        "solo_propose": "Solo — produce concrete work items from existing plans",
        "solo_reconcile": "Solo — check active items against reality, update statuses",
    }
    for ct, phases in CYCLE_PHASES.items():
        result.append({
            "type": ct,
            "description": descriptions.get(ct, ""),
            "phase_count": len(phases),
            "phases": [{"key": k, "name": n} for k, n in phases],
        })
    return {"cycle_types": result}


@app.post("/api/apps/evolve/trigger")
async def api_trigger_evolve_cycle(req: TriggerEvolveRequest):
    """Manually trigger an Evolve cycle."""
    from domain_evolve import CYCLE_PHASES
    if req.cycle_type not in CYCLE_PHASES:
        raise HTTPException(status_code=400, detail=f"Invalid cycle type: {req.cycle_type}. Valid: {list(CYCLE_PHASES.keys())}")
    try:
        from domain_evolve import _find_active_cycle
        active = await _find_active_cycle()
        if active:
            return {"ok": False, "error": "A cycle is already in progress", "cycle_id": active["id"]}

        from thinking_scheduler import get_budget_status
        budget = await get_budget_status()

        from domain_evolve import _start_cycle
        result = await _start_cycle(req.cycle_type, budget)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error("EVOLVE: Trigger failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# App API endpoints — Backups
# ---------------------------------------------------------------------------

import app_platform.backups as dl_backups


@app.get("/api/apps/backups")
async def api_list_backups():
    """List all backup records, most recent first."""
    def _fetch():
        backups = dl_backups.list_backups(limit=50)
        cfg = dl_backups.get_config()
        return {
            "backups": backups,
            "count": len(backups),
            "retention": int(cfg.get("retention") or 5),
            "network_path": cfg.get("filesystem_path") or "",
        }
    return await asyncio.to_thread(_fetch)


@app.get("/api/apps/backups/config")
async def api_backup_config():
    """Get current backup configuration.

    Returns every config key the manifest declares so the UI can render
    independent toggles + fields for each destination.
    """
    def _fetch():
        cfg = dl_backups.get_config()
        return {
            # Master switches
            "enabled": bool(cfg.get("enabled", True)),
            "cron": cfg.get("cron") or "0 2 * * *",
            "retention": int(cfg.get("retention") or 5),
            # Filesystem destination
            "filesystem_enabled": bool(cfg.get("filesystem_enabled", False)),
            "filesystem_path": cfg.get("filesystem_path") or "",
            # Google Drive destination — the service-account JSON is a secret
            # set via Settings → Backups (encrypted); never returned here. We
            # only report whether it's been configured.
            "gdrive_enabled": bool(cfg.get("gdrive_enabled", False)),
            "gdrive_credentials_set": _backups_settings.is_configured(
                "gdrive_service_account_json", scope="app:backups"),
            "gdrive_impersonate_email": cfg.get("gdrive_impersonate_email") or "",
        }
    from app_platform import settings as _backups_settings
    return await asyncio.to_thread(_fetch)


class BackupConfigPatchRequest(BaseModel):
    enabled: bool | None = None
    cron: str | None = None
    retention: int | None = None
    filesystem_enabled: bool | None = None
    filesystem_path: str | None = None
    gdrive_enabled: bool | None = None
    gdrive_impersonate_email: str | None = None


@app.patch("/api/apps/backups/config")
async def api_patch_backup_config(req: BackupConfigPatchRequest):
    """Patch any subset of backup config keys. Each destination toggles
    independently — clients send only the keys they want to change.
    """
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        return await asyncio.to_thread(dl_backups.get_config)
    return await asyncio.to_thread(dl_backups.set_config, updates, by="web")


# Backwards compatibility for the existing UI's simple enable/disable
# button. New UI code should PATCH /api/apps/backups/config directly.
class BackupEnabledRequest(BaseModel):
    enabled: bool


@app.patch("/api/apps/backups/enabled")
async def api_toggle_backup_enabled(req: BackupEnabledRequest):
    """Toggle the master switch in the app:backups config scope."""
    await asyncio.to_thread(dl_backups.set_config, {"enabled": req.enabled}, by="web")
    return {"ok": True, "enabled": req.enabled}


@app.get("/api/apps/backups/{backup_id}")
async def api_get_backup(backup_id: str):
    """Get a single backup record."""
    result = await asyncio.to_thread(dl_backups.get_backup, backup_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backup not found")
    return result


@app.post("/api/apps/backups/run")
async def api_run_backup():
    """Trigger an on-demand backup (ignores the master enabled switch)."""
    from app_platform.jobs import submit_job
    job = submit_job(
        "backup",
        config={"on_demand": True},
        created_by="web",
        notify_user="alice",
        description="On-demand backup",
    )
    return {"ok": True, "job_id": job["id"]}


@app.delete("/api/apps/backups/{backup_id}")
async def api_delete_backup(backup_id: str):
    """Delete a backup record and its filesystem destination files (if any)."""
    def _do():
        backup = dl_backups.get_backup(backup_id)
        if not backup:
            return None
        network_path = backup.get("network_path", "")
        if network_path and os.path.isdir(network_path):
            import shutil
            try:
                shutil.rmtree(network_path)
            except Exception as e:
                logger.warning("Failed to delete backup files at %s: %s", network_path, e)
        dl_backups.delete_backup(backup_id)
        return backup
    result = await asyncio.to_thread(_do)
    if not result:
        raise HTTPException(status_code=404, detail="Backup not found")
    return {"ok": True, "message": f"Backup {backup_id} deleted"}


# System metrics route moved to apps/system/routes.py
# (auto-mounted by the loader at /api/apps/system/metrics).


# Issues routes provided by apps/issues/routes.py


# ---------------------------------------------------------------------------
# App API endpoints — Schedules
# ---------------------------------------------------------------------------

import app_platform.schedules as _dl_schedules


class CreateScheduleRequest(BaseModel):
    title: str
    created_by: str = ""
    category: str = "general"
    assigned_to: str = ""
    description: str = ""
    recurrence_type: str = "weekly"
    recurrence_rule: dict | None = None
    time_of_day: str | None = None
    duration_mins: int | None = None
    usage_metric: str | None = None
    usage_interval: int | None = None
    linked_entity_id: str | None = None
    linked_entity_type: str | None = None
    reminder_mins: int | None = None   # None → use Settings → Schedules default_reminder_minutes
    notify_channel: str = "both"


class UpdateScheduleRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    assigned_to: str | None = None
    recurrence_type: str | None = None
    recurrence_rule: dict | None = None
    time_of_day: str | None = None
    duration_mins: int | None = None
    usage_metric: str | None = None
    usage_interval: int | None = None
    linked_entity_id: str | None = None
    linked_entity_type: str | None = None
    reminder_mins: int | None = None
    notify_channel: str | None = None
    active: bool | None = None
    next_due: str | None = None


class CompleteScheduleRequest(BaseModel):
    completed_by: str = ""
    notes: str = ""
    usage_value: int | None = None


@app.get("/api/apps/schedules")
async def api_list_schedules(category: str = "", assigned_to: str = "", active_only: bool = True):
    def _fetch():
        return _dl_schedules.list_schedules(
            category=category or None,
            assigned_to=assigned_to or None,
            active_only=active_only,
        )
    schedules = await asyncio.to_thread(_fetch)
    return {"schedules": schedules, "count": len(schedules)}


@app.post("/api/apps/schedules")
async def api_create_schedule(req: CreateScheduleRequest, http_request: Request):
    req.created_by = _actor_name(http_request)
    def _create():
        return _dl_schedules.create_schedule(
            title=req.title,
            created_by=req.created_by,
            category=req.category,
            assigned_to=req.assigned_to,
            description=req.description,
            recurrence_type=req.recurrence_type,
            recurrence_rule=req.recurrence_rule,
            time_of_day=req.time_of_day,
            duration_mins=req.duration_mins,
            usage_metric=req.usage_metric,
            usage_interval=req.usage_interval,
            linked_entity_id=req.linked_entity_id,
            linked_entity_type=req.linked_entity_type,
            reminder_mins=req.reminder_mins,
            notify_channel=req.notify_channel,
        )
    schedule = await asyncio.to_thread(_create)
    return {"ok": True, "schedule": schedule}


@app.get("/api/apps/calendar/events")
async def api_calendar_events(from_date: str = "", to_date: str = "", assigned_to: str = ""):
    """Aggregated calendar events from all sources: schedules, reminders, tasks, auto service, nags."""
    if not from_date or not to_date:
        from datetime import date as _date, timedelta as _td
        today = _date.today()
        first = today.replace(day=1)
        if today.month == 12:
            last = today.replace(year=today.year + 1, month=1, day=1) - _td(days=1)
        else:
            last = today.replace(month=today.month + 1, day=1) - _td(days=1)
        from_date = from_date or first.isoformat()
        to_date = to_date or last.isoformat()

    import data_layer.calendar as _dl_cal

    def _fetch():
        return _dl_cal.get_aggregated_events(
            from_date=from_date,
            to_date=to_date,
            assigned_to=assigned_to or None,
        )
    events = await asyncio.to_thread(_fetch)
    return {"events": events, "count": len(events), "from": from_date, "to": to_date}


@app.get("/api/apps/schedules/events")
async def api_schedule_events(from_date: str = "", to_date: str = "", assigned_to: str = "", category: str = ""):
    """Expand schedules into per-day calendar events for a date range."""
    if not from_date or not to_date:
        from datetime import date, timedelta
        today = date.today()
        first = today.replace(day=1)
        # Default to current month
        if today.month == 12:
            last = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        from_date = from_date or first.isoformat()
        to_date = to_date or last.isoformat()

    def _fetch():
        return _dl_schedules.get_calendar_events(
            from_date=from_date,
            to_date=to_date,
            assigned_to=assigned_to or None,
            category=category or None,
        )
    events = await asyncio.to_thread(_fetch)
    return {"events": events, "count": len(events), "from": from_date, "to": to_date}


@app.get("/api/apps/schedules/due")
async def api_due_schedules(assigned_to: str = "", days_ahead: int = 7):
    def _fetch():
        return _dl_schedules.get_due_schedules(
            assigned_to=assigned_to or None,
            days_ahead=days_ahead,
        )
    schedules = await asyncio.to_thread(_fetch)
    return {"schedules": schedules, "count": len(schedules)}


@app.get("/api/apps/schedules/{schedule_id}")
async def api_get_schedule(schedule_id: str):
    def _fetch():
        sch = _dl_schedules.get_schedule(schedule_id)
        if not sch:
            return {"error": f"Schedule {schedule_id} not found"}
        sch["completions"] = _dl_schedules.get_completions(schedule_id, limit=10)
        sch["recurrence_summary"] = _dl_schedules.describe_recurrence(
            sch["recurrence_type"], sch["recurrence_rule"]
        )
        return sch
    return await asyncio.to_thread(_fetch)


@app.patch("/api/apps/schedules/{schedule_id}")
async def api_update_schedule(schedule_id: str, req: UpdateScheduleRequest):
    def _update():
        kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
        # Parse next_due string into a timezone-aware datetime
        if "next_due" in kwargs and isinstance(kwargs["next_due"], str):
            from dateutil.parser import parse as _dtparse
            from app_platform.time import get_timezone
            dt = _dtparse(kwargs["next_due"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=get_timezone())
            kwargs["next_due"] = dt
        return _dl_schedules.update_schedule(schedule_id, **kwargs)
    result = await asyncio.to_thread(_update)
    if not result:
        return {"error": f"Schedule {schedule_id} not found"}
    return {"ok": True, "schedule": result}


@app.delete("/api/apps/schedules/{schedule_id}")
async def api_delete_schedule(schedule_id: str):
    await asyncio.to_thread(_dl_schedules.delete_schedule, schedule_id)
    return {"ok": True}


@app.post("/api/apps/schedules/{schedule_id}/complete")
async def api_complete_schedule(schedule_id: str, req: CompleteScheduleRequest, http_request: Request):
    req.completed_by = _actor_name(http_request)
    def _complete():
        return _dl_schedules.complete_schedule(
            schedule_id=schedule_id,
            completed_by=req.completed_by,
            notes=req.notes,
            usage_value=req.usage_value,
        )
    result = await asyncio.to_thread(_complete)
    if not result:
        return {"error": f"Schedule {schedule_id} not found"}
    return {"ok": True, "schedule": result}


# ── Folders App ──
import app_platform.folders as _folder_store


class FolderCreateRequest(BaseModel):
    name: str
    owner: str = ""
    parent_folder_id: str = ""
    related_entity_id: str = ""
    description: str = ""
    icon: str = "folder"
    color: str = ""
    tags: list[str] = []


class FolderUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    owner: str | None = None
    parent_folder_id: str | None = None
    icon: str | None = None
    color: str | None = None
    tags: list[str] | None = None


class FolderAddItemRequest(BaseModel):
    entity_id: str


class FolderNewDocRequest(BaseModel):
    title: str
    content: str = ""
    tags: list[str] = []


class FolderReorderRequest(BaseModel):
    entity_ids: list[str]


@app.get("/api/apps/folders")
async def api_list_folders(owner: str = "", root_only: bool = True):
    folders = await asyncio.to_thread(_folder_store.list_folders, owner=owner, root_only=root_only)
    return {"folders": folders}


@app.get("/api/apps/folders/tree")
async def api_folder_tree(owner: str = ""):
    tree = await asyncio.to_thread(_folder_store.get_full_tree, owner=owner)
    return {"tree": tree}


@app.get("/api/apps/folders/search")
async def api_search_folders(q: str = ""):
    if not q.strip():
        return {"folders": []}
    folders = await asyncio.to_thread(_folder_store.search_folders, q.strip())
    return {"folders": folders}


@app.post("/api/apps/folders")
async def api_create_folder(req: FolderCreateRequest):
    try:
        folder = await asyncio.to_thread(
            _folder_store.create_folder,
            name=req.name,
            created_by="web",
            owner=req.owner,
            parent_folder_id=req.parent_folder_id,
            related_entity_id=req.related_entity_id,
            description=req.description,
            icon=req.icon,
            color=req.color,
            tags=req.tags,
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={"error": str(e)})
    return folder


@app.get("/api/apps/folders/{folder_id}")
async def api_get_folder(folder_id: str):
    detail = await asyncio.to_thread(_folder_store.get_folder_detail, folder_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Folder not found")
    return detail


@app.patch("/api/apps/folders/{folder_id}")
async def api_update_folder(folder_id: str, req: FolderUpdateRequest):
    kwargs = {k: v for k, v in req.dict().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")
    folder = await asyncio.to_thread(
        _folder_store.update_folder, folder_id, updated_by="web", **kwargs
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@app.delete("/api/apps/folders/{folder_id}")
async def api_delete_folder(folder_id: str):
    ok = await asyncio.to_thread(_folder_store.delete_folder, folder_id, deleted_by="web")
    if not ok:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"ok": True}


@app.post("/api/apps/folders/{folder_id}/items")
async def api_add_folder_item(folder_id: str, req: FolderAddItemRequest):
    result = await asyncio.to_thread(
        _folder_store.add_item, folder_id, req.entity_id, added_by="web"
    )
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.delete("/api/apps/folders/{folder_id}/items/{entity_id}")
async def api_remove_folder_item(folder_id: str, entity_id: str):
    ok = await asyncio.to_thread(
        _folder_store.remove_item, folder_id, entity_id, removed_by="web"
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found in folder")
    return {"ok": True}


@app.put("/api/apps/folders/{folder_id}/reorder")
async def api_reorder_folder_items(folder_id: str, req: FolderReorderRequest):
    await asyncio.to_thread(_folder_store.reorder_items, folder_id, req.entity_ids)
    return {"ok": True}


@app.post("/api/apps/folders/{folder_id}/new-doc")
async def api_create_doc_in_folder(folder_id: str, req: FolderNewDocRequest):
    result = await asyncio.to_thread(
        _folder_store.create_doc_in_folder,
        folder_id=folder_id,
        title=req.title,
        created_by="web",
        content=req.content,
        tags=req.tags,
    )
    if isinstance(result, str):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/apps/folders/containing/{entity_id}")
async def api_folders_containing(entity_id: str):
    folders = await asyncio.to_thread(_folder_store.get_folders_containing, entity_id)
    return {"folders": folders}


# ── Thinking App ──
import data_layer.skipper_state as _dl_state
import data_layer.thinking_domains as _dl_domains
import data_layer.thinking_log as _dl_tlog


@app.get("/api/apps/thinking/state")
async def api_thinking_state(
    domain: str | None = None,
    state_type: str | None = None,
    status: str | None = "active",
    subject_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    states = await asyncio.to_thread(
        _dl_state.list_states,
        domain=domain, state_type=state_type,
        status=status, subject_id=subject_id,
        limit=min(limit, 200), offset=offset,
    )
    return {"states": states, "count": len(states)}


@app.get("/api/apps/thinking/state/{state_id}")
async def api_thinking_state_detail(state_id: str):
    state = await asyncio.to_thread(_dl_state.get_state, state_id)
    if not state:
        return {"error": "State entry not found"}
    return state


@app.get("/api/apps/thinking/log")
async def api_thinking_log(
    domain: str | None = None,
    trigger: str | None = None,
    date: str | None = None,
    days: int = 1,
    limit: int = 50,
    offset: int = 0,
):
    entries = await asyncio.to_thread(
        _dl_tlog.list_log_entries,
        domain=domain, trigger=trigger,
        date=date, days=min(days, 30),
        limit=min(limit, 200), offset=offset,
    )
    return {"entries": entries, "count": len(entries)}


@app.get("/api/apps/thinking/log/{log_id}")
async def api_thinking_log_detail(log_id: str):
    entry = await asyncio.to_thread(_dl_tlog.get_log_entry, log_id)
    if not entry:
        return {"error": "Log entry not found"}
    return entry


@app.get("/api/apps/thinking/budget")
async def api_thinking_budget(domain: str | None = None):
    usage = await asyncio.to_thread(_dl_tlog.get_today_token_usage, domain=domain)
    from thinking_scheduler import DAILY_TOKEN_BUDGET
    usage["budget"] = DAILY_TOKEN_BUDGET
    usage["usage_pct"] = round(usage.get("total_tokens", 0) / DAILY_TOKEN_BUDGET * 100, 1) if DAILY_TOKEN_BUDGET else 0
    # Per-domain breakdown
    by_domain = await asyncio.to_thread(_dl_tlog.get_today_usage_by_domain)
    usage["by_domain"] = by_domain
    # OpenAI actual cost (best-effort, non-blocking)
    usage["daily_cost_usd"] = await _fetch_openai_daily_cost()
    return usage


async def _fetch_openai_daily_cost() -> float | None:
    """Query OpenAI Organization Costs API for today's spend. Returns USD or None on failure."""
    import os, requests
    from datetime import datetime, timezone
    from app_platform import settings as _settings
    admin_key = _settings.get("openai_admin_key", scope="platform", secret=True)
    if not admin_key:
        return None
    try:
        now = datetime.now(timezone.utc)
        start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())
        resp = await asyncio.to_thread(
            lambda: requests.get(
                "https://api.openai.com/v1/organization/costs",
                headers={"Authorization": f"Bearer {admin_key}"},
                params={"start_time": start, "bucket_width": "1d"},
                timeout=10,
            )
        )
        if resp.status_code != 200:
            logger.warning("OpenAI costs API returned %d: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        total = 0.0
        for bucket in data.get("data", []):
            for result in bucket.get("results", []):
                amt = result.get("amount", {})
                total += float(amt.get("value", 0))
        return round(total, 4)
    except Exception as e:
        logger.debug("OpenAI costs fetch failed: %s", e)
        return None


@app.get("/api/apps/thinking/domains")
async def api_thinking_domains(enabled_only: bool = True):
    domains = await asyncio.to_thread(_dl_domains.list_domains, enabled_only=enabled_only)
    return {"domains": domains}


class DomainUpdateRequest(BaseModel):
    enabled: bool | None = None
    budget_priority: str | None = None


@app.patch("/api/apps/thinking/domains/{name}")
async def api_thinking_domain_update(name: str, body: DomainUpdateRequest):
    # Chat is a priority-0 domain — cannot be disabled
    if name == "chat" and body.enabled is False:
        raise HTTPException(status_code=400, detail="Chat domain cannot be disabled")
    kwargs = {k: v for k, v in body.dict().items() if v is not None}
    if not kwargs:
        return {"error": "No fields to update"}, 400
    updated = await asyncio.to_thread(_dl_domains.update_domain, name, **kwargs)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Domain '{name}' not found")
    return updated


@app.get("/api/apps/thinking/dispatch")
async def api_thinking_dispatch():
    """Current dispatch status — what's running, chat preemption, domain tasks."""
    from thinking_scheduler import get_dispatch_status
    return get_dispatch_status()


# Email routes are now provided by apps/email/routes.py (loaded by app_platform)


# ── Behaviors API ──
import app_platform.behaviors as _dl_behaviors


class BehaviorCreateRequest(BaseModel):
    trigger_description: str
    action_description: str
    created_by: str
    scope: str = "user"
    notes: str = ""


class BehaviorUpdateRequest(BaseModel):
    trigger_description: str | None = None
    action_description: str | None = None
    scope: str | None = None
    notes: str | None = None


@app.get("/api/behaviors")
async def api_list_behaviors(user_id: str = "", scope: str = ""):
    behaviors = await asyncio.to_thread(
        _dl_behaviors.list_behaviors,
        user_id=user_id or None,
        scope=scope or None,
    )
    return {"behaviors": behaviors}


@app.post("/api/behaviors")
async def api_create_behavior(req: BehaviorCreateRequest, http_request: Request):
    req.created_by = _actor_name(http_request)
    behavior = await asyncio.to_thread(
        _dl_behaviors.create_behavior,
        trigger_description=req.trigger_description,
        action_description=req.action_description,
        created_by=req.created_by,
        scope=req.scope,
        notes=req.notes,
    )
    return behavior


@app.patch("/api/behaviors/{behavior_id}")
async def api_update_behavior(behavior_id: str, req: BehaviorUpdateRequest):
    updated = await asyncio.to_thread(
        _dl_behaviors.update_behavior,
        behavior_id=behavior_id,
        trigger_description=req.trigger_description,
        action_description=req.action_description,
        scope=req.scope,
        notes=req.notes,
    )
    if not updated:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Behavior not found")
    return updated


@app.post("/api/behaviors/{behavior_id}/toggle")
async def api_toggle_behavior(behavior_id: str):
    result = await asyncio.to_thread(_dl_behaviors.toggle_behavior, behavior_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Behavior not found")
    return result


@app.delete("/api/behaviors/{behavior_id}")
async def api_delete_behavior(behavior_id: str):
    deleted = await asyncio.to_thread(_dl_behaviors.delete_behavior, behavior_id)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Behavior not found")
    return {"ok": True}


# ── Admin endpoints ──

@app.get("/api/admin/status")
async def api_admin_status():
    """Return agent status including shutdown state and uptime."""
    from thinking_scheduler import is_shutting_down, get_dispatch_status
    from app_platform.jobs import get_active_job_ids
    dispatch = get_dispatch_status()
    return {
        "build_id": BUILD_ID,
        "uptime_seconds": int(time.time()) - int(BUILD_ID),
        "shutting_down": is_shutting_down(),
        "active_dispatches": len(dispatch.get("active_dispatches", [])),
        "active_jobs": len(get_active_job_ids()),
        "env": os.getenv("SKIPPER_ENV", "prod"),
    }


async def _drain_and_exit(max_wait: int = 30, deploy: bool = False):
    """Background task: wait for in-flight work to finish, then force-exit.

    Runs detached from the HTTP request so the client gets a response
    immediately and Ctrl+C is not blocked by the drain loop.

    When *deploy* is True, a ``.deploy_pending`` sentinel is written just before
    exit so the host deploy watcher (scripts/deploy_watcher.sh) runs
    ``git pull`` + a rebuild + recycle (``docker compose up -d --build``). With
    no watcher installed it's a no-op and ``restart: always`` just bounces the
    container (a plain restart). Deploy is the deliberate, heavier path; the UI
    restart button uses ``/api/admin/restart`` (deploy=False) instead.
    """
    import threading
    from thinking_scheduler import get_dispatch_status
    from app_platform.jobs import get_active_job_ids

    start = time.time()
    while time.time() - start < max_wait:
        dispatch = get_dispatch_status()
        active = [d for d in dispatch.get("active_dispatches", []) if d["domain"] != "chat"]
        active_jobs = get_active_job_ids()

        if not active and not active_jobs:
            logger.info("ADMIN: All in-flight work drained \u2014 shutting down")
            break

        dispatch_names = [d.get("domain", "?") for d in active]
        all_pending = dispatch_names + list(active_jobs)
        logger.info("ADMIN: Waiting for %d in-flight items (%.0fs elapsed): %s",
                     len(all_pending), time.time() - start, ", ".join(all_pending))
        await asyncio.sleep(3)
    else:
        logger.warning("ADMIN: Drain timeout after %ds \u2014 forcing shutdown", max_wait)

    def _do_exit():
        if deploy:
            try:
                sentinel = Path(__file__).resolve().parent / ".deploy_pending"
                sentinel.write_text(f"deploy requested at {int(time.time())}\n", encoding="utf-8")
                logger.info("ADMIN: wrote deploy sentinel %s", sentinel)
            except Exception:
                logger.warning("ADMIN: could not write deploy sentinel", exc_info=True)
        logger.info("ADMIN: Exiting with code 42 (%s signal)", "deploy" if deploy else "restart")
        os._exit(42)

    threading.Timer(1.0, _do_exit).start()


@app.post("/api/admin/restart")
async def api_admin_restart(request: Request):
    """Graceful restart: signal shutdown, drain in background, then exit with code 42.

    Returns immediately — drain runs as a background task so the HTTP response
    is not held open and Ctrl+C remains responsive.
    A wrapper script (run-agent.ps1) sees exit code 42 and restarts the process.
    """
    if not _is_admin_req(request):
        return JSONResponse({"ok": False, "error": "Admin access required."}, status_code=403)
    from thinking_scheduler import request_shutdown as thinking_shutdown, is_shutting_down
    from app_platform.jobs import request_shutdown as jobs_shutdown
    from apps.reminders.scheduler import request_shutdown as reminders_shutdown

    if is_shutting_down():
        return {"status": "already_shutting_down"}

    thinking_shutdown()
    jobs_shutdown()
    reminders_shutdown()
    logger.info("ADMIN: Graceful restart requested \u2014 draining in-flight work (max 30s)")

    # Notify connected clients
    await manager.broadcast({"type": "server_restarting"})

    # Drain + exit runs in the background — response returns immediately
    asyncio.create_task(_drain_and_exit(max_wait=30))

    return {"status": "restarting", "message": "Agent will restart shortly (draining in background)"}


@app.get("/api/apps/{app_id}/help")
async def api_app_help(app_id: str):
    """User-facing help doc for an app's in-app Help panel.

    Serves apps/<id>/help.md (markdown). app_id is validated against the loaded
    apps (so it can't traverse the filesystem). Returns an empty `help` string
    when the app hasn't shipped a help.md yet — the UI shows a placeholder."""
    from app_platform.loader import get_loaded_apps
    manifest = get_loaded_apps().get(app_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Unknown app")
    help_path = Path(__file__).resolve().parent / "apps" / app_id / "help.md"
    text = ""
    if help_path.is_file():
        try:
            text = help_path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("could not read help.md for %s", app_id, exc_info=True)
    return {"app_id": app_id, "name": manifest.name, "help": text}


@app.post("/api/admin/deploy")
async def api_admin_deploy(request: Request):
    """Graceful deploy: drain in-flight work, then signal the host deploy
    watcher (option B) to `git pull` + rebuild + recycle the stack. The agent
    never gets host/docker control — it only writes a sentinel;
    scripts/deploy_watcher.sh on the host does the pull + `docker compose up -d
    --build`. This is the deliberate update path (used by the deploy_skipper
    flow); the UI restart button uses /api/admin/restart, not this. If no watcher
    is installed, `restart: always` just bounces the container (a plain restart,
    no code update)."""
    if not _is_admin_req(request):
        return JSONResponse({"ok": False, "error": "Admin access required."}, status_code=403)
    from thinking_scheduler import request_shutdown as thinking_shutdown, is_shutting_down
    from app_platform.jobs import request_shutdown as jobs_shutdown
    from apps.reminders.scheduler import request_shutdown as reminders_shutdown

    if is_shutting_down():
        return {"status": "already_shutting_down"}

    thinking_shutdown()
    jobs_shutdown()
    reminders_shutdown()
    logger.info("ADMIN: Deploy requested — draining (max 30s), then git pull + recycle via host watcher")

    await manager.broadcast({"type": "server_restarting"})

    asyncio.create_task(_drain_and_exit(max_wait=30, deploy=True))

    return {"status": "deploying", "message": "Draining in-flight work, then pulling latest + recycling."}


# ── Mobile capture page (served before SPA catch-all) ──
_CAPTURE_HTML = Path(__file__).resolve().parent / "web" / "capture.html"

@app.get("/capture")
async def serve_capture_page():
    """Mobile-optimized standalone issue capture page."""
    if _CAPTURE_HTML.is_file():
        return FileResponse(_CAPTURE_HTML, media_type="text/html")
    return {"error": "Capture page not found"}, 404


# ── Meal menu export page ──
_MEAL_MENU_HTML = Path(__file__).resolve().parent / "web" / "meal-menu.html"

@app.get("/meal-menu")
@app.get("/meal-menu.html")
async def serve_meal_menu_page():
    """Standalone restaurant-style meal menu export / print page."""
    if _MEAL_MENU_HTML.is_file():
        return FileResponse(_MEAL_MENU_HTML, media_type="text/html")
    return {"error": "Meal menu page not found"}, 404


# ── Serve built frontend (SPA) ──
_DIST = Path(__file__).resolve().parent / "web" / "dist"
if _DIST.is_dir():
    # Asset filenames are content-hashed by Vite (e.g. index-a1b2c3.js), so they
    # change whenever the content does and are safe to cache forever. This also
    # makes loads faster.
    class _ImmutableStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

    # Mount static assets (JS, CSS, images) — immutable (hashed filenames).
    app.mount("/assets", _ImmutableStatic(directory=_DIST / "assets"), name="static-assets")

    # The entry point and the service-worker files must NOT be cached. If they
    # are, the browser keeps serving an old build (and an old service worker)
    # until a manual hard refresh — which defeats the PWA's autoUpdate. Serving
    # them no-cache makes the browser revalidate on every load, so a new build
    # (and the new SW) is picked up and auto-reloaded with no hard refresh.
    _NO_CACHE = {"index.html", "sw.js", "registerSW.js", "manifest.webmanifest"}

    # Serve root-level static files (manifest, SW, icons)
    @app.get("/{filename:path}")
    async def spa_fallback(request: Request, filename: str):
        # If the file exists in dist, serve it directly — but only if the
        # resolved path stays INSIDE the built web dir. Without this, an
        # unauthenticated request like /../../.env or /../../../etc/passwd would
        # traverse out of dist and FileResponse would serve it (audit #20).
        dist_root = _DIST.resolve()
        if filename:
            candidate = (dist_root / filename).resolve()
            if (candidate == dist_root or dist_root in candidate.parents) and candidate.is_file():
                if candidate.name in _NO_CACHE:
                    return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
                return FileResponse(candidate)
        # Otherwise serve index.html (SPA client-side routing) — always revalidated.
        return FileResponse(dist_root / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    # Listen port is configurable via SKIPPERBOT_PORT (default 8000). The same
    # value is used for the Docker published port and the native bind, so it
    # means the same thing on every runtime. Fall back to 8000 if it's unset or
    # not a valid integer.
    try:
        _port = int(os.getenv("SKIPPERBOT_PORT", "8000"))
    except ValueError:
        logger.warning("SKIPPERBOT_PORT is not a valid integer; falling back to 8000")
        _port = 8000
    uvicorn.run(app, host="0.0.0.0", port=_port)
