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

STATE_DB = os.path.expanduser("~/.evolve/instances.sqlite")  # ONE store for all intake (unified)
SEEN = os.path.expanduser("~/.evolve/github_ingested.json")
DEEP = os.getenv("EVOLVE_MODEL_DEEP", "claude-opus-4-8")
CAP = float(os.getenv("EVOLVE_MONTHLY_CAP", "500"))
BOX2_HOST = os.getenv("EVOLVE_BOX2_HOST", "evolve-test.local")
BOX2_REPO = os.getenv("EVOLVE_BOX2_REPO", "/home/skipper/repos/skipperbot-platform")


def _safe_resolve(iid, status):
    """Mark a gate's terminal outcome — best-effort (the platform may not have the
    resolve route yet if it hasn't been updated; the resume itself still succeeded)."""
    try:
        bridge.resolve(iid, status)
    except Exception as e:
        print(f"    (resolve '{status}' not recorded — platform may need `skipper update`: {type(e).__name__})")


def _pushover(title, message, priority=1):
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("_pd", os.path.join(ROOT, "tools", "pushover_tool.py"))
        mod = ilu.module_from_spec(spec); spec.loader.exec_module(mod)
        print(" ", mod.send_pushover_direct(message, title=title, priority=priority))
    except Exception as e:
        print("  pushover failed:", e)


def _make_on_gate(pipe):
    """on_gate hook: enrich the packet with the feature diff (if implement has run),
    push it to the operator work queue (the Pi), and Pushover. Closes over `pipe` so it
    can load the instance + compute the diff for the gate the engine just parked at."""
    from apps.evolve.workspace import git

    def hook(packet):
        inst = pipe.store.load(packet.get("instance"))
        feat = (inst.context.get("feature") if inst else None) or {}
        if feat:
            packet["feature"] = feat
            try:
                packet["diff"] = git(pipe.wm.repo, "diff", "release...{}".format(feat["branch"]))
            except Exception:
                packet["diff"] = ""
        try:
            bridge.push_gate(packet)
            print(f"  -> pushed {packet.get('gate')} to the operator work queue")
        except Exception as e:
            print("  -> push_gate FAILED:", e)
        rec = packet.get("recommendation") or {}
        wi = packet.get("work_item") or {}
        label = {"gate1": "Gate 1 · approve intent", "gate2": "Gate 2 · approve result"}.get(
            packet.get("gate"), packet.get("gate"))
        _pushover(f"Evolve · {label}", f"{wi.get('title', '(work item)')}\n"
                  f"Recommend: {rec.get('action', '?')} — {rec.get('why', '')}")

    return hook


def build_pipeline():
    os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
    model = M.load("specs/evolve/sdlc.yaml")
    ledger = CostLedger()
    from apps.evolve.agents.tooluse import ToolUseBackend
    from apps.evolve.emitter import EventEmitter
    read_tools = ToolUseBackend(repo_root=ROOT, allow_writes=False, max_turns=14)  # spec phase reads REAL code
    runner = Runner(AnthropicBackend(), dict(ROSTER), tool_backend=read_tools,
                    ledger=ledger, monthly_limit_usd=CAP, budget_usd=20.0)
    wm = WorkspaceManager(ROOT, worktrees_dir=os.path.expanduser("~/evolve-wt"), release="release")
    validate_fn = remote_validate(RemoteBox2(BOX2_HOST, BOX2_REPO), release="release",
                                  test_path="tests/evolve", log=print)
    store = SqliteInstanceStore(STATE_DB)

    # live mission-control: batch+flush activity to the Pi off the build thread
    emitter = EventEmitter(
        lambda iid, fields, events: bridge.report_run(iid, events=events, **fields),
        log=print).start()

    # Stage 2/3 (opt-in via EVOLVE_USE_SDK=1): run the spec phase as ONE shared claude-agent-sdk
    # session (constructive chain resumes + caches, critics fork) instead of the hand-rolled backend.
    sdk_backend = None
    if os.getenv("EVOLVE_USE_SDK", "").strip() in ("1", "true", "yes"):
        from apps.evolve.agents.sdk_backend import ClaudeSDKBackend
        sdk_backend = ClaudeSDKBackend(repo_root=ROOT, allow_writes=False, max_turns=20,
                                       max_budget_usd=min(20.0, CAP))
        print("  spec phase: claude-agent-sdk shared session (EVOLVE_USE_SDK=1)")

    class RealPipeline(Pipeline):
        def _code_acting(self, agent, inst):
            if agent == "implement":
                feat = self._feature(inst)
                spec_rec = inst.context.get("spec_record") or {"id": feat.item_id}
                wi = inst.context.get("work_item", {})
                self._run(inst, phase="build", status="building",
                          current_node="impl", current_agent="implement")
                self._ev(inst, "implement", "node", "implementing: writing the code + bound test")
                if self.sdk_backend is not None:
                    from apps.evolve.build_loop import implement_with_sdk
                    impl = implement_with_sdk(wi, spec_rec, model=DEEP, ledger=ledger,
                                              max_budget_usd=min(20.0, CAP),
                                              on_event=self.on_event, instance_id=inst.id,
                                              resume_session=inst.context.get("sdk_session_id"))(feat)
                    if getattr(impl, "session_id", None):    # 1 issue = 1 conversation forever
                        inst.context["sdk_session_id"] = impl.session_id
                else:
                    impl = implement_with_agent(wi, spec_rec, model=DEEP, skills_dir=".claude/skills",
                                                ledger=ledger, monthly_limit_usd=CAP,
                                                on_event=self.on_event, instance_id=inst.id,
                                                code_context=inst.context.get("code_context"))(feat)
                # shared gating: ok AND a real code change, else validate is short-circuited
                return self._finish_implement(inst, feat, impl)
            return super()._code_acting(agent, inst)

    pipe = RealPipeline(model, runner=runner, wm=wm, implement_fn=lambda f: None,
                        validate_fn=validate_fn, store=store, log=print, on_gate=None,
                        on_event=emitter.event, on_run=emitter.run, sdk_backend=sdk_backend)
    pipe.on_gate = _make_on_gate(pipe)
    pipe.emitter = emitter
    return pipe, runner, ledger


