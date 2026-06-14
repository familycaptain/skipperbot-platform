"""Orchestrator — wires the process engine (control plane) to the agent runner
(data plane) and walks a work-item through the SDLC (EVOLVE.md §7).

`run_work_item` is the integration seam: agent nodes dispatch to the real Runner
(or any backend); system nodes are deterministic stubs (serialize/deploy/merge —
the real ones touch git/box-2 and are TODO); gates auto-resume in demo mode or
block for the human work-queue in production.

Run the live demo (needs ANTHROPIC_API_KEY in .env):
    /tmp/evolve-venv/bin/python -m apps.evolve.orchestrator
"""
from __future__ import annotations

import os

from apps.evolve.engine import model as M
from apps.evolve.engine.instance import Instance
from apps.evolve.engine.walker import Walker, _default_decider
from apps.evolve.agents.runner import Runner

# code-acting agents need box-2 + tool use (file edits, running tests) — stubbed for now
CODE_ACTING = {"implement", "test-author", "validate", "variance-detect"}

_HAPPY = {"gw_kind": "feature", "gw_vision": "fits", "gw_prio": "top-n",
          "gw_conf": "clear", "gw_tests": "green"}


def happy_decider(node, inst, outs):
    pref = _HAPPY.get(node.id)
    if pref:
        for e in outs:
            if e.when and pref in e.when.lower():
                return e
    return _default_decider(node, inst, outs)


def _match(outs, sub):
    if sub:
        for e in outs:
            if e.when and sub in e.when.lower():
                return e
    return None


def output_driven_decider(node, inst, outs):
    """Route exclusive gateways on the PRECEDING agent's structured output, so the
    swarm actually steers control flow (falls back to the happy path for gateways
    with no agent signal, e.g. the stubbed test gate)."""
    ao = inst.context.get("agent_outputs", {})

    def out_of(nid):
        return (ao.get(nid) or {}).get("output") or {}

    pref = None
    if node.id == "gw_kind":
        pref = out_of("triage").get("kind")                       # bug | feature
    elif node.id == "gw_vision":
        pref = "fits" if out_of("vision").get("verdict") == "fits" else "off-vision"
    elif node.id == "gw_prio":
        pref = "top-n" if out_of("prio").get("decision") == "surface" else "low-priority"
    elif node.id == "gw_conf":
        pref = "conflict" if out_of("interop").get("conflicts") else "clear"
    elif node.id == "gw_tests":
        pref = "green"                                            # validate stubbed -> assume green
    return _match(outs, pref) or happy_decider(node, inst, outs)


def make_agent_handler(runner: Runner, log=lambda *a: None):
    """agent node -> real Runner call (reasoning agents) or a stub (code-acting)."""
    def handler(node, inst):
        agent = node.agent or node.id
        if agent in CODE_ACTING or agent not in runner.registry:
            log(f"      · {agent}: stubbed (needs box-2 + tools)")
            return {"_stub": True, "agent": agent}
        payload = {"work_item": inst.context.get("work_item", {}),
                   "charter": inst.context.get("charter"),
                   "proposal": inst.context.get("proposal")}
        res = runner.run(agent, payload)
        if res.ok and agent == "spec-author":
            inst.context["proposal"] = res.output      # downstream reviewers see it
        status = "ok" if res.ok else f"FAIL: {res.error}"
        log(f"      · {agent} [{res.model.split('-')[1] if '-' in res.model else res.model}] "
            f"{status}  ${res.cost_usd:.5f}")
        if res.ok:
            log(f"          -> {res.output}")
        return {"ok": res.ok, "output": res.output, "error": res.error}
    return handler


def system_handler(node, inst):
    return f"[stub] {node.label}"


def run_work_item(model, runner: Runner, work_item: dict, *, charter=None,
                  decider=output_driven_decider, auto_approve=True, log=print) -> Instance:
    """Walk one work-item from s_issue through the pipeline. Exclusive gateways route
    on agent output (decider). In demo mode gates auto-approve; in production they
    block for the human work-queue (resume_gate)."""
    walker = Walker(model,
                    system_handler=system_handler,
                    agent_handler=make_agent_handler(runner, log),
                    exclusive_decider=decider)
    inst = walker.start(context={"work_item": work_item, "charter": charter}, at="s_issue")
    while inst.status == "blocked" and auto_approve:
        gate = next(n for n in inst.tokens if model.node(n).type == "gate")
        log(f"  >> {model.node(gate).label}: auto-approve (demo)")
        walker.resume_gate(inst, "approve", gate)
    return inst


# --------------------------------------------------------------------------- #
def _load_env():
    if os.path.exists(".env"):
        with open(".env") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


if __name__ == "__main__":
    from apps.evolve.agents.runner import AnthropicBackend, MODEL_TIERS
    from apps.evolve.agents.registry import ROSTER

    _load_env()
    model = M.load("specs/evolve/sdlc.yaml")
    # cheap demo: force every tier to Haiku, cap the budget
    haiku = MODEL_TIERS["fast"]
    runner = Runner(AnthropicBackend(), dict(ROSTER), budget_usd=1.0,
                    tiers={"fast": haiku, "smart": haiku, "deep": haiku})

    charter = ("Skipper is a self-hosted, agentic family assistant. It bundles apps "
               "for a household: among them the Auto app, which tracks the family's "
               "vehicles, their service history, and their issues/repairs. In scope: "
               "making those household apps more usable and complete.")
    issue = {"title": "After saving an auto issue you can't edit it",
             "body": "Once an auto (vehicle) issue is saved there's no way to change it. "
                     "There should be an Edit button on the issue detail."}
    print(f"\n=== Walking a work-item through Evolve (model {model.id} v{model.version}) ===")
    print(f"ISSUE: {issue['title']}\n")
    inst = run_work_item(model, runner, issue, charter=charter)
    print(f"\n=== RESULT: status={inst.status}  ended_at={inst.context.get('ended_at')} ===")
    print(f"steps: {len(inst.history)}  |  total spend: ${runner.spent_usd:.4f}")
    path = " -> ".join(t.dst for t in inst.history)
    print("path:", path)
