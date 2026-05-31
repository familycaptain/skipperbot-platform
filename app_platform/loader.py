"""App Package Loader
=====================
Discovers app packages in apps/, runs their lifecycle, and integrates them
with the platform (migrations, entity types, tools, routes, events, thinking).

Lifecycle per app:
1. Parse manifest.yaml
2. Create/ensure Postgres schema (app_<id>)
3. Run pending migrations
4. Validate no cross-schema foreign keys
5. Register entity types
6. Register in app_registry
7. Load tools (tools.py → MCP tool registration)
8. Mount routes (routes.py → FastAPI router)
9. Load guide (guide.md → tool_routes integration)
10. Wire event subscriptions (handlers.py)
11. Register job handlers
12. Register thinking domain
"""

import importlib
import importlib.util
import inspect
import json
import logging
import sys
from pathlib import Path

import psycopg2.extras

from data_layer.db import get_conn, fetch_one, execute
from app_platform.manifest import AppManifest, discover_apps
from app_platform.migrator import (
    ensure_schema,
    run_app_migrations,
    validate_no_cross_schema_fks,
)

logger = logging.getLogger("platform.loader")

# ---------------------------------------------------------------------------
# State: loaded app packages
# ---------------------------------------------------------------------------

_loaded_apps: dict[str, AppManifest] = {}
_app_tools: dict[str, list[callable]] = {}      # app_id -> list of tool functions
_app_routers: dict[str, object] = {}             # app_id -> FastAPI APIRouter
_app_tool_routes: dict[str, dict] = {}           # app_id -> tool_routes entry


def get_loaded_apps() -> dict[str, AppManifest]:
    """Return dict of currently loaded app manifests."""
    return dict(_loaded_apps)


def require_apps(*app_ids: str) -> None:
    """Raise RuntimeError if any of the required apps are not loaded.

    Use this in platform features that have a declared dependency on a
    specific app (e.g. the evolve thinking domain depends on the Issues
    app). Call it at the entry point so missing prerequisites fail loudly
    with a clear remediation message instead of degrading silently.
    """
    missing = [a for a in app_ids if a not in _loaded_apps]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Required app(s) not installed: {joined}. "
            f"Install the app folder(s) under apps/ and restart the platform."
        )


# Apps the platform refuses to run without (core: true in their manifests).
# They ship inside the platform repo. If a folder is deleted or an app fails
# to load, boot aborts with a clear message rather than silently degrading.
REQUIRED_APPS = (
    "backups", "behaviors", "documents", "finder", "folders", "goals",
    "jobs", "lists", "notifications", "prioritize", "reminders", "schedules",
    "settings", "system", "timeline", "todo", "tools",
)


def get_app_tools() -> dict[str, list[callable]]:
    """Return dict of app_id -> tool functions."""
    return dict(_app_tools)


def get_app_tool_routes() -> dict[str, dict]:
    """Return dict of app_id -> tool_routes entry for tool_router integration."""
    return dict(_app_tool_routes)


# ---------------------------------------------------------------------------
# Full load cycle
# ---------------------------------------------------------------------------

def load_all_apps(apps_dir: Path, fastapi_app=None, mcp=None):
    """Discover and load all app packages.

    Args:
        apps_dir:     Path to apps/ directory
        fastapi_app:  FastAPI app instance (for route mounting)
        mcp:          FastMCP instance (for tool registration)
    """
    manifests = discover_apps(apps_dir)

    if not manifests:
        logger.info("APP LOADER: No app packages found")
        return

    logger.info("APP LOADER: Found %d app package(s)", len(manifests))

    for manifest in manifests:
        try:
            _load_app(manifest, fastapi_app=fastapi_app, mcp=mcp)
        except Exception as e:
            logger.error("APP LOADER: Failed to load '%s': %s", manifest.id, e,
                         exc_info=True)
            _mark_app_status(manifest.id, "error", str(e), manifest)

    # Refuse to run without the required (core) apps. A core app that's missing
    # or that failed to load above won't be in _loaded_apps, so this fails the
    # boot loudly with the exact app(s) to fix instead of degrading silently.
    require_apps(*REQUIRED_APPS)

    # Merge app tool routes into the tool router for keyword matching
    if _app_tool_routes:
        from tool_router import merge_app_tool_routes
        merge_app_tool_routes(_app_tool_routes)
        logger.info("APP LOADER: Merged %d app tool route(s) into tool router",
                     len(_app_tool_routes))

    # Rebuild the system prompt so {{TOOL_CATEGORY_LIST}} includes app categories
    from config import invalidate_system_prompt
    invalidate_system_prompt()


