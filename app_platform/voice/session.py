"""
Voice Session Manager
=====================
Handles OpenAI Realtime API ephemeral token minting and active voice session
state. Prompt/tool construction lives in voice_prompting.py so Android and the
home voice service can share it.
"""

from __future__ import annotations

import os
import time
import uuid

import requests

from config import logger
from app_platform.voice.prompting import (
    build_app_voice_payload,
    build_base_voice_payload,
    build_exit_voice_payload,
    is_exit_app_name,
)


# Voice/Realtime billing is split out so costs can be analyzed separately.
# Set OPENAI_VOICE_API_KEY in .env to a dedicated key; falls back to the
# shared OPENAI_API_KEY if not set so existing deployments keep working.
OPENAI_API_KEY = os.getenv("OPENAI_VOICE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "ash")
REALTIME_AUDIO_RATE = 24000
REALTIME_TRANSCRIPTION_MODEL = os.getenv("VOICE_REALTIME_TRANSCRIPTION_MODEL", "whisper-1")

# Active voice sessions: session_id -> session info
_active_sessions: dict[str, dict] = {}


def mint_ephemeral_token(user_id: str, device_info: dict | None = None) -> dict | None:
    """Mint an ephemeral OpenAI Realtime token via the sessions API."""
    device_info = device_info or {}

    try:
        base_payload = build_base_voice_payload(user_id=user_id, device_info=device_info)
        resp = requests.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "session": {
                    "type": "realtime",
                    "model": REALTIME_MODEL,
                    "instructions": base_payload["instructions"],
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": REALTIME_AUDIO_RATE},
                            "transcription": {"model": REALTIME_TRANSCRIPTION_MODEL},
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "prefix_padding_ms": 300,
                                "silence_duration_ms": 500,
                            },
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": REALTIME_AUDIO_RATE},
                            "voice": REALTIME_VOICE,
                        },
                    },
                },
            },
            timeout=10,
        )

        if resp.status_code not in (200, 201):
            logger.error("VOICE: Failed to mint token: %s %s", resp.status_code, resp.text)
            return None

        data = resp.json()
        # Full-entropy id (was 48-bit uuid[:12]); the WS also requires a bearer token.
        import secrets as _secrets
        session_id = f"vs-{_secrets.token_urlsafe(24)}"

        session_info = {
            "session_id": session_id,
            "user_id": user_id,
            "ephemeral_token": data.get("value", ""),
            "expires_at": data.get("expires_at", 0),
            "voice": REALTIME_VOICE,
            "model": REALTIME_MODEL,
            "base_instructions": base_payload["instructions"],
            "base_tools": base_payload["tools"],
            "created_at": time.time(),
            "active_app": base_payload.get("app"),
            "active_category": base_payload.get("category"),
            "device_info": device_info,
        }

        _active_sessions[session_id] = session_info

        logger.info(
            "VOICE: Minted session %s for %s (model=%s, voice=%s, app=%s, tools=%d)",
            session_id,
            user_id,
            REALTIME_MODEL,
            REALTIME_VOICE,
            session_info.get("active_app"),
            len(base_payload["tools"]),
        )

        return {
            "session_id": session_id,
            "ephemeral_token": session_info["ephemeral_token"],
            "expires_at": session_info["expires_at"],
            "voice": REALTIME_VOICE,
            "model": REALTIME_MODEL,
            "base_instructions": base_payload["instructions"],
            "base_tools": base_payload["tools"],
            "active_app": session_info.get("active_app"),
            "active_category": session_info.get("active_category"),
        }

    except Exception as exc:
        logger.error("VOICE: Token minting failed: %s", exc, exc_info=True)
        return None


def build_switch_app_payload(session_id: str, app_name: str) -> dict | None:
    """Build a session.update payload for switching to an app."""
    session = _active_sessions.get(session_id)
    if not session:
        logger.warning("VOICE: switch_app called for unknown session %s", session_id)
        return None

    if is_exit_app_name(app_name):
        return build_exit_app_payload(session_id)

    payload = build_app_voice_payload(
        app_name,
        user_id=session.get("user_id", ""),
        device_info=session.get("device_info") or {},
    )

    if not payload.get("error"):
        session["active_app"] = payload.get("app")
        session["active_category"] = payload.get("category")
        logger.info(
            "VOICE: Session %s switched to %s (category=%s, tools=%d)",
            session_id,
            payload.get("app"),
            payload.get("category"),
            len(payload.get("tools", [])),
        )

    return payload


def build_exit_app_payload(session_id: str) -> dict | None:
    """Build a session.update payload for returning to default voice mode."""
    session = _active_sessions.get(session_id)
    if not session:
        return None

    payload = build_exit_voice_payload(
        user_id=session.get("user_id", ""),
        device_info=session.get("device_info") or {},
    )
    session["active_app"] = payload.get("app")
    session["active_category"] = payload.get("category")
    return payload


def end_session(session_id: str) -> None:
    """Clean up a voice session."""
    session = _active_sessions.pop(session_id, None)
    try:
        from app_platform.voice.chatlog import forget_voice_session

        forget_voice_session(session_id)
    except Exception as exc:
        logger.debug("VOICE: Failed to forget chatlog buffer for %s: %s", session_id, exc)
    if session:
        logger.info("VOICE: Ended session %s for %s", session_id, session.get("user_id"))


def get_session(session_id: str) -> dict | None:
    """Get active session info."""
    return _active_sessions.get(session_id)
