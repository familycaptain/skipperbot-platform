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


def login() -> str:
    if _token_cache["tok"]:
        return _token_cache["tok"]
    user = os.getenv("EVOLVE_PLATFORM_USER", "admin")
    pw = os.getenv("EVOLVE_PLATFORM_PASS", "admin1234")
    try:
        _post("/auth/login", {"username": user})  # step 1: existence/typo check
    except Exception:
        pass
    res = _post("/auth/login", {"username": user, "password": pw})
    if not res.get("token"):
        raise RuntimeError(f"platform login failed: {res}")
    _token_cache["tok"] = res["token"]
    return res["token"]


def push_gate(packet: dict, token: str | None = None) -> dict:
    """Surface a parked gate in the platform work queue."""
    token = token or login()
    return _post("/api/apps/evolve/gates", {
        "instance_id": packet.get("instance"),
        "gate": packet.get("gate"),
        "packet": packet,
    }, token)


def list_decided(token: str | None = None) -> list[dict]:
    """Gates the operator has decided in the UI (for the resume poller)."""
    token = token or login()
    return _get("/api/apps/evolve/gates?status=decided", token).get("gates", [])
