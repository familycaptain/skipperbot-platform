#!/usr/bin/env python
"""Ingest GitHub issues into Evolve — the real intake (EVOLVE.md §5/§8).

    python scripts/evolve_github_ingest.py list      # show open issues on the repo
    python scripts/evolve_github_ingest.py ingest    # submit NEW issues -> pipeline -> gate -> UI
    python scripts/evolve_github_ingest.py poll      # resume the engine on UI decisions

Each open issue becomes a work-item submitted at s_issue. The walk runs to a human gate;
the on_gate hook pushes the review packet to the platform's Evolve work queue (the UI)
and pings the operator via Pushover. `poll` reads the operator's UI decisions back and
resumes the engine via pipeline.approve(). Reasoning on Opus; cost to the shared ledger.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
for line in open(os.path.join(ROOT, ".env")) if os.path.exists(".env") else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from apps.evolve.engine import model as M
from apps.evolve.engine.instance import SqliteInstanceStore
from apps.evolve.agents.runner import Runner, AnthropicBackend
from apps.evolve.agents.registry import ROSTER
from apps.evolve.pipeline import Pipeline
from apps.evolve.workspace import WorkspaceManager
from apps.evolve.build_loop import implement_with_agent, remote_validate, RemoteBox2
from apps.evolve.cost import CostLedger
from apps.evolve import github_connector as gh
from apps.evolve import platform_bridge as bridge

STATE_DB = os.path.expanduser("~/.evolve/github.sqlite")
SEEN = os.path.expanduser("~/.evolve/github_ingested.json")
DEEP = os.getenv("EVOLVE_MODEL_DEEP", "claude-opus-4-8")
CAP = float(os.getenv("EVOLVE_MONTHLY_CAP", "500"))
BOX2_HOST = os.getenv("EVOLVE_BOX2_HOST", "evolve-test.local")
BOX2_REPO = os.getenv("EVOLVE_BOX2_REPO", "/home/skipper/repos/skipperbot-platform")


def _pushover(title, message, priority=1):
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("_pd", os.path.join(ROOT, "tools", "pushover_tool.py"))
        mod = ilu.module_from_spec(spec); spec.loader.exec_module(mod)
        print(" ", mod.send_pushover_direct(message, title=title, priority=priority))
    except Exception as e:
        print("  pushover failed:", e)


def on_gate(packet):
    """Surface a parked gate in the UI + ping the operator."""
    try:
        bridge.push_gate(packet)
        print(f"  -> pushed {packet.get('gate')} to the Evolve UI work queue")
    except Exception as e:
        print("  -> push_gate FAILED:", e)
    rec = packet.get("recommendation") or {}
    wi = packet.get("work_item") or {}
    label = {"gate1": "Gate 1 · approve intent", "gate2": "Gate 2 · approve result"}.get(packet.get("gate"), packet.get("gate"))
    _pushover(f"Evolve · {label}", f"{wi.get('title','(work item)')}\nRecommend: {rec.get('action','?')} — {rec.get('why','')}")


def build_pipeline():
    os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
    model = M.load("specs/evolve/sdlc.yaml")
    ledger = CostLedger()
    runner = Runner(AnthropicBackend(), dict(ROSTER), ledger=ledger, monthly_limit_usd=CAP, budget_usd=20.0)
    wm = WorkspaceManager(ROOT, worktrees_dir=os.path.expanduser("~/evolve-wt"), release="release")
    validate_fn = remote_validate(RemoteBox2(BOX2_HOST, BOX2_REPO), release="release",
                                  test_path="tests/evolve", log=print)
    store = SqliteInstanceStore(STATE_DB)

    class RealPipeline(Pipeline):
        def _code_acting(self, agent, inst):
            if agent == "implement":
                feat = self._feature(inst)
                spec_rec = inst.context.get("spec_record") or {"id": feat.item_id}
                wi = inst.context.get("work_item", {})
                impl = implement_with_agent(wi, spec_rec, model=DEEP, skills_dir=".claude/skills",
                                            ledger=ledger, monthly_limit_usd=CAP)(feat)
                ok = getattr(impl, "ok", False)
                if ok and self.wm.is_dirty(feat):
                    self.wm.commit(feat, f"implement {feat.item_id}")
                self.log(f"  implement ok={ok}")
                return {"ok": ok, "output": getattr(impl, "output", None) or {}}
            return super()._code_acting(agent, inst)

    return RealPipeline(model, runner=runner, wm=wm, implement_fn=lambda f: None,
                        validate_fn=validate_fn, store=store, log=print, on_gate=on_gate), runner, ledger


def _seen():
    return set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()


def _mark(num):
    s = _seen(); s.add(num); json.dump(sorted(s), open(SEEN, "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "ingest", "poll"])
    ap.add_argument("--all", action="store_true", help="ingest: re-submit even already-seen issues")
    args = ap.parse_args()

    if args.cmd == "list":
        for i in gh.list_open_issues():
            print(f"#{i['number']}: {i['title']}  (labels: {[l['name'] for l in i.get('labels', [])]})")
        return

    pipe, runner, ledger = build_pipeline()

    if args.cmd == "ingest":
        seen = _seen()
        issues = gh.list_open_issues()
        todo = [i for i in issues if args.all or i["number"] not in seen]
        print(f"{len(issues)} open, {len(todo)} to ingest")
        for issue in todo:
            wi = gh.issue_to_work_item(issue)
            print(f"\n=== ingest #{issue['number']}: {wi['title']} ===")
            inst = pipe.submit(wi)
            _mark(issue["number"])
            print(f"  instance {inst.id} status={inst.status} gate={pipe.gate_waiting(inst)}")
        print(f"\nthis-run reasoning spend: ${runner.spent_usd:.4f}  month-to-date: ${ledger.month_to_date():.4f}")

    elif args.cmd == "poll":
        decided = bridge.list_decided()
        print(f"{len(decided)} decided gate(s) in the UI")
        for g in decided:
            iid, decision = g["instance_id"], g["decision"]
            try:
                inst = pipe.approve(iid, decision)
                print(f"  {iid}: {decision} -> status={inst.status} gate={pipe.gate_waiting(inst)}")
            except Exception as e:
                print(f"  {iid}: resume failed: {e}")


if __name__ == "__main__":
    main()