def _load_app(manifest: AppManifest, fastapi_app=None, mcp=None):
    """Run the full lifecycle for a single app package."""
    app_id = manifest.id
    logger.info("APP LOADER: Loading '%s' v%s ...", app_id, manifest.version)

    # 1. Register in app_registry (must happen before migrations due to FK on app_migrations)
    _mark_app_status(app_id, "active", "", manifest)

    # 2. Ensure Postgres schema
    schema = ensure_schema(app_id)

    # 3. Run migrations
    if manifest.has_migrations:
        migrations_dir = manifest.app_dir / "migrations"
        applied = run_app_migrations(app_id, migrations_dir)
        if applied:
            logger.info("APP LOADER: %s — applied %d migration(s)", app_id, len(applied))

    # 4. Validate no cross-schema FKs
    violations = validate_no_cross_schema_fks(app_id)
    if violations:
        raise RuntimeError(
            f"App '{app_id}' has cross-schema foreign keys: {violations}"
        )

    # 5. Register entity types
    _register_entity_types(manifest)

    # 6. Mark active
    _mark_app_status(app_id, "active", "", manifest)

    # 7. Load tools
    if manifest.has_tools:
        tools = _load_tools(manifest, mcp=mcp)
        _app_tools[app_id] = tools

    # 8. Mount routes
    if manifest.has_routes and fastapi_app:
        router = _mount_routes(manifest, fastapi_app)
        if router:
            _app_routers[app_id] = router

    # 9. Build tool_routes entry
    if manifest.has_tools and manifest.tool_category:
        _build_tool_route(manifest)

    # 10. Wire event subscriptions
    if manifest.has_handlers:
        _wire_event_subscriptions(manifest)

    # 11. Register job handlers
    if manifest.job_types:
        _register_job_handlers(manifest)

    # 12. Register thinking domain
    if manifest.thinking:
        _register_thinking_domain(manifest)

    # 13. Load platform hooks (backlog providers, activity checkers, etc.)
    _load_hooks(manifest)

    _loaded_apps[app_id] = manifest
    logger.info("APP LOADER: '%s' loaded successfully", app_id)


# ---------------------------------------------------------------------------
# Entity type registration
# ---------------------------------------------------------------------------

def _register_entity_types(manifest: AppManifest):
    """Register the app's entity types in public.entity_types."""
    for et in manifest.entity_types:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO entity_types (prefix, name, id_format, table_name) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (prefix) DO UPDATE "
                    "SET name = EXCLUDED.name, id_format = EXCLUDED.id_format, "
                    "table_name = EXCLUDED.table_name",
                    (et.prefix, et.name, et.id_format, et.table),
                )
            conn.commit()
        logger.info("APP LOADER: Registered entity type '%s' (%s)", et.prefix, et.name)

    # Invalidate entity type cache
    if manifest.entity_types:
        from data_layer.entity_types import invalidate_cache
        invalidate_cache()


# ---------------------------------------------------------------------------
# App registry
# ---------------------------------------------------------------------------

