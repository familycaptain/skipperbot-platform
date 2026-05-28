"""
SkipperBot MCP Client
Handles connection to the MCP server, tool discovery, and tool execution.
"""

import asyncio
import os
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from config import logger, BASE_DIR

MCP_TOOL_TIMEOUT = 30  # seconds — includes semaphore wait + subprocess + call
MCP_MAX_CONCURRENT = 2  # limit concurrent MCP server subprocesses

mcp_tools = []
_mcp_semaphore = asyncio.Semaphore(MCP_MAX_CONCURRENT)


async def connect_to_mcp():
    """Connect to the MCP server and fetch available tools."""
    global mcp_tools

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        cwd=BASE_DIR,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            mcp_tools = tools_response.tools
            logger.debug("MCP connected. Tools: %s", [t.name for t in mcp_tools])
            return mcp_tools


def get_openai_tools():
    """Convert MCP tools to OpenAI function format."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}
            }
        }
        openai_tools.append(openai_tool)
    return openai_tools


async def call_mcp_tool(tool_name: str, arguments: dict, chat_turn_id: str = "") -> str:
    """Call an MCP tool and return the result. Retries once on transient failures."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    if chat_turn_id:
        env["SKIPPERBOT_CHAT_TURN_ID"] = chat_turn_id

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        cwd=BASE_DIR,
        env=env,
    )

    last_err = None
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(MCP_TOOL_TIMEOUT):
                async with _mcp_semaphore:
                    async with stdio_client(server_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool(tool_name, arguments)
                            if result.content:
                                return result.content[0].text
                            return "Tool executed but returned no content."
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("MCP TIMEOUT: %s timed out after %ds", tool_name, MCP_TOOL_TIMEOUT)
            return f"Error: Tool '{tool_name}' timed out after {MCP_TOOL_TIMEOUT}s."
        except BaseException as e:
            real = _unwrap_group(e)
            if isinstance(real, (asyncio.CancelledError, asyncio.TimeoutError, TimeoutError)):
                logger.error("MCP TIMEOUT: %s timed out after %ds (via TaskGroup)", tool_name, MCP_TOOL_TIMEOUT)
                return f"Error: Tool '{tool_name}' timed out after {MCP_TOOL_TIMEOUT}s."
            last_err = real
            elapsed = time.monotonic() - t0
            # Don't retry if we hit the timeout — BrokenResourceError from
            # subprocess cleanup after timeout is not a transient failure.
            near_timeout = elapsed >= MCP_TOOL_TIMEOUT - 2
            if attempt == 0 and "BrokenResource" in type(real).__name__ and not near_timeout:
                logger.warning("MCP RETRY: %s got %s (%.1fs), retrying...", tool_name, type(real).__name__, elapsed)
                await asyncio.sleep(1)
                continue
            logger.error("MCP ERROR: %s failed after %.1fs: %r (%s)", tool_name, elapsed, real, type(real).__name__)
            return f"Error: Tool '{tool_name}' failed: {real!r}"
    logger.error("MCP ERROR: %s failed after retry: %r (%s)", tool_name, last_err, type(last_err).__name__)
    return f"Error: Tool '{tool_name}' failed after retry: {last_err!r}"


def _unwrap_group(exc: BaseException) -> BaseException:
    """Unwrap an ExceptionGroup to find the root cause exception."""
    if isinstance(exc, BaseExceptionGroup):
        subs = exc.exceptions
        if subs:
            return _unwrap_group(subs[0])
    return exc
