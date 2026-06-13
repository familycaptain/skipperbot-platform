"""Server-side OpenAI Realtime relay (voice satellite ↔ host ↔ OpenAI).

The original design streamed audio satellite→OpenAI directly. This relay flips
that: the platform holds the OpenAI Realtime session (server-side, with the
platform's key), and the satellite becomes a thin audio endpoint (wake word +
AEC + 2-way PCM). The platform runs the tools, logs the transcript, and is the
single point where speaker identification will hook in (it sees the inbound
audio). Tools never round-trip to the satellite anymore — they execute here.

Satellite ↔ host WebSocket protocol (this module's side):
  satellite → host:
    * binary frame  = mic PCM16 mono @ REALTIME_AUDIO_RATE
    * text  frame   = JSON control: {"type": "end"}  (client-initiated stop)
  host → satellite:
    * binary frame  = output PCM16 mono @ REALTIME_AUDIO_RATE (play it)
    * text  frame   = JSON: {"type":"transcript","role":..,"text":..}
                      {"type":"status","status":"speech_started|stopped|ready"}
                      {"type":"session_ended"}

The OpenAI event flow mirrors the satellite's proven client
(skipperbot-voice/realtime_voice_test.py) exactly, so the two stay protocol-
compatible.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os

import websockets

from config import logger

# SECURITY: the websockets client logs the full WS handshake — including the
# "Authorization: Bearer <OPENAI_API_KEY>" header — at DEBUG level. If the app
# runs at DEBUG, that leaks the key into the logs. Cap the library's own loggers
# to WARNING so the handshake (and the per-frame audio spam) never log, no
# matter what the platform's root log level is.
for _noisy in ("websockets", "websockets.client", "websockets.server", "websockets.protocol"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logging.getLogger("websockets").propagate = False
from app_platform.voice.session import (
    OPENAI_API_KEY,
    REALTIME_AUDIO_RATE,
    REALTIME_MODEL,
    REALTIME_VOICE,
)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"

_AUDIO_DELTA_TYPES = {"response.audio.delta", "response.output_audio.delta"}
_ASSISTANT_TRANSCRIPT_TYPES = {
    "response.audio_transcript.done",
    "response.output_audio_transcript.done",
}


def _session_update(instructions: str, tools: list[dict], voice: str) -> dict:
    """Build the OpenAI session.update payload (matches session.py / the satellite)."""
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": REALTIME_AUDIO_RATE},
                    "transcription": {
                        "model": os.getenv("VOICE_REALTIME_TRANSCRIPTION_MODEL", "whisper-1"),
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": float(os.getenv("VOICE_VAD_THRESHOLD", "0.5")),
                        "prefix_padding_ms": int(os.getenv("VOICE_VAD_PREFIX_PADDING_MS", "300")),
                        "silence_duration_ms": int(os.getenv("VOICE_VAD_SILENCE_MS", "500")),
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": REALTIME_AUDIO_RATE},
                    "voice": voice,
                },
            },
            "tools": tools,
        },
    }


async def _openai_connect(url: str, headers: dict):
    """websockets >=12 renamed extra_headers → additional_headers; support both."""
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


async def _send_oai(oai, event: dict) -> None:
    await oai.send(json.dumps(event))


async def _apply_tool_events(oai, events: list[dict]) -> bool:
    """Translate handle_voice_tool_call() output into OpenAI WS sends.

    Returns True if the session should end (end_voice_session tool).
    """
    should_end = False
    for ev in events or []:
        et = ev.get("type")
        if et == "session_update":
            # switch_voice_app → reconfigure the live session (new app's tools)
            await _send_oai(oai, _session_update(
                ev.get("instructions", ""),
                ev.get("tools", []),
                ev.get("voice", REALTIME_VOICE),
            ))
        elif et == "tool_result":
            await _send_oai(oai, {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": ev.get("call_id", ""),
                    "output": ev.get("output", ""),
                },
            })
            await _send_oai(oai, {"type": "response.create"})
        elif et == "end_session":
            should_end = True
    return should_end


async def relay_session(satellite_ws, session_id: str, session: dict) -> None:
    """Bridge one satellite audio WebSocket to a server-side OpenAI Realtime session.

    `satellite_ws` is an already-accepted Starlette WebSocket. `session` is the
    record created by app_platform.voice.session (base_instructions/base_tools).
    """
    from app_platform.voice.tool_runtime import handle_voice_tool_call
    try:
        from app_platform.voice.chatlog import record_voice_transcript
    except Exception:  # chatlog is best-effort
        record_voice_transcript = None

    instructions = session.get("base_instructions", "")
    tools = session.get("base_tools", []) or []
    voice = session.get("voice", REALTIME_VOICE)
    user_id = session.get("user_id", "")

    if not OPENAI_API_KEY:
        await satellite_ws.send_text(json.dumps({"type": "error", "error": "OPENAI_API_KEY not set on the platform"}))
        return

    url = f"{OPENAI_REALTIME_URL}?model={REALTIME_MODEL}"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    oai = await _openai_connect(url, headers)
    logger.info("VOICE-RELAY: session %s connected to OpenAI Realtime (user=%s, tools=%d)",
                session_id, user_id, len(tools))
    stop = asyncio.Event()

    try:
        await _send_oai(oai, _session_update(instructions, tools, voice))

        async def pump_satellite_to_openai():
            """Mic PCM (binary) → OpenAI input_audio_buffer.append; text = control."""
            try:
                while not stop.is_set():
                    msg = await satellite_ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    chunk = msg.get("bytes")
                    if chunk:
                        await _send_oai(oai, {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        })
                        continue
                    text = msg.get("text")
                    if text:
                        try:
                            ctrl = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if ctrl.get("type") == "end":
                            break
            finally:
                stop.set()

        async def pump_openai_to_satellite():
            """OpenAI events → satellite audio/transcripts; tools run here."""
            try:
                async for raw in oai:
                    if stop.is_set():
                        break
                    event = json.loads(raw)
                    et = event.get("type", "")

                    if et in _AUDIO_DELTA_TYPES:
                        delta = event.get("delta", "")
                        if delta:
                            await satellite_ws.send_bytes(base64.b64decode(delta))

                    elif et == "input_audio_buffer.speech_started":
                        await satellite_ws.send_text(json.dumps({"type": "status", "status": "speech_started"}))
                    elif et == "input_audio_buffer.speech_stopped":
                        await satellite_ws.send_text(json.dumps({"type": "status", "status": "speech_stopped"}))

                    elif et == "conversation.item.input_audio_transcription.completed":
                        text = event.get("transcript", "")
                        if record_voice_transcript:
                            await record_voice_transcript(session_id, "user", text, user_id=user_id)
                        await satellite_ws.send_text(json.dumps({"type": "transcript", "role": "user", "text": text}))

                    elif et in _ASSISTANT_TRANSCRIPT_TYPES:
                        text = event.get("transcript", "")
                        if record_voice_transcript:
                            await record_voice_transcript(session_id, "assistant", text, user_id=user_id)
                        await satellite_ws.send_text(json.dumps({"type": "transcript", "role": "assistant", "text": text}))

                    elif et == "response.function_call_arguments.done":
                        call_id = event.get("call_id", "")
                        name = event.get("name", "")
                        raw_args = event.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {}
                        logger.info("VOICE-RELAY: tool %s(%s) [session %s]", name, list(args.keys()), session_id[:12])
                        events = await handle_voice_tool_call(
                            session_id=session_id, call_id=call_id, tool_name=name, arguments=args,
                        )
                        if await _apply_tool_events(oai, events):
                            break

                    elif et == "error":
                        logger.error("VOICE-RELAY: OpenAI error [session %s]: %s", session_id[:12], event.get("error"))
            finally:
                stop.set()

        await asyncio.gather(pump_satellite_to_openai(), pump_openai_to_satellite())
    finally:
        try:
            await oai.close()
        except Exception:
            pass
        try:
            await satellite_ws.send_text(json.dumps({"type": "session_ended"}))
        except Exception:
            pass
        logger.info("VOICE-RELAY: session %s relay closed", session_id)
