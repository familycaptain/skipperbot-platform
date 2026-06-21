#!/usr/bin/env python3
"""Operate an Evolve gate ON THE OPERATOR'S EXPLICIT INSTRUCTION — approve / reject / change a
parked gate, recording the operator's note. The WRITE counterpart to the read-only evolve_explain.py.

    python3 scripts/evolve_decide.py <id> approve "confirmed scope / answers to the decisions"
    python3 scripts/evolve_decide.py <id> change  "ordered list of requirement revisions"
    python3 scripts/evolve_decide.py <id> reject  "reason"

AUTH — this is the whole security model the operator asked for:
  * Uses EVOLVE_DECIDE_TOKEN, a PARENT-role token, set in .env ONLY on the operator's assistant
    machine (where Claude runs). It is NEVER placed on box 1 / the autonomous loop, so the Evolve
    AGENTS cannot decide gates — only the operator, via their assistant, can.
  * The decision is recorded as the token's principal (the operator).
  * The Pi base URL comes from $EVOLVE_PI_URL / $EVOLVE_PLATFORM_URL; nothing is hardcoded.

Claude runs this ONLY when the operator explicitly says to decide a SPECIFIC item, and only after
echoing back the exact decision + note for a final confirmation. Never autonomously, never to clear a
backlog, never inferred — an explicit per-item instruction each time.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_envf = os.path.join(ROOT, ".env")
for _l in (open(_envf) if os.path.exists(_envf) else []):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

BASE = (os.getenv("EVOLVE_PI_URL") or os.getenv("EVOLVE_PLATFORM_URL") or "http://localhost:8000").rstrip("/")
API = BASE + "/api/apps/evolve"
TOK = os.getenv("EVOLVE_DECIDE_TOKEN")


def _get(path):
    headers = {"Authorization": f"Bearer {TOK}"} if TOK else {}
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _resolve(token):
    ids = [r["instance_id"] for r in _get("/runs").get("runs", [])]
    if token in ids:
        return token
    cands = ([i for i in ids if i.split("-")[-1] == token]
             or [i for i in ids if i.endswith(token)]
             or [i for i in ids if token in i])
    if len(cands) == 1:
        return cands[0]
    sys.exit(f"'{token}' -> {cands or 'no match'}; known ids: {', '.join(ids)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("item", help="run id or loose token (e.g. 26, ev-26)")
    ap.add_argument("decision", choices=["approve", "reject", "change"])
    ap.add_argument("note", nargs="?", default="", help="operator's answers + free-text guidance")
    a = ap.parse_args()

    if not TOK:
        sys.exit("EVOLVE_DECIDE_TOKEN is not set in .env — assistant gate-operation is not configured "
                 "yet (one-time: mint a parent-role token on the platform and put it in this machine's "
                 ".env). Refusing to act.")

    iid = _resolve(a.item)
    body = json.dumps({"decision": a.decision, "note": a.note}).encode()
    req = urllib.request.Request(f"{API}/gates/{iid}/decision", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        if e.code == 403:
            sys.exit(f"403 — EVOLVE_DECIDE_TOKEN lacks parent/admin role (or is wrong). {detail}")
        sys.exit(f"decision rejected (HTTP {e.code}): {detail}")
    print(f"{iid}: {res.get('decision', '?')} recorded.\n  note: {a.note[:160]}")


if __name__ == "__main__":
    main()
