"""Background event emitter — ships the engine's live activity to the platform's
mission-control view WITHOUT blocking the build (EVOLVE.md §9).

The engine runs synchronously (a poll resumes one instance through minutes of implement +
validate). If we POSTed each agent step to the Pi inline, the HTTP latency would stack onto
the build. Instead the Runner / tool-use backend enqueue events here; a daemon thread
batches and flushes them every ~0.7 s. Best-effort: a flush failure is logged and dropped —
observability must never break the SDLC.
"""
from __future__ import annotations

import queue
import threading


class EventEmitter:
    def __init__(self, flush_fn, *, interval: float = 0.7, log=lambda *a: None):
        # flush_fn(instance_id, fields: dict, events: list[dict]) -> None
        self.flush_fn = flush_fn
        self.interval = interval
        self.log = log
        self._q: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def start(self) -> "EventEmitter":
        if self._t is None:
            self._t = threading.Thread(target=self._loop, daemon=True)
            self._t.start()
        return self

    # producers (called from the engine thread) -----------------------------
    def run(self, instance_id: str, **fields) -> None:
        if instance_id:
            self._q.put(("run", instance_id, fields))

    def event(self, instance_id: str, agent: str, kind: str, message: str) -> None:
        if instance_id:
            self._q.put(("event", instance_id, {"agent": agent, "kind": kind, "message": message}))

    # the flusher -----------------------------------------------------------
    def _drain(self) -> dict:
        batches: dict = {}
        try:
            while True:
                typ, iid, payload = self._q.get_nowait()
                b = batches.setdefault(iid, {"fields": {}, "events": []})
                if typ == "run":
                    b["fields"].update(payload)
                else:
                    b["events"].append(payload)
        except queue.Empty:
            pass
        return batches

    def _flush(self) -> None:
        for iid, b in self._drain().items():
            try:
                self.flush_fn(iid, b["fields"], b["events"])
            except Exception as e:
                self.log(f"  emit flush failed: {type(e).__name__}: {e}")

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._flush()
        self._flush()   # final drain on stop

    def stop(self) -> None:
        self._stop.set()
        if self._t is not None:
            self._t.join(timeout=5)
        self._flush()
