#!/usr/bin/env python3
"""box2_drive.py — thin 'hands' for driving box2's live Skipper from an interactive Claude
session (the BRAIN lives in Claude, NOT here — there is no LLM in this file). stdlib only.

Subcommands:
  signup <user> <pw> [display]   create the primary user, save the auth token, print result
  say "<message>"                send ONE chat turn; print Skipper's reply + the tool_calls
  history [n]                    print the last n rendered chat messages (raw)
  state                          print the goals summary (onboarding goal/agenda/tasks + done)
  whoami                         print the saved user/token presence

Each turn is stateless — the token saved in ~/.box2_drive.json carries the session, so the
Claude driver issues one `say` per turn over SSH and reasons/judges in its own context.
"""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("BOX2_BASE", "http://localhost:8000")
STATE = os.path.expanduser("~/.box2_drive.json")


def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save(d):
    json.dump(d, open(STATE, "w"))


def _req(method, path, body=None, token=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:800]
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body


def signup(user, pw, display=""):
    st, res = _req("POST", "/api/onboarding/create-user", {
        "username": user, "display_name": display or user.capitalize(),
        "password": pw, "timezone": "America/Chicago",
    })
    tok = res.get("token") if isinstance(res, dict) else None
    if tok:
        _save({"user": user, "token": tok})
    shown = res
    if isinstance(res, dict):
        shown = {k: ("<token>" if k == "token" else v) for k, v in res.items()}
    print(json.dumps({"http": st, "saved_token": bool(tok), "res": shown}, indent=2, default=str))


def _tool_calls_from_history(token, n=8):
    st, hist = _req("GET", f"/api/chat/history?limit={n}", token=token)
    items = hist if isinstance(hist, list) else (hist.get("messages") or hist.get("history") or []) if isinstance(hist, dict) else []
    calls = []
    for m in items if isinstance(items, list) else []:
        tc = (m.get("tool_calls") or m.get("tool_call")) if isinstance(m, dict) else None
        if tc:
            calls.append(tc)
    return st, calls, hist


def say(message):
    s = _load()
    user, token = s.get("user"), s.get("token")
    if not user:
        sys.exit("no saved user — run `signup` first")
    st, res = _req("POST", "/chat", {"user_id": user, "message": message}, token=token)
    reply = res.get("response") if isinstance(res, dict) else res
    hst, calls, _ = _tool_calls_from_history(token)
    print(json.dumps({"you": message, "http": st, "skipper": reply, "tool_calls": calls},
                     indent=2, default=str))


def history(n="12"):
    s = _load()
    st, _, hist = _tool_calls_from_history(s.get("token"), int(n))
    print(json.dumps({"http": st, "history": hist}, indent=2, default=str))


def state():
    s = _load()
    st, res = _req("GET", "/api/apps/goals/summary", token=s.get("token"))
    print(json.dumps({"http": st, "goals": res}, indent=2, default=str))


def whoami():
    s = _load()
    print(json.dumps({"user": s.get("user"), "has_token": bool(s.get("token"))}, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    args = sys.argv[2:]
    fn = {"signup": signup, "say": say, "history": history, "state": state, "whoami": whoami}.get(cmd)
    if not fn:
        sys.exit(__doc__)
    fn(*args)
