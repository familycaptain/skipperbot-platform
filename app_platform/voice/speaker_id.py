"""Host-side speaker identification for voice.

Identifies WHICH enrolled household member is speaking, so the agent can attach
the right identity to a voice turn (permissions, personal data, "remind *me*").
The relay (app_platform/voice/relay.py) buffers each turn's user audio and calls
identify(); enrollment is voice-driven ("Skipper, this is <name>").

Uses resemblyzer voice embeddings (256-d). It's an OPTIONAL extra
(requirements-voice-speaker.txt) — if it isn't installed, available() is False
and enroll/identify are no-ops, so voice keeps working without speaker-ID.

Scope: per-TURN attribution (each VAD-segmented turn → one speaker). It does NOT
separate two people talking simultaneously in the same segment ("cocktail party"
problem) — a mixed segment yields a mixed embedding.

Profiles live in public.voice_speaker_profiles (created on first use, since
init_db only runs the baseline — same ensure-schema pattern as service tokens).
"""

from __future__ import annotations

import os
import threading

from config import logger
from data_layer.db import execute, fetch_all, fetch_one

# Cosine-similarity threshold for a confident match (resemblyzer: same speaker
# typically > 0.75, different < 0.6). Tunable via env.
MATCH_THRESHOLD = float(os.getenv("VOICE_SPEAKER_THRESHOLD", "0.75"))

_encoder = None
_encoder_lock = threading.Lock()
_schema_ready = False


def available() -> bool:
    """True if the speaker-ID dependency stack is importable."""
    try:
        import numpy  # noqa: F401
        import resemblyzer  # noqa: F401
        return True
    except Exception:
        return False


def _get_encoder():
    """Lazily build and cache the resemblyzer VoiceEncoder (CPU)."""
    global _encoder
    if _encoder is None:
        with _encoder_lock:
            if _encoder is None:
                from resemblyzer import VoiceEncoder
                _encoder = VoiceEncoder("cpu")
                logger.info("SPEAKER-ID: voice encoder loaded")
    return _encoder


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    execute(
        """
        CREATE TABLE IF NOT EXISTS public.voice_speaker_profiles (
            name         text PRIMARY KEY,
            embedding    jsonb NOT NULL,
            sample_count integer NOT NULL DEFAULT 1,
            updated_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    _schema_ready = True


def embed(pcm16: bytes, sample_rate: int = 24000) -> list[float] | None:
    """Embed mono int16 PCM into a 256-d voiceprint. None if unavailable/too short."""
    if not pcm16 or not available():
        return None
    try:
        import numpy as np
        from resemblyzer import preprocess_wav

        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        wav = preprocess_wav(samples, source_sr=sample_rate)
        if wav.size < sample_rate // 2:  # < ~0.5s of voiced audio — too short to trust
            return None
        vec = _get_encoder().embed_utterance(wav)
        return [float(x) for x in vec]
    except Exception as exc:
        logger.warning("SPEAKER-ID: embed failed: %s", exc)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    import numpy as np
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def enroll(name: str, pcm16: bytes, sample_rate: int = 24000) -> bool:
    """Enroll/update a voiceprint for `name` from an audio sample.

    Multiple enrollments are averaged (weighted by prior sample count) for
    robustness. Returns True on success.
    """
    name = (name or "").strip().lower()
    if not name:
        return False
    new_vec = embed(pcm16, sample_rate)
    if new_vec is None:
        return False
    _ensure_schema()
    row = fetch_one("SELECT embedding, sample_count FROM voice_speaker_profiles WHERE name = %s", (name,))
    import json
    if row and row.get("embedding"):
        old = row["embedding"]
        n = int(row.get("sample_count") or 1)
        merged = [(o * n + v) / (n + 1) for o, v in zip(old, new_vec)]
        execute(
            "UPDATE voice_speaker_profiles SET embedding = %s, sample_count = %s, updated_at = now() WHERE name = %s",
            (json.dumps(merged), n + 1, name),
        )
    else:
        execute(
            "INSERT INTO voice_speaker_profiles (name, embedding, sample_count) VALUES (%s, %s, 1) "
            "ON CONFLICT (name) DO UPDATE SET embedding = EXCLUDED.embedding, sample_count = 1, updated_at = now()",
            (name, json.dumps(new_vec)),
        )
    logger.info("SPEAKER-ID: enrolled voiceprint for '%s'", name)
    return True


def identify(pcm16: bytes, sample_rate: int = 24000) -> tuple[str | None, float]:
    """Return (best-matching name, score) for an audio sample.

    (None, score) if no enrolled profile clears MATCH_THRESHOLD, or if speaker-ID
    is unavailable.
    """
    if not available():
        return (None, 0.0)
    vec = embed(pcm16, sample_rate)
    if vec is None:
        return (None, 0.0)
    _ensure_schema()
    rows = fetch_all("SELECT name, embedding FROM voice_speaker_profiles")
    best_name, best_score = None, 0.0
    for r in rows:
        emb = r.get("embedding")
        if not emb:
            continue
        score = _cosine(vec, emb)
        if score > best_score:
            best_name, best_score = r["name"], score
    if best_score >= MATCH_THRESHOLD:
        return (best_name, best_score)
    return (None, best_score)


def list_profiles() -> list[dict]:
    """Enrolled names + sample counts (no embeddings)."""
    _ensure_schema()
    return fetch_all(
        "SELECT name, sample_count, updated_at FROM voice_speaker_profiles ORDER BY name"
    ) or []


def delete_profile(name: str) -> bool:
    _ensure_schema()
    return execute("DELETE FROM voice_speaker_profiles WHERE name = %s", ((name or "").strip().lower(),)) > 0
