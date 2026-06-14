#!/usr/bin/env python
"""Drive ONE real work-item through the Evolve pipeline to a human stage gate.

Staged so each real (paid) step is observable:

    python scripts/evolve_run_bug.py submit          # triage->spec->reviews-> GATE 1 (block), print packet
    python scripts/evolve_run_bug.py gate1 approve    # serialize->implement(box1 worktree)->validate(box2)-> GATE 2
    python scripts/evolve_run_bug.py show             # reprint the current gate packet
    python scripts/evolve_run_bug.py diff             # show the feature-branch diff
    # (GATE 2 is the operator's call — this script never merges.)

Reasoning agents run on Opus via AnthropicBackend (shared cost ledger + $500/mo kill-switch).
The `implement` agent runs as a tool-use code-actor rooted in an isolated feature worktree
off `release`; `validate` deploys that branch to box 2 (evolve-test.local) and runs the
bound test there. State is durable (SQLite), so the stages can run as separate invocations.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

# --- env (.env holds ANTHROPIC_API_KEY on box 1) ---
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

STATE_DB = os.path.expanduser("~/.evolve/weather_run.sqlite")
IID_FILE = os.path.expanduser("~/.evolve/weather_run.iid")
DEEP = os.getenv("EVOLVE_MODEL_DEEP", "claude-opus-4-8")
MONTHLY_CAP = float(os.getenv("EVOLVE_MONTHLY_CAP", "500"))
BOX2_HOST = os.getenv("EVOLVE_BOX2_HOST", "evolve-test.local")
BOX2_REPO = os.getenv("EVOLVE_BOX2_REPO", "/home/skipper/repos/skipperbot-platform")

WORK_ITEM = {
    "title": "Weather chat tool reports the wrong city for ZIP 72956 (Rena, not Van Buren)",
    "body": (
        "Asking Skipper's chat weather tools for the current weather at ZIP 72956 reports the "
        "city as 'Rena, AR' (the user saw 'Reno'). The correct city for 72956 is Van Buren, AR. "
        "Right ZIP, wrong city.\n\n"
        "Root cause: get_current_weather_by_zip() in apps/weather/tools.py fetches from wttr.in and "
        "reads the city from nearest_area.areaName, which is wrong for this ZIP. Every OTHER weather "
        "tool (rain/hourly/daily) resolves the city via _lookup_zip() -> api.zippopotam.us, which "
        "correctly returns 'Van Buren'.\n\n"
        "Fix: make get_current_weather_by_zip() derive the displayed city/region from the "
        "authoritative ZIP lookup (_lookup_zip / zippopotam) rather than trusting wttr.in's area "
        "name, so all weather tools report a consistent, correct city. Keep using wttr.in for the "
        "live conditions if convenient, but the place name must come from the ZIP lookup.\n\n"
        "Add a self-contained regression test at tests/evolve/test_weather_zip_city.py that asserts "
        "the resolved city/region for ZIP 72956 is 'Van Buren' / 'AR'. Mock the network calls — the "
        "test must not hit the live API."
    ),
}


def _send_pushover(*a, **k):
    # Load pushover_tool.py directly — the tools package __init__ pulls in the DB stack.
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("_pushover_direct", os.path.join(ROOT, "tools", "pushover_tool.py"))
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.send_pushover_direct(*a, **k)


def gate_notify(pkt):
    """Pushover the operator when a work-item parks at a human gate (EVOLVE.md §9 work
    queue, MVP path: direct from box 1). Leads with the recommendation, never a bare ask."""
    send_pushover_direct = _send_pushover
    gate = pkt.get("gate")
    rec = pkt.get("recommendation") or {}
    wi = pkt.get("work_item") or {}
    label = {"gate1": "Gate 1 · approve intent", "gate2": "Gate 2 · approve result"}.get(gate, gate)
    msg = (f"{wi.get('title', '(work item)')}\n"
           f"Recommend: {rec.get('action', '?')} — {rec.get('why', '')}\n"
           f"Instance {pkt.get('instance')} · reply to advance the gate.")
    print(send_pushover_direct(msg[:900], title=f"Evolve · {label}", priority=1))


def build_pipeline():
    os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
    model = M.load("specs/evolve/sdlc.yaml")
    ledger = CostLedger()
    runner = Runner(AnthropicBackend(), dict(ROSTER), ledger=ledger,
                    monthly_limit_usd=MONTHLY_CAP, budget_usd=20.0)
    wm = WorkspaceManager(ROOT, worktrees_dir=os.path.expanduser("~/evolve-wt"), release="release")
    box2 = RemoteBox2(BOX2_HOST, BOX2_REPO)
    validate_fn = remote_validate(box2, release="release", test_path="tests/evolve", log=print)
    store = SqliteInstanceStore(STATE_DB)

    # The real `implement` needs the instance's work_item + serialized spec, which the
    # base Pipeline doesn't pass to implement_fn. Subclass to inject the real code-actor.
    class RealPipeline(Pipeline):
        def _code_acting(self, agent, inst):
            if agent == "implement":
                feat = self._feature(inst)
                spec_rec = inst.context.get("spec_record") or {"id": feat.item_id}
                wi = inst.context.get("work_item", {})
                impl = implement_with_agent(wi, spec_rec, model=DEEP,
                                            skills_dir=".claude/skills", ledger=ledger,
                                            monthly_limit_usd=MONTHLY_CAP)(feat)
                ok = getattr(impl, "ok", False)
                if ok and self.wm.is_dirty(feat):
                    self.wm.commit(feat, f"implement {feat.item_id}")
                self.log(f"  implement ok={ok}  output={getattr(impl, 'output', None)}")
                if not ok:
                    self.log(f"  implement ERROR: {getattr(impl, 'error', '')}")
                    self.log("  transcript tail:\n" + (getattr(impl, "raw_text", "") or "")[-1500:])
                return {"ok": ok, "output": getattr(impl, "output", None) or {}}
            return super()._code_acting(agent, inst)

    pipe = RealPipeline(model, runner=runner, wm=wm, implement_fn=lambda f: None,
                        validate_fn=validate_fn, store=store, log=print, on_gate=gate_notify)
    return pipe, runner, ledger


def _save_iid(iid):
    open(IID_FILE, "w").write(iid)


def _load_iid():
    return open(IID_FILE).read().strip() if os.path.exists(IID_FILE) else None


def _print_packet(pipe, inst, runner=None, ledger=None):
    pkt = pipe.packet(inst)
    print("\n" + "=" * 72)
    print(f"INSTANCE {inst.id}   status={inst.status}   gate={pkt['gate']}")
    print("=" * 72)
    print("\nRECOMMENDATION:", json.dumps(pkt["recommendation"], indent=2))
    if pkt.get("triage"):
        print("\nTRIAGE:", json.dumps(pkt["triage"], indent=2)[:900])
    if pkt.get("proposal"):
        print("\nSPEC PROPOSAL:", json.dumps(pkt["proposal"], indent=2)[:1400])
    revs = {k: v for k, v in (pkt.get("reviews") or {}).items() if v}
    if revs:
        print("\nREVIEWS:")
        for k, v in revs.items():
            ap = v.get("approve")
            print(f"  - {k}: approve={ap}  {json.dumps(v)[:200]}")
    if pkt.get("prioritize"):
        print("\nPRIORITIZE:", json.dumps(pkt["prioritize"])[:300])
    if pkt.get("validation"):
        print("\nVALIDATION:", json.dumps(pkt["validation"]))
    if pkt.get("review_packet"):
        print("\nREVIEW PACKET:", json.dumps(pkt["review_packet"])[:600])
    path = " -> ".join(t.dst for t in inst.history)
    print("\nPATH:", path)
    if ledger is not None:
        print(f"\nMONTH-TO-DATE SPEND: ${ledger.month_to_date():.4f}")
    if runner is not None:
        print(f"THIS-RUN SPEND: ${runner.spent_usd:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "gate1", "gate2", "show", "diff"])
    ap.add_argument("decision", nargs="?", default="approve")
    args = ap.parse_args()

    pipe, runner, ledger = build_pipeline()

    if args.cmd == "submit":
        inst = pipe.submit(WORK_ITEM)
        _save_iid(inst.id)
        _print_packet(pipe, inst, runner, ledger)
        return

    iid = _load_iid()
    if not iid:
        sys.exit("no instance yet — run `submit` first")

    if args.cmd in ("gate1", "gate2"):
        inst = pipe.approve(iid, args.decision)
        _print_packet(pipe, inst, runner, ledger)
    elif args.cmd == "show":
        inst = pipe.store.load(iid)
        _print_packet(pipe, inst, None, ledger)
    elif args.cmd == "diff":
        inst = pipe.store.load(iid)
        feat = inst.context.get("feature") or {}
        if not feat:
            sys.exit("no feature branch yet (implement hasn't run)")
        from apps.evolve.workspace import git
        print(git(pipe.wm.repo, "diff", "release...{}".format(feat["branch"])))


if __name__ == "__main__":
    main()
