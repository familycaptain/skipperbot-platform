#!/usr/bin/env python
"""POC reporting bridge — let the in-session `/loop` Evolve (the `evolve` skill) surface its run,
per-agent activity, and gates in the SAME Evolve UI as production. Thin wrapper over
platform_bridge so the skill can report with one-line CLI calls. POC ids are prefixed `poc-` so the
production poller ignores them (the POC session owns its own gate loop).

    python scripts/evolve_poc.py run poc-3 --title "Add doc for Backup setup" --source github:..#3 --status running
    python scripts/evolve_poc.py event poc-3 triage agent_end "✓ proceed · feature"
    python scripts/evolve_poc.py gate  poc-3 gate1 ~/.evolve-poc/3/gate1.json
    python scripts/evolve_poc.py decision poc-3        # -> {"decision": "approve"|null, "note": ...}
    python scripts/evolve_poc.py resolve poc-3 merged  # clear the gate after acting on the decision
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
for _line in (open(os.path.join(ROOT, ".env")) if os.path.exists(".env") else []):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from apps.evolve import platform_bridge as bridge


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("iid")
    for opt in ("title", "source", "phase", "status", "agent", "node"):
        r.add_argument(f"--{opt}", default="")
    e = sub.add_parser("event")
    e.add_argument("iid"); e.add_argument("agent"); e.add_argument("kind"); e.add_argument("message")
    g = sub.add_parser("gate")
    g.add_argument("iid"); g.add_argument("gate"); g.add_argument("packet_file")
    d = sub.add_parser("decision"); d.add_argument("iid")
    rs = sub.add_parser("resolve"); rs.add_argument("iid"); rs.add_argument("status")
    a = ap.parse_args()

    if a.cmd == "run":
        print(bridge.report_run(a.iid, title=a.title, source=a.source, phase=a.phase,
                                status=a.status, current_agent=a.agent, current_node=a.node))
    elif a.cmd == "event":
        print(bridge.report_run(a.iid, current_agent=a.agent,
                                events=[{"agent": a.agent, "kind": a.kind, "message": a.message}]))
    elif a.cmd == "gate":
        packet = json.load(open(os.path.expanduser(a.packet_file)))
        packet["instance"] = a.iid
        packet["gate"] = a.gate
        print(bridge.push_gate(packet))
    elif a.cmd == "decision":
        dec = [x for x in bridge.list_decided() if x.get("instance_id") == a.iid]
        print(json.dumps({"decision": dec[0]["decision"] if dec else None,
                          "note": dec[0].get("note") if dec else None}))
    elif a.cmd == "resolve":
        print(bridge.resolve(a.iid, a.status))


if __name__ == "__main__":
    main()
