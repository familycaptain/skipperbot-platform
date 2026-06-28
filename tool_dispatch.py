"""
Direct in-process tool dispatch — bypasses MCP subprocess for tool execution.

Instead of spawning a Python subprocess per tool call (5-10s overhead on Windows),
calls tool functions directly in the main process (<50ms overhead).

Architecture:
  - Tool SCHEMAS for the LLM still come from mcp_client.get_openai_tools()
  - Tool EXECUTION goes through this module's call_tool()
  - Sync tool functions are run via asyncio.to_thread() to avoid blocking the event loop
  - Falls back to mcp_client.call_mcp_tool() for any tool not in the registry

Call init() once at startup after dotenv is loaded.
"""

import asyncio
import importlib.util
import inspect
import sys
import time
from pathlib import Path

from config import logger, BASE_DIR

_registry: dict[str, callable] = {}
_initialized = False


def init():
    """Build the direct-call tool registry. Call once at startup."""
    global _initialized
    if _initialized:
        return

    _discover_legacy_tools()
    _discover_app_tools()

    _initialized = True
    logger.info("TOOL_DISPATCH: Registry ready — %d tools for direct dispatch", len(_registry))


def _discover_legacy_tools():
    """Auto-discover and register tools from tools/*.py modules.

    Registers all public functions (no leading underscore) with docstrings
    that are defined in the module itself (not re-exports from other packages).
    Same convention used by mcp_server.py for app package tools.
    """
    tools_dir = Path(BASE_DIR) / "tools"
    if not tools_dir.is_dir():
        return

    count = 0
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"tools.{py_file.stem}"

        try:
            # Reuse already-loaded module if available
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

            for name in dir(module):
                if name.startswith("_"):
                    continue
                obj = getattr(module, name)
                if (callable(obj) and inspect.isfunction(obj) and obj.__doc__
                        and getattr(obj, "__module__", "") == module_name):
                    _registry[name] = obj
                    count += 1
        except Exception as e:
            logger.error("TOOL_DISPATCH: Failed to load %s: %s", module_name, e)

    logger.info("TOOL_DISPATCH: Registered %d legacy tools from tools/", count)


def _discover_app_tools():
    """Auto-discover and register tools from app packages in apps/.

    Mirrors mcp_server.py _register_app_tools() — scans for apps/*/tools.py
    with a manifest.yaml, registers all public functions with docstrings.
    """
    apps_dir = Path(BASE_DIR) / "apps"
    if not apps_dir.is_dir():
        return

    for child in sorted(apps_dir.iterdir()):
        if not child.is_dir():
            continue
        tools_path = child / "tools.py"
        manifest_path = child / "manifest.yaml"
        if not tools_path.exists() or not manifest_path.exists():
            continue

        app_id = child.name
        module_name = f"apps.{app_id}.tools"

        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, tools_path)
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

            count = 0
            for name in dir(module):
                if name.startswith("_"):
                    continue
                obj = getattr(module, name)
                if callable(obj) and inspect.isfunction(obj) and obj.__doc__:
                    _registry[name] = obj
                    count += 1

            if count:
                logger.info("TOOL_DISPATCH: Registered %d tool(s) from app '%s'", count, app_id)
        except Exception as e:
            logger.error("TOOL_DISPATCH: Failed to load app '%s': %s", app_id, e)


async def call_tool(tool_name: str, arguments: dict) -> str:
    """Call a tool function directly in-process.

    Runs sync functions in a thread pool via asyncio.to_thread() to avoid
    blocking the event loop. Async functions are awaited directly.

    Falls back to MCP subprocess for tools not in the registry.
    """
    # Hard refusal for tools disabled from the chat surface (code authoring /
    # shell / MCP control). Defense in depth behind chat_domain's offer-time
    # filter; internal/operator code that calls these functions directly does
    # not route through call_tool and is unaffected.
    from tool_router import DISABLED_CHAT_TOOLS
    if tool_name in DISABLED_CHAT_TOOLS:
        logger.warning("TOOL_DISPATCH: refused disabled tool '%s'", tool_name)
        return (f"Error: Tool '{tool_name}' is disabled. Code and app changes go "
                f"through the development workflow, not in-chat tools.")

    fn = _registry.get(tool_name)
    if fn is None:
        from mcp_client import call_mcp_tool
        logger.warning("TOOL_DISPATCH: '%s' not in registry, falling back to MCP subprocess", tool_name)
        return await call_mcp_tool(tool_name, arguments)

    t0 = time.monotonic()
    try:
        if asyncio.iscoroutinefunction(fn):
            result = await fn(**arguments)
        else:
            result = await asyncio.to_thread(fn, **arguments)
        elapsed = time.monotonic() - t0
        if elapsed > 2.0:
            logger.warning("TOOL_DISPATCH: %s took %.1fs (slow)", tool_name, elapsed)
        return str(result) if result is not None else "Tool executed but returned no content."
    except TypeError as e:
        logger.error("TOOL_DISPATCH: %s(%s) TypeError: %s", tool_name, list(arguments.keys()), e)
        return f"Error: Tool '{tool_name}' argument error: {e}"
    except Exception as e:
        logger.error("TOOL_DISPATCH: %s failed: %s", tool_name, e, exc_info=True)
        return f"Error: Tool '{tool_name}' failed: {e}"


def get_tool(tool_name: str):
    """Get a tool function by name, or None."""
    return _registry.get(tool_name)


def list_tools() -> list[str]:
    """List all registered tool names."""
    return sorted(_registry.keys())


def verify_against_mcp(mcp_tool_names: list[str]) -> dict:
    """Compare registry against MCP tool list. Call after connect_to_mcp().

    Returns dict with 'missing' (in MCP but not registry) and
    'extra' (in registry but not MCP) tool names.
    """
    mcp_set = set(mcp_tool_names)
    reg_set = set(_registry.keys())
    missing = sorted(mcp_set - reg_set)
    extra = sorted(reg_set - mcp_set)
    if missing:
        logger.warning("TOOL_DISPATCH: %d tools in MCP but not in registry: %s", len(missing), missing)
    if extra:
        logger.debug("TOOL_DISPATCH: %d tools in registry but not in MCP: %s", len(extra), extra)
    return {"missing": missing, "extra": extra}
