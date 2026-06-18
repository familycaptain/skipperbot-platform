#!/usr/bin/env python
"""Evolve `/loop` reporting bridge — let the in-session `/loop` Evolve (the `evolve` skill) surface its
run, per-agent activity, and gates in the SAME Evolve UI as production. Thin wrapper over
platform_bridge so the skill can report with one-line CLI calls. Run ids are prefixed `ev-` (legacy
`poc-`) so the production poller ignores them (the in-session engine owns its own gate loop). The id
is opaque to this script — it's passed in; the filename stays `evolve_poc.py` for call-compat.

    python scripts/evolve_poc.py run ev-3 --title "Add doc for Backup setup" --source github:..#3 --status running
    python scripts/evolve_poc.py event ev-3 triage agent_end "✓ proceed · feature"
    python scripts/evolve_poc.py emit-file ev-3 spec-author ~/.evolve-poc/3/spec.json  # post a big artifact by PATH (keeps it out of the loop's context)
    python scripts/evolve_poc.py gate  ev-3 gate1 ~/.evolve-poc/3/gate1.json
    python scripts/evolve_poc.py decision ev-3        # -> {"decision": "approve"|null, "note": ...}
    python scripts/evolve_poc.py resolve ev-3 merged  # clear the gate after acting on the decision
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
    # emit-file: post a (large) artifact's contents to the UI log WITHOUT the orchestrator carrying
    # the full text in its context — it passes a PATH; this script reads + posts it. Use for the big
    # emits (full spec, reviewer findings, the diff) you already wrote to ~/.evolve-poc/<n>/.
    ef = sub.add_parser("emit-file")
    ef.add_argument("iid"); ef.add_argument("agent"); ef.add_argument("file")
    ef.add_argument("--kind", default="emit")
    g = sub.add_parser("gate")
    g.add_argument("iid"); g.add_argument("gate"); g.add_argument("packet_file")
    d = sub.add_parser("decision"); d.add_argument("iid")
    rs = sub.add_parser("resolve"); rs.add_argument("iid"); rs.add_argument("status")
    c = sub.add_parser("close"); c.add_argument("iid"); c.add_argument("comment", nargs="?", default="")
    a = ap.parse_args()

    if a.cmd == "run":
        print(bridge.report_run(a.iid, title=a.title, source=a.source, phase=a.phase,
                                status=a.status, current_agent=a.agent, current_node=a.node))
    elif a.cmd == "event":
        print(bridge.report_run(a.iid, current_agent=a.agent,
                                events=[{"agent": a.agent, "kind": a.kind, "message": a.message}]))
    elif a.cmd == "emit-file":
        text = open(os.path.expanduser(a.file)).read()
        print(bridge.report_run(a.iid, current_agent=a.agent,
                                events=[{"agent": a.agent, "kind": a.kind, "message": text}]))
    elif a.cmd == "gate":
        packet = json.load(open(os.path.expanduser(a.packet_file)))
        packet["instance"] = a.iid
        packet["gate"] = a.gate
        print(bridge.push_gate(packet))
    elif a.cmd == "decision":
        dec = [x for x in bridge.list_decided() if x.get("instance_id") == a.iid]
        print(json.dumps({"decision": dec[0]["decision"] if dec else None,
                          "note": dec[0].get("note") if dec else None,
                          "gate": dec[0].get("gate") if dec else None}))
    elif a.cmd == "resolve":
        out = bridge.resolve(a.iid, a.status)
        # Keep the run row in lockstep with the gate outcome so it can never be left "running"
        # after a terminal gate (the two-step "resolve then report status" used to drop the 2nd).
        run_status, phase = {
            "cleared":  ("building", "build"),       # gate-1 approved → build begins
            "shipped":  ("waiting", "verify"),       # gate-2 approved + merged → awaiting operator test
            "merged":   ("merged", "done"),          # gate-3 VERIFIED works → truly done
            "rejected": ("rejected", "rejected"),
        }.get(a.status, ("", ""))
        if run_status:
            bridge.report_run(a.iid, status=run_status, phase=phase)
        print(out)
    elif a.cmd == "close":
        # close the loop — only after the operator verifies the shipped change works
        from apps.evolve import github_connector as gh
        num = int(str(a.iid).split("-")[-1])
        print(gh.close_issue(num, comment=a.comment))


if __name__ == "__main__":
    main()