def _seen():
    return set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()


def _mark(num):
    s = _seen(); s.add(num); json.dump(sorted(s), open(SEEN, "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "ingest", "poll"])
    ap.add_argument("--all", action="store_true", help="ingest: re-submit even already-seen issues")
    ap.add_argument("--loop", type=float, default=0.0,
                    help="poll: keep polling every N seconds in ONE process (snappy; pipeline loaded once)")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="poll --loop: exit after N seconds (lets cron relaunch + reset; 0 = forever)")
    args = ap.parse_args()

    if args.cmd == "list":
        for i in gh.list_open_issues():
            print(f"#{i['number']}: {i['title']}  (labels: {[l['name'] for l in i.get('labels', [])]})")
        return

    pipe, runner, ledger = build_pipeline()
    try:
        if args.cmd == "poll" and args.loop > 0:
            import time
            start = time.monotonic()
            while True:
                _run_cmd(args, pipe, runner, ledger)              # quiet when nothing is decided
                if args.duration and (time.monotonic() - start) >= args.duration:
                    break
                time.sleep(args.loop)
        else:
            _run_cmd(args, pipe, runner, ledger)
    finally:
        pipe.emitter.stop()      # final flush of the live activity stream


def _run_cmd(args, pipe, runner, ledger):
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
        from apps.evolve.engine.instance import DONE, REJECTED
        decided = bridge.list_decided()
        if not decided:
            return                       # quiet: nothing to resume (the --loop polls every few seconds)
        print(f"{len(decided)} decided gate(s) on the platform")
        for g in decided:
            iid, decision = g["instance_id"], g["decision"]
            inst = pipe.store.load(iid)
            if inst is None:
                _safe_resolve(iid, "orphan")
                print(f"  {iid}: not in this brain's store -> marked orphan")
                continue
            note = g.get("note") or ""
            print(f"  {iid}: operator said '{decision}'{' (+note)' if note else ''} — resuming the engine...")
            try:
                # Resumes the walk. If it parks at a NEXT gate, the pipeline's on_gate
                # re-pushes that gate to the queue (flipping the row back to 'waiting').
                inst = pipe.approve(iid, decision, note=note)
            except Exception as e:
                # A failed resume must be processed ONCE, never looped: leaving the gate 'decided'
                # makes the poller re-run the same (expensive) build every cycle (the runaway).
                # Flip it to 'error' so it leaves the decided set; the operator re-decides once fixed.
                print(f"    resume FAILED: {type(e).__name__}: {e}")
                _safe_resolve(iid, "error")
                continue
            if inst.status == DONE:
                _safe_resolve(iid, "merged")
                print(f"    -> DONE — merged to release @ {(inst.context.get('release_sha') or '')[:8]}")
            elif inst.status == REJECTED:
                _safe_resolve(iid, "rejected")
                print(f"    -> rejected")
            else:
                print(f"    -> advanced to {pipe.gate_waiting(inst)} (re-pushed to the queue)")
        print(f"this-run reasoning spend: ${runner.spent_usd:.4f}")


if __name__ == "__main__":
    main()
