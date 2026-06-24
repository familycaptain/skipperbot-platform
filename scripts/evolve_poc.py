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
    python scripts/evolve_poc.py decision ev-3        # -> {"decision": "approve"|null, "note": ...} (ONE item)
    python scripts/evolve_poc.py pending              # -> [EVERY item with a live operator decision] in ONE Pi call (the loop's per-pass scan)
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
    sub.add_parser("pending")  # bulk: EVERY item with a live operator decision, in ONE Pi call
    sub.add_parser("stranded")  # local: ONLY run dirs stranded mid-segment (phase new|build)
    rs = sub.add_parser("resolve"); rs.add_argument("iid"); rs.add_argument("status")
    c = sub.add_parser("close"); c.add_argument("iid"); c.add_argument("comment", nargs="?", default="")
    sub.add_parser("flush")   # drain the offline outbox to the Pi now (no-op if empty / Pi down)
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
    elif a.cmd == "pending":
        # ONE Pi call returns EVERY item with a live operator decision (a decided gate, including a
        # re-opened 'done' item that came back at gate3). The loop iterates THIS short list instead of
        # calling `decision <id>` once per run dir — O(actionable), not O(all-runs-ever) — so the scan
        # stays cheap as closed/done items pile up. Each entry: instance_id + gate + decision + note;
        # route on `gate`, cross-ref the local ~/.evolve-poc/<n>/ dir for phase/artifacts.
        items = bridge.list_decided()
        print(json.dumps([{"instance_id": x.get("instance_id"), "gate": x.get("gate"),
                           "decision": x.get("decision"), "note": x.get("note")} for x in items]))
    elif a.cmd == "stranded":
        # Local scan of ~/.evolve-poc/*/state.json returning ONLY dirs stranded MID-SEGMENT — phase
        # `new` or `build` (a pass died before the segment finished). Filtered HERE so the loop never
        # reads all N state.json files into context; it ingests only the few stranded ids. Terminal
        # (done/rejected) and operator-PARKED (gate1/gate2/verify) phases are excluded — not stranded.
        # O(stranded), not O(all-runs-ever); tiny metadata only, never packet contents.
        import glob
        base = os.path.expanduser("~/.evolve-poc")
        out = []
        for sf in glob.glob(os.path.join(base, "*", "state.json")):
            try:
                st = json.load(open(sf))
            except Exception:
                continue
            if st.get("phase") in ("new", "build"):
                out.append({"instance_id": st.get("instance_id"), "phase": st.get("phase")})
        print(json.dumps(out))
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
    elif a.cmd == "flush":
        n = len(open(bridge._OUTBOX).read().splitlines()) if os.path.exists(bridge._OUTBOX) else 0
        bridge._flush()
        left = len(open(bridge._OUTBOX).read().splitlines()) if os.path.exists(bridge._OUTBOX) else 0
        print(json.dumps({"buffered": n, "remaining": left, "sent": n - left}))


if __name__ == "__main__":
    main()