def _mark_app_status(app_id: str, status: str, error_message: str,
                     manifest: AppManifest | None = None):
    """Insert or update the app in app_registry."""
    manifest_json = {}
    if manifest:
        manifest_json = {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "entity_types": [
                {"prefix": et.prefix, "name": et.name}
                for et in manifest.entity_types
            ],
            "emits": manifest.emits,
            "subscribes": manifest.subscribes,
        }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO app_registry (app_id, version, status, error_message, manifest, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (app_id) DO UPDATE SET "
                "version = EXCLUDED.version, status = EXCLUDED.status, "
                "error_message = EXCLUDED.error_message, manifest = EXCLUDED.manifest, "
                "updated_at = now()",
                (app_id,
                 manifest.version if manifest else "0.0.0",
                 status,
                 error_message,
                 psycopg2.extras.Json(manifest_json)),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Tool loader
# ---------------------------------------------------------------------------

def _load_tools(manifest: AppManifest, mcp=None) -> list[callable]:
    """Import tools.py from the app package and register tool functions.

    Returns list of tool functions found.
    """
    app_id = manifest.id
    tools_path = manifest.app_dir / "tools.py"
    module_name = f"apps.{app_id}.tools"

    spec = importlib.util.spec_from_file_location(module_name, tools_path)
    if not spec or not spec.loader:
        logger.warning("APP LOADER: Could not load tools.py for '%s'", app_id)
        return []

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Collect only the functions DEFINED in this module — skip
    # re-exports of `load_dotenv`, `digest_record`, etc. that an app's
    # tools.py imports for its own use. Otherwise MCP would try to
    # schema their signatures (load_dotenv has `IO[str]`, which
    # pydantic refuses) and re-register the same callable from every
    # app that imports it ("Component already exists").
    tool_fns = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if not (inspect.isfunction(obj) and obj.__doc__):
            continue
        if getattr(obj, "__module__", "") != module_name:
            continue
        tool_fns.append(obj)

    # Register with MCP if provided
    if mcp and tool_fns:
        for fn in tool_fns:
            mcp.tool()(fn)
            logger.info("APP LOADER: Registered MCP tool '%s' from '%s'",
                        fn.__name__, app_id)

    logger.info("APP LOADER: Loaded %d tool(s) from '%s'", len(tool_fns), app_id)
    return tool_fns


# ---------------------------------------------------------------------------
# Route mounter
# ---------------------------------------------------------------------------

def _mount_routes(manifest: AppManifest, fastapi_app) -> object | None:
    """Import routes.py and mount its APIRouter on /api/apps/<id>/."""
    app_id = manifest.id
    routes_path = manifest.app_dir / "routes.py"
    module_name = f"apps.{app_id}.routes"

    spec = importlib.util.spec_from_file_location(module_name, routes_path)
    if not spec or not spec.loader:
        logger.warning("APP LOADER: Could not load routes.py for '%s'", app_id)
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    router = getattr(module, "router", None)
    if router is None:
        logger.warning("APP LOADER: routes.py for '%s' has no 'router' attribute", app_id)
        return None

    prefix = f"/api/apps/{app_id}"
    fastapi_app.include_router(router, prefix=prefix, tags=[f"app:{app_id}"])
    logger.info("APP LOADER: Mounted routes for '%s' at %s", app_id, prefix)
    return router


# ---------------------------------------------------------------------------
# Tool routes integration
# ---------------------------------------------------------------------------

def _build_tool_route(manifest: AppManifest):
    """Build a tool_routes-compatible entry for the app's tools."""
    app_id = manifest.id
    tc = manifest.tool_category

    tool_names = [fn.__name__ for fn in _app_tools.get(app_id, [])]

    entry = {
        "description": tc.description,
        "tools": tool_names,
        "ack": {},
        "keywords": tc.keywords,
    }

    # Include guide if present
    if manifest.has_guide:
        entry["guide_path"] = str(manifest.app_dir / "guide.md")

    # If tools.py exposes get_guide_context(), store it for dynamic injection
    tools_module = sys.modules.get(f"apps.{app_id}.tools")
    if tools_module and hasattr(tools_module, "get_guide_context"):
        entry["_guide_context_fn"] = tools_module.get_guide_context

    _app_tool_routes[app_id] = entry
    logger.info("APP LOADER: Built tool route for '%s' with %d tool(s), %d keyword(s)",
                app_id, len(tool_names), len(tc.keywords))


# ---------------------------------------------------------------------------
# Event subscriptions
# ---------------------------------------------------------------------------

def _wire_event_subscriptions(manifest: AppManifest):
    """Import handlers.py and register @subscribe-decorated functions."""
    app_id = manifest.id
    handlers_path = manifest.app_dir / "handlers.py"
    module_name = f"apps.{app_id}.handlers"

    spec = importlib.util.spec_from_file_location(module_name, handlers_path)
    if not spec or not spec.loader:
        return

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    # Import will trigger @subscribe decorators which auto-register
    spec.loader.exec_module(module)
    logger.info("APP LOADER: Wired event handlers for '%s'", app_id)


# ---------------------------------------------------------------------------
# Job handlers
# ---------------------------------------------------------------------------

def _register_job_handlers(manifest: AppManifest):
    """Register job type handlers declared in the manifest."""
    app_id = manifest.id
    for jt in manifest.job_types:
        if not jt.handler:
            continue
        # Handler format: "handlers.handle_import" or "module.func"
        parts = jt.handler.rsplit(".", 1)
        if len(parts) != 2:
            logger.warning("APP LOADER: Invalid handler format '%s' in '%s'",
                           jt.handler, app_id)
            continue

        module_rel, func_name = parts
        module_path = manifest.app_dir / f"{module_rel}.py"
        module_name = f"apps.{app_id}.{module_rel}"

        if module_name not in sys.modules:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        else:
            module = sys.modules[module_name]

        handler_fn = getattr(module, func_name, None)
        if handler_fn:
            # Register with job_dispatcher
            try:
                from job_handlers import register_handler
                register_handler(jt.type, handler_fn,
                                max_concurrent=jt.max_concurrent,
                                cancel_on_shutdown=jt.cancel_on_shutdown)
                logger.info("APP LOADER: Registered job handler '%s' -> %s.%s (cancel_on_shutdown=%s)",
                            jt.type, app_id, jt.handler, jt.cancel_on_shutdown)
            except ImportError:
                logger.warning("APP LOADER: job_handlers.register_handler not available")


# ---------------------------------------------------------------------------
# Thinking domain registration
# ---------------------------------------------------------------------------

def _register_thinking_domain(manifest: AppManifest):
    """Register every thinking domain the app declared with the platform.

    Apps may declare zero, one, or many thinking domains (see
    ``apps/goals/manifest.yaml`` for a 2-domain example: 'pm' + 'goals').
    The manifest parser normalizes to a list.
    """
    if not manifest.thinking:
        return

    app_id = manifest.id

    for td in manifest.thinking:
        if not td.domain:
            continue

        # Read the thinking prompt (relative to the app folder).
        prompt_text = ""
        if td.prompt_file:
            prompt_path = manifest.app_dir / td.prompt_file
            if prompt_path.exists():
                prompt_text = prompt_path.read_text(encoding="utf-8")

        logger.info("APP LOADER: Registered thinking domain '%s' for '%s' (schedule: %s, prompt_chars: %d)",
                    td.domain, app_id, td.schedule, len(prompt_text))

        # NOTE: Full integration with thinking_scheduler will require extending
        # the thinking_domains table and scheduler to support app-declared domains.
        # For now, log the registration. The domain config is stored in the
        # app_registry manifest and can be read by the scheduler.


# ---------------------------------------------------------------------------
# Platform hooks (backlog providers, activity checkers, etc.)
# ---------------------------------------------------------------------------

def _load_hooks(manifest: AppManifest):
    """Import hooks.py from the app package and call register_hooks() if present.

    This lets app packages register backlog providers, activity checkers,
    and other platform extension points without the platform having any
    hard dependency on the app.
    """
    app_id = manifest.id
    hooks_path = manifest.app_dir / "hooks.py"
    if not hooks_path.exists():
        return

    module_name = f"apps.{app_id}.hooks"
    spec = importlib.util.spec_from_file_location(module_name, hooks_path)
    if not spec or not spec.loader:
        logger.warning("APP LOADER: Could not load hooks.py for '%s'", app_id)
        return

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    register_fn = getattr(module, "register_hooks", None)
    if register_fn and callable(register_fn):
        register_fn()
        logger.info("APP LOADER: Loaded platform hooks for '%s'", app_id)


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

def uninstall_app(app_id: str, purge: bool = False):
    """Uninstall an app package.

    Args:
        purge: If True, drops the app's Postgres schema (RESTRICT).
    """
    if purge:
        from app_platform.migrator import drop_app_schema
        drop_app_schema(app_id, purge=True)

    execute(
        "UPDATE app_registry SET status = 'uninstalled', updated_at = now() "
        "WHERE app_id = %s",
        (app_id,),
    )

    # Clean up in-memory state
    _loaded_apps.pop(app_id, None)
    _app_tools.pop(app_id, None)
    _app_routers.pop(app_id, None)
    _app_tool_routes.pop(app_id, None)

    # Invalidate entity cache
    from app_platform.entities import invalidate_cache
    invalidate_cache()

    logger.info("APP LOADER: Uninstalled '%s' (purge=%s)", app_id, purge)
