"""
Shared voice tool runtime.

Both Android voice sideband calls and the home voice service should route model
tool calls through this module so policy and app switching stay consistent.
"""

from __future__ import annotations

import json
import time

from config import logger


async def handle_voice_tool_call(
    *,
    session_id: str,
    call_id: str,
    tool_name: str,
    arguments: dict | None,
) -> list[dict]:
    """Execute a voice tool call and return sideband-style events."""
    arguments = arguments or {}

    # Console-log EVERY voice tool call with its full parameters. Uses the VOICE prefix so
    # it also surfaces in the /api/voice/debug stream. Truncated to keep log lines sane.
    try:
        _args_json = json.dumps(arguments, default=str)
    except Exception:
        _args_json = repr(arguments)
    if len(_args_json) > 800:
        _args_json = _args_json[:800] + "…"
    logger.info("VOICE-TOOL call=%s session=%s args=%s", tool_name, session_id, _args_json)
    _t0 = time.monotonic()

    try:
        from app_platform.voice.prompting import is_exit_app_name
        from app_platform.voice.session import (
            build_exit_app_payload,
            build_switch_app_payload,
            get_session,
        )
        from local_tools import LOCAL_TOOL_NAMES, handle_local_tool
        import tool_dispatch

        session = get_session(session_id)
        if not session:
            return [tool_result(call_id, f"Error: unknown voice session {session_id}")]

        user_id = session["user_id"]

        if tool_name == "end_voice_session":
            logger.info("VOICE: end_voice_session requested for %s", session_id)
            return [{"type": "end_session"}]

        if tool_name == "enroll_voice":
            # The host audio relay intercepts this (it has the live audio buffer).
            # Reaching here means a direct-to-OpenAI client called it — no audio
            # to enroll from on this side.
            return [tool_result(call_id, "Voice enrollment is only available when "
                                         "using the host audio relay.")]

        if tool_name == "switch_voice_app":
            app_name = str(arguments.get("app_name", "base")).lower().strip()
            if is_exit_app_name(app_name):
                payload = build_exit_app_payload(session_id)
                output = "Returned to default voice mode."
            else:
                payload = build_switch_app_payload(session_id, app_name)
                output = f"Switched to {app_name} app. You now have access to {app_name} tools."

            if not payload:
                return [tool_result(call_id, "Error: voice session not found")]
            if payload.get("error"):
                return [tool_result(call_id, payload["error"])]

            return [
                {
                    "type": "session_update",
                    "instructions": payload.get("instructions", ""),
                    "tools": payload.get("tools", []),
                    "app": payload.get("app"),
                },
                tool_result(call_id, output),
            ]

        if tool_name in LOCAL_TOOL_NAMES:
            output = await handle_local_tool(tool_name, arguments, user_id)
        else:
            output = await tool_dispatch.call_tool(tool_name, arguments)

        logger.info("VOICE-TOOL done=%s %.0fms result=%s", tool_name,
                    (time.monotonic() - _t0) * 1000.0,
                    str(output)[:300].replace("\n", " "))
        return [tool_result(call_id, output)]

    except Exception as exc:
        logger.error("VOICE: Tool execution failed: %s: %s", tool_name, exc, exc_info=True)
        return [tool_result(call_id, f"Error executing {tool_name}: {exc}")]


def tool_result(call_id: str, output: str) -> dict:
    return {
        "type": "tool_result",
        "call_id": call_id,
        "output": output,
    }
