"""Live voice debug stream — one watchable place for the WHOLE voice pipeline.

Voice problems are hard to debug because the signal is split across the agent
container log (relay + speaker-ID, server side) and the satellite console
(wake/listen/transcribe, on the device). This is an in-memory ring buffer that
both sides push into, exposed over HTTP (GET /api/voice/debug) so the operator —
and an assistant watching remotely — can follow turn capture, speaker-ID, and
transcripts as they happen, live, from a single endpoint.

Best-effort + in-memory only (capped ring, never persisted). A `RingHandler`
mirrors existing ``logger.info("VOICE…"/"SPEAKER-ID…")`` lines in automatically,
so server-side voice logs appear with no call-site changes; the relay also pushes
richer events (partial/final transcripts) explicitly, and the satellite POSTs its
own events to /api/voice/debug.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

_MAX = 800
_lock = threading.Lock()
_buf: deque = deque(maxlen=_MAX)
_seq = 0


def record(message: str, *, source: str = "platform", level: str = "info",
           session: str = "", **fields) -> int:
    """Append one event to the ring; returns its monotonic id."""
    global _seq
    with _lock:
        _seq += 1
        entry = {"id": _seq, "ts": round(time.time(), 3), "source": source,
                 "level": level, "session": session, "message": message}
        if fields:
            entry.update(fields)
        _buf.append(entry)
        return _seq


def since(after_id: int = 0, limit: int = 400) -> list[dict]:
    """Events with id > after_id (oldest→newest), capped to the last `limit`."""
    with _lock:
        items = [e for e in _buf if e["id"] > after_id]
    return items[-limit:]


class _RingHandler(logging.Handler):
    """Mirror voice-related log records into the ring without touching call sites."""
    _PREFIXES = ("VOICE", "SPEAKER-ID")

    def emit(self, rec: logging.LogRecord) -> None:
        try:
            msg = rec.getMessage()
        except Exception:
            return
        if not any(msg.startswith(p) for p in self._PREFIXES):
            return
        record(msg, source="platform", level=rec.levelname.lower())


_installed = False


def install() -> None:
    """Attach the ring handler to the root logger once (idempotent). Safe to call
    on every voice-session start."""
    global _installed
    if _installed:
        return
    h = _RingHandler()
    h.setLevel(logging.INFO)
    logging.getLogger().addHandler(h)
    _installed = True
    record("voice debug stream attached", level="info")
