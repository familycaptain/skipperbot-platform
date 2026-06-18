#!/usr/bin/env python3
"""Read-only Evolve lookup — fetch a run's gate packet + activity from the operator's Pi so the
assistant (Claude) can explain an Evolve item in plain language. READ ONLY: only GETs; it never
decides, resolves, or mutates a gate.

    python3 scripts/evolve_explain.py list             # runs + the gates waiting on you
    python3 scripts/evolve_explain.py 13               # loose-resolve -> poc-13, print its digest
    python3 scripts/evolve_explain.py ev-12f8541f      # exact instance id
    python3 scripts/evolve_explain.py poc-1 --events   # also show recent activity
    python3 scripts/evolve_explain.py poc-1 --json     # raw packet JSON (everything)

The GET endpoints need no auth; EVOLVE_PLATFORM_TOKEN (from .env) is sent as Bearer if present —
never printed. Pi URL: $EVOLVE_PI_URL (default http://skipper-pi.local:8000).
"""
import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_envf = os.path.join(ROOT, ".env")
for _l in (open(_envf) if os.path.exists(_envf) else []):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

BASE = (os.getenv("EVOLVE_PI_URL") or "http://skipper-pi.local:8000").rstrip("/")
API = BASE + "/api/apps/evolve"
TOK = os.getenv("EVOLVE_PLATFORM_TOKEN")


def _get(path):
    headers = {"Authorization": f"Bearer {TOK}"} if TOK else {}
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _runs():
    return _get("/runs").get("runs", [])


def resolve(token, runs):
    ids = [r["instance_id"] for r in runs]
    if token in ids:
        return token
    cands = ([i for i in ids if i.split("-")[-1] == token]      # "13" -> *-13
             or [i for i in ids if i.endswith(token)]
             or [i for i in ids if token in i])
    if len(cands) == 1:
        return cands[0]
    if not cands:
        sys.exit(f"no run matches '{token}'. Known ids: {', '.join(ids) or '(none)'}")
    sys.exit(f"'{token}' is ambiguous — matches: {', '.join(cands)}")


def _line(label, val):
    if val:
        print(f"  {label}: {val}")


def _aslist(v):
    """Coerce a maybe-list field to a list so we never iterate a string char-by-char
    (agent JSON sometimes emits a scalar where the schema says array)."""
    if isinstance(v, list):
        return v
    if v in (None, "", {}):
        return []
    return [v]


