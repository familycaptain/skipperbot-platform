"""Bridge between the Evolve engine (box 1) and the platform's Evolve UI work queue.

The engine pushes a parked gate's review packet to the platform over HTTP (POST /gates),
where the operator sees it and decides; a poller reads decided rows back so the engine
can resume. This is the box-1 -> platform side of EVOLVE.md §9 (the work queue). stdlib
only. Config via env:
    EVOLVE_PLATFORM_URL    default http://evolve-test.local:8000
    EVOLVE_PLATFORM_USER   default admin
    EVOLVE_PLATFORM_PASS   default admin1234
"""
import json
import os
import urllib.request

_token_cache = {"tok": None}


def _base() -> str:
    return (os.getenv("EVOLVE_PLATFORM_URL") or "http://evolve-test.local:8000").rstrip("/")


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
    pw = os.getenv("EVOLVE_PLATFORM_PASS", "admin1234")
    try:
        _post("/auth/login", {"username": user})  # step 1: existence/typo check
    except Exception:
        pass
    res = _post("/auth/login", {"username": user, "password": pw})
    if not res.get("token"):
        raise RuntimeError(f"platform login failed (no EVOLVE_PLATFORM_TOKEN set): {res}")
    _token_cache["tok"] = res["token"]
    return res["token"]


def push_gate(packet: dict, token: str | None = None) -> dict:
    """Surface a parked gate in the operator's work queue (on the Pi)."""
    token = token or auth()
    return _post("/api/apps/evolve/gates", {
        "instance_id": packet.get("instance"),
        "gate": packet.get("gate"),
        "packet": packet,
    }, token)


def list_decided(token: str | None = None) -> list[dict]:
    """Gates the operator has decided in the UI (for the resume poller)."""
    token = token or auth()
    return _get("/api/apps/evolve/gates?status=decided", token).get("gates", [])


def resolve(instance_id: str, status: str, token: str | None = None) -> dict:
    """Mark a decided gate's terminal outcome after the engine resumed it."""
    token = token or auth()
    return _post(f"/api/apps/evolve/gates/{instance_id}/resolve", {"status": status}, token)


def report_run(instance_id: str, *, title="", source="", phase="", status="",
               current_agent="", current_node="", events=None,
               token: str | None = None) -> dict:
    """Report a run's status + a batch of activity events to the mission-control view
    (one POST does both). Best-effort observability — never let it break the engine."""
    token = token or auth()
    return _post("/api/apps/evolve/runs", {
        "instance_id": instance_id, "title": title, "source": source, "phase": phase,
        "status": status, "current_agent": current_agent, "current_node": current_node,
        "events": events or [],
    }, token)
