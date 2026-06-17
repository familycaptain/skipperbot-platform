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
        t = out_of("triage")
        wi = inst.context.get("work_item", {})
        # Operator-authored items are NEVER rejected — the operator is the authority. They go
        # 'trusted' (skip vision-fit) even if triage flagged duplicate/invalid; that disposition
        # is carried forward as advice for the operator to weigh at Gate 1, not a hard reject.
        # Only PUBLIC (non-operator) submissions get filtered as junk here.
        if wi.get("from_operator"):
            pref = "trusted"
        elif t.get("disposition") in ("duplicate", "malicious", "invalid"):
            pref = "reject"
        else:
            pref = t.get("kind")                                  # bug -> prio, feature -> vision-fit
    elif node.id == "gw_vision":
        pref = "fits" if out_of("vision").get("verdict") == "fits" else "off-vision"
    elif node.id == "gw_prio":
        pref = "top-n" if out_of("prio").get("decision") == "surface" else "low-priority"
    elif node.id == "gw_conf":
        pref = "conflict" if out_of("interop").get("conflicts") else "clear"
    elif node.id == "gw_tests":
        # route on the validate agent's result. GREEN only on an explicit pass — a
        # missing/False signal must NEVER false-green; it escalates to the human gate.
        pref = "green" if out_of("validate").get("passed") is True else "stuck"
    return _match(outs, pref) or happy_decider(node, inst, outs)


def make_agent_handler(runner: Runner, log=lambda *a: None):
    """agent node -> real Runner call (reasoning agents) or a stub (code-acting)."""
    def handler(node, inst):
        agent = node.agent or node.id
        if agent in CODE_ACTING or agent not in runner.registry:
            log(f"      · {agent}: stubbed (needs box-2 + tools)")
            return {"_stub": True, "agent": agent}
        # charter is NOT in the payload — each agent is grounded with only the charter
        # sections it needs, via the Runner's composed system prompt (agents/charter.py).
        payload = {"work_item": inst.context.get("work_item", {}),
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


def run_work_item(model, runner: Runner, work_item: dict, *,
                  decider=output_driven_decider, auto_approve=True, log=print) -> Instance:
    """Walk one work-item from s_issue through the pipeline. Exclusive gateways route
    on agent output (decider). Agents are charter-grounded via the Runner. In demo
    mode gates auto-approve; in production they block for the human work-queue."""
    walker = Walker(model,
                    system_handler=system_handler,
                    agent_handler=make_agent_handler(runner, log),
                    exclusive_decider=decider)
    inst = walker.start(context={"work_item": work_item}, at="s_issue")
    while inst.status == "blocked" and auto_approve:
        gate = next(n for n in inst.tokens if model.node(n).type == "gate")
        log(f"  >> {model.node(gate).label}: auto-approve (demo)")
        walker.resume_gate(inst, "approve", gate)
    return inst


# --------------------------------------------------------------------------- #
def load_charter(path: str = "specs/CHARTER.md") -> str | None:
    """The vision authority (EVOLVE.md §11) — fed to vision-fit + design agents."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return None


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

    issue = {"title": "After saving an auto issue you can't edit it",
             "body": "Once an auto (vehicle) issue is saved there's no way to change it. "
                     "There should be an Edit button on the issue detail."}
    print(f"\n=== Walking a work-item through Evolve (model {model.id} v{model.version}) ===")
    print(f"ISSUE: {issue['title']}  (agents charter-grounded from {runner.charter_path})\n")
    inst = run_work_item(model, runner, issue)
    print(f"\n=== RESULT: status={inst.status}  ended_at={inst.context.get('ended_at')} ===")
    print(f"steps: {len(inst.history)}  |  total spend: ${runner.spent_usd:.4f}")
    path = " -> ".join(t.dst for t in inst.history)
    print("path:", path)
