"""Bridge between the Evolve engine (box 1) and the platform's Evolve UI work queue.

The engine pushes a parked gate's review packet to the platform over HTTP (POST /gates),
where the operator sees it and decides; a poller reads decided rows back so the engine
can resume. This is the box-1 -> platform side of EVOLVE.md §9 (the work queue). stdlib
only. Config via env (set in .env — no operator-specific host or credential is committed):
    EVOLVE_PLATFORM_URL    the operator platform (Pi) base URL; defaults to localhost only
    EVOLVE_PLATFORM_TOKEN  long-lived service token (preferred auth)
    EVOLVE_PLATFORM_USER   admin username for the local-dev login fallback
    EVOLVE_PLATFORM_PASS   admin password for the local-dev login fallback (no default)
"""
import json
import os
import urllib.request

_token_cache = {"tok": None}


def _base() -> str:
    return (os.getenv("EVOLVE_PLATFORM_URL") or "http://localhost:8000").rstrip("/")


def _post(path: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(_base() + path, data=json.dumps(body).encode(),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(_base() + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def auth() -> str:
    """The brain authenticates to the operator platform with a long-lived SERVICE
    token (EVOLVE_PLATFORM_TOKEN) — minted on the Pi via scripts/service_token.py.
    Its is_service flag permits POSTing gates but NOT deciding them (least privilege).
    Falls back to an admin login only for local dev (box 2)."""
    if _token_cache["tok"]:
        return _token_cache["tok"]
    svc = os.getenv("EVOLVE_PLATFORM_TOKEN")
    if svc:
        _token_cache["tok"] = svc
        return svc
    user = os.getenv("EVOLVE_PLATFORM_USER", "admin")
    pw = os.getenv("EVOLVE_PLATFORM_PASS", "")  # no committed default credential
    if not pw:
        raise RuntimeError("set EVOLVE_PLATFORM_TOKEN (preferred) or EVOLVE_PLATFORM_PASS in .env")
    try:
        _post("/auth/login", {"username": user})  # step 1: existence/typo check
    except Exception:
        pass
    res = _post("/auth/login", {"username": user, "password": pw})
    if not res.get("token"):
        raise RuntimeError(f"platform login failed (no EVOLVE_PLATFORM_TOKEN set): {res}")
    _token_cache["tok"] = res["token"]
    return res["token"]


# --- offline outbox -----------------------------------------------------------
# The Pi goes down during a `skipper update`. Rather than lose the agents' status/gate
# post-backs, buffer them on box 1 and flush in FIFO order once the Pi is reachable
# again — every write reconciles on the Pi exactly once, in order, when it's back up.
import socket
import urllib.error

_OUTBOX = os.path.expanduser(os.getenv("EVOLVE_OUTBOX", "~/.evolve/outbox.jsonl"))


def _is_conn_error(e: Exception) -> bool:
    # connection-level failure (Pi down/unreachable) — NOT an HTTP 4xx/5xx (a real error
    # that retrying won't fix, so we must not buffer it forever).
    if isinstance(e, urllib.error.HTTPError):
        return False
    return isinstance(e, (urllib.error.URLError, socket.timeout, ConnectionError, OSError))


def _enqueue(path: str, body: dict) -> None:
    os.makedirs(os.path.dirname(_OUTBOX), exist_ok=True)
    with open(_OUTBOX, "a") as f:
        f.write(json.dumps({"path": path, "body": body}) + "\n")


def _flush() -> None:
    """Deliver buffered post-backs in order; stop at the first connection error (Pi still down)."""
    if not os.path.exists(_OUTBOX):
        return
    lines = [l for l in open(_OUTBOX).read().splitlines() if l.strip()]
    if not lines:
        return
    try:
        token = auth()
    except Exception:
        return                                   # can't even auth → leave the queue intact
    done = 0
    for line in lines:
        try:
            item = json.loads(line)
            _post(item["path"], item["body"], token)
            done += 1
        except Exception as e:
            if _is_conn_error(e):
                break                            # Pi still down — keep this and the rest
            done += 1                            # poison/HTTP error → drop it, don't block the queue
    tail = lines[done:]
    if tail:
        open(_OUTBOX, "w").write("\n".join(tail) + "\n")
    elif os.path.exists(_OUTBOX):
        os.remove(_OUTBOX)


def _send(path: str, body: dict) -> dict:
    """Resilient write: flush any backlog first, then post — buffering this one if the Pi is down."""
    _flush()
    try:
        return _post(path, body, auth())
    except Exception as e:
        if _is_conn_error(e):
            _enqueue(path, body)
            return {"queued": True, "path": path}
        raise


def push_gate(packet: dict, token: str | None = None) -> dict:
    """Surface a parked gate in the operator's work queue (on the Pi). Buffered if the Pi is down."""
    return _send("/api/apps/evolve/gates", {
        "instance_id": packet.get("instance"),
        "gate": packet.get("gate"),
        "packet": packet,
    })


def list_decided(token: str | None = None) -> list[dict]:
    """Gates the operator has decided in the UI (for the resume poller). If the Pi is unreachable
    (e.g. mid `skipper update`), return [] — no decisions are visible right now; the loop keeps
    working new GitHub issues and reconciles once the Pi is back. Never let a Pi outage crash it.

    FLUSH-FIRST: the loop calls this at the START of every pass (its decided-gate scan), so draining
    the outbox here guarantees buffered reports go out even for a PARKED item whose own pass does no
    `_send` — otherwise a terminal report buffered during a Pi restart (e.g. a Gate-2 push) could
    strand until some *other* item happened to write. `_flush` is a no-op when the outbox is empty and
    self-handles a still-down Pi (keeps the queue), so this is cheap and safe every pass."""
    _flush()
    try:
        return _get("/api/apps/evolve/gates?status=decided", token or auth()).get("gates", [])
    except Exception as e:
        if _is_conn_error(e):
            return []
        raise


def resolve(instance_id: str, status: str, token: str | None = None) -> dict:
    """Mark a decided gate's terminal outcome after the engine resumed it. Buffered if the Pi is down."""
    return _send(f"/api/apps/evolve/gates/{instance_id}/resolve", {"status": status})


def report_run(instance_id: str, *, title="", source="", phase="", status="",
               current_agent="", current_node="", cost_usd=None, events=None,
               token: str | None = None) -> dict:
    """Report a run's status + a batch of activity events to the mission-control view
    (one POST does both). Best-effort observability — buffered if the Pi is down, flushed in
    order when it's back, so a `skipper update` never loses run/event updates."""
    return _send("/api/apps/evolve/runs", {
        "instance_id": instance_id, "title": title, "source": source, "phase": phase,
        "status": status, "current_agent": current_agent, "current_node": current_node,
        "cost_usd": cost_usd, "events": events or [],
    })
