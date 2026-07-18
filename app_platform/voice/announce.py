"""Proactive voice announcements — host-side TTS + push to a satellite (Group 1).

One-way: the host synthesizes speech (OpenAI, same voice as the live session),
pushes an ``announce`` envelope to the device, then streams the PCM. The device
plays a local chime first (its "I'm about to talk" earcon), then the audio.

The ``announce`` envelope carries fields later groups will use — ``listen_after``
(Group 2 opens the mic for a reply), ``priority`` (Group 3/4 quiet-hours +
interrupt-vs-queue) — but a one-way announcement just speaks. Delivery is
best-effort: if no device is online or TTS fails, the caller falls back to the
ordinary push channels so nothing is lost.
"""
from __future__ import annotations

import os

from config import logger
from app_platform.voice.session import REALTIME_AUDIO_RATE, REALTIME_VOICE
from app_platform.voice.devices import manager as devices

try:                                    # match relay.py's source for the key
    from config import OPENAI_API_KEY
except Exception:                       # pragma: no cover
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_TTS_MODEL = os.getenv("VOICE_TTS_MODEL", "gpt-4o-mini-tts")
_TTS_VOICE = os.getenv("VOICE_TTS_VOICE", REALTIME_VOICE)
# ~100ms of PCM16 mono per frame @ 24kHz — the same format the relay streams.
_PCM_FRAME = (REALTIME_AUDIO_RATE * 2) // 10


async def synthesize_pcm(text: str) -> bytes:
    """OpenAI text->speech as raw PCM16 mono @ 24kHz (matches the relay audio path)."""
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": _TTS_MODEL, "voice": _TTS_VOICE, "input": text,
                  "response_format": "pcm"},
        )
        resp.raise_for_status()
        return resp.content


async def announce_to_device(device_id: str, text: str, *, source: dict | None = None,
                             priority: str = "normal", listen_after: bool = False) -> bool:
    """Speak ``text`` on a device. Returns True only if it was actually delivered
    (device online + TTS ok + frames sent), so a False lets the caller fall back."""
    text = (text or "").strip()
    if not text:
        return False
    target = devices.resolve(device_id)
    if not target:
        logger.info("VOICE-ANNOUNCE: no online device (asked=%r) — can't speak %r",
                    device_id, text[:60])
        return False
    if not OPENAI_API_KEY:
        logger.warning("VOICE-ANNOUNCE: OPENAI_API_KEY unset — can't synthesize")
        return False
    try:
        pcm = await synthesize_pcm(text)
    except Exception as exc:  # noqa: BLE001
        logger.error("VOICE-ANNOUNCE: TTS failed: %s", exc)
        return False

    # 1) Envelope: chime + get ready to play. 2) stream PCM. 3) end marker.
    ok = await devices.send_json(target, {
        "type": "announce", "text": text, "chime": "default",
        "priority": priority, "listen_after": listen_after,
        "source": source or {}, "sample_rate": REALTIME_AUDIO_RATE,
    })
    if not ok:
        return False
    for i in range(0, len(pcm), _PCM_FRAME):
        if not await devices.send_bytes(target, pcm[i:i + _PCM_FRAME]):
            return False
    await devices.send_json(target, {"type": "announce_end"})
    logger.info("VOICE-ANNOUNCE: spoke on %s (%d bytes pcm): %r", target, len(pcm), text[:60])
    return True