def digest(iid, runs):
    run = next((r for r in runs if r["instance_id"] == iid), {})
    try:
        g = _get(f"/gates/{iid}")
    except Exception:
        g = {}
    pkt = g.get("packet") or g or {}

    print("=" * 78)
    print(f"{iid}  —  {run.get('title') or pkt.get('work_item', {}).get('title') or ''}")
    print("=" * 78)
    _line("status", run.get("status"))
    _line("phase", run.get("phase"))
    _line("source", run.get("source"))
    _line("gate", g.get("gate") or pkt.get("gate"))
    _line("gate status", g.get("status"))
    if g.get("decision"):
        _line("operator decision", f"{g.get('decision')}  (note: {g.get('note') or '—'})")
    if run.get("cost_usd"):
        _line("spend", f"${run['cost_usd']:.2f}")

    wi = pkt.get("work_item") or {}
    if wi.get("body"):
        print("\n-- Work item --")
        print("  " + wi["body"].strip().replace("\n", "\n  "))

    rec = pkt.get("recommendation") or {}
    if rec:
        print("\n-- Lead's recommendation --")
        _line("action", rec.get("action"))
        _line("why", rec.get("why") or rec.get("rationale"))
        _line("today", rec.get("current"))
        _line("after this change", rec.get("after"))

    for d in (pkt.get("decisions_needed") or []):
        print("\n-- Decision for you --")
        _line("question", d.get("question"))
        _line("options", " | ".join(d.get("options") or []))
        _line("recommends", d.get("recommendation"))

    prop = pkt.get("proposal") or {}
    if prop.get("spec_id") or prop.get("behavior"):
        print("\n-- Proposed spec --")
        _line("id", prop.get("spec_id"))
        _line("title", prop.get("title"))
        _line("behavior", prop.get("behavior"))
        for t in _aslist(prop.get("tests")):
            _line("test", f"{t.get('path') or t.get('type')} — {t.get('rubric', '')}")
        _line("notes", prop.get("notes"))

    cp = pkt.get("code_plan") or {}
    if cp:
        print("\n-- Planned code changes (code scout, read-only) --")
        _line("summary", cp.get("summary"))
        _line("approach", cp.get("approach"))
        for c in _aslist(cp.get("changes")):
            _line(f"[{c.get('action')}]", f"{c.get('path')} — {c.get('what', '')}")
        for n in _aslist(cp.get("new_modules")):
            _line("new module", n)
        for n in _aslist(cp.get("placement_notes")):
            _line("placement", n)
        for n in _aslist(cp.get("risks")):
            _line("risk", n)
        for n in _aslist(cp.get("open_questions")):
            _line("open question", n)

    st = pkt.get("spec_tree")
    if isinstance(st, list) and len(st) > 1:
        print("\n-- Spec tree --")
        for s in st:
            _line(s.get("spec_id"), f"{s.get('title', '')} — {s.get('summary', '')}")

    for a in (pkt.get("agents") or []):
        o = a.get("output") or {}
        print(f"\n-- {a.get('label') or a.get('key')} --")
        _line("summary", o.get("summary"))
        if "approve" in o:
            _line("approve", o.get("approve"))
        for c in _aslist(o.get("concerns")):
            _line(f"concern[{c.get('severity')}]", c.get("detail"))
        for c in _aslist(o.get("findings")):
            _line(f"finding[{c.get('severity')}]", f"{c.get('category', '')}: {c.get('detail', '')}")
        for c in _aslist(o.get("conflicts")):
            _line("conflict", f"{c.get('with_spec', '')}: {c.get('detail', '')}")

    val = pkt.get("validation")
    if val:
        print("\n-- Validation (box 2) --")
        _line("passed", val.get("passed"))
        _line("reason", val.get("reason"))
    if pkt.get("diff"):
        n = pkt["diff"].count("\n") + 1
        print(f"\n-- Diff available ({n} lines) — re-run with --json to see it --")
    if pkt.get("feature", {}).get("branch"):
        _line("branch", pkt["feature"]["branch"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("item", nargs="?", help="run id or loose token (e.g. 13, poc-13, ev-12f8541f); omit/`list` to list")
    ap.add_argument("--json", action="store_true", help="dump the raw gate packet JSON")
    ap.add_argument("--events", action="store_true", help="also show recent activity events")
    a = ap.parse_args()

    runs = _runs()

    if not a.item or a.item == "list":
        waiting = {g["instance_id"] for g in _get("/gates?status=waiting").get("gates", [])}
        print(f"{len(runs)} run(s) on {BASE}:")
        for r in sorted(runs, key=lambda r: r["instance_id"]):
            flag = "  <-- WAITING ON YOU" if r["instance_id"] in waiting else ""
            print(f"  {r['instance_id']:<16} {r.get('status', ''):<9} {r.get('phase', ''):<8} {r.get('title', '')}{flag}")
        return

    iid = resolve(a.item, runs)

    if a.json:
        print(json.dumps(_get(f"/gates/{iid}"), indent=2))
        return

    digest(iid, runs)

    if a.events:
        evs = _get(f"/runs/{iid}/events").get("events", [])
        print(f"\n-- Recent activity ({len(evs)} events) --")
        for e in evs[-40:]:
            print(f"  [{e.get('agent', '')}/{e.get('kind', '')}] {e.get('message', '')}")


if __name__ == "__main__":
    main()
