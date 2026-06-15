"""The Lead spec phase on the claude-agent-sdk — ONE shared conversation per work item.

This is the Stage-2 re-platform of `lead.run_lead_phase`. Instead of a fresh, isolated API
call per agent (and a lossy grounding *digest* passed between them), the whole spec team works
in **one growing, prompt-cached conversation**:

    grounding → design → spec-author ⇄ spec-auditor → reviewers → Lead recommendation

The CONSTRUCTIVE chain (grounding/design/spec-author/lead) **resumes** the session — each agent
inherits the actual code exploration and prior reasoning at ~0.1x cache price, no re-scan, no
digest. The ADVERSARIAL critics (spec-audit, the reviewers) **fork** the session — full context
on an independent branch, so their skepticism isn't anchored and doesn't pollute the main thread
(their findings come back to the Lead via the payload, as before).

Returns the same shape as `run_lead_phase` so the pipeline downstream is unchanged. Cost is the
SDK's real `total_cost_usd` recorded to the ledger. The `runner` is used only for the registry,
the charter-grounded system prompts, and the ledger — never to call the API (execution is the
SDK backend).
"""
from __future__ import annotations

from apps.evolve.agents import base
from apps.evolve.lead import REVIEWERS

# ONE frozen system prompt for the whole session — the per-agent role goes in the user turn
# (varying `system` per turn would invalidate the conversation cache). Kept short + stable.
_SHARED_SYSTEM = (
    "You are part of Skipper's Evolve spec team, collaborating in ONE shared conversation to "
    "turn a single work item into a sound, buildable specification. Each turn names the role "
    "you must play right now (Grounding, Design, Spec-author, Spec-auditor, a domain reviewer, "
    "or the Lead) and the exact structured result to emit. Build on the shared context above — "
    "the code already explored and the prior agents' reasoning — instead of starting over. "
    "Honor Skipper's engineering principles: preconfigure once, minimize external calls, config "
    "in Settings, build for the self-hoster, degrade gracefully."
)


def _emit(on_event, instance_id, agent, kind, message) -> None:
    try:
        on_event(instance_id, agent, kind, message)
    except Exception:
        pass   # observability must never break a run


def run_lead_phase_sdk(runner, sdk_backend, work_item: dict, *, context: dict | None = None,
                       model: str = "claude-opus-4-8", max_rounds: int = 3,
                       log=lambda *a: None, instance_id=None, on_event=None) -> dict:
    context = context or {}
    human_note = context.get("human_note")
    outputs: dict[str, dict] = {}
    sess = {"id": None}                       # the shared session, threaded by the constructive chain

    def call(name, payload, *, store_as=None, critic=False):
        spec = runner.registry[name]
        lane = store_as or name               # the per-agent lane key in the live activity stream
        # per-agent live streaming: tag THIS turn's tool calls with the running agent's lane.
        # (The conversation is shared; the engine segments the log because it drives turns serially.)
        if on_event:
            _emit(on_event, instance_id, lane, "agent_start", f"{name}{' · fork' if critic else ''}")
            sdk_backend.on_tool = lambda kind, msg, _l=lane: _emit(on_event, instance_id, _l, kind, msg)
        else:
            sdk_backend.on_tool = None
        # frozen system (cache-safe) + the agent's full charter-grounded prompt as the user-turn role
        res = sdk_backend.run_turn(spec, payload, context, model, _SHARED_SYSTEM,
                                   role_prompt=runner.composed_system(spec),
                                   resume=sess["id"], fork=critic)
        sdk_backend.on_tool = None
        if runner.ledger is not None:
            runner.ledger.record_result(res, instance_id=instance_id)
        out = res.output or {}
        if res.ok and out:
            res.schema_errors = base.validate_against_schema(spec.output_schema, out)
        if not critic and res.session_id:    # advance the shared conversation (critics branch off it)
            sess["id"] = res.session_id
        outputs[lane] = out
        if on_event:
            summ = (out.get("summary") or "")[:160] if isinstance(out, dict) else ""
            _emit(on_event, instance_id, lane, "agent_end",
                  f"{'✓' if res.ok else '✗'} (${res.cost_usd:.4f}) {summ}".strip())
        log(f"    lead-sdk/{lane} ok={res.ok} ${res.cost_usd:.4f} "
            f"sess={(res.session_id or '')[:8]}{' (fork)' if critic else ''}")
        return out

    # 0. GROUNDING — the one cold scan; everyone downstream resumes THIS conversation.
    call("grounding", {"work_item": work_item}, store_as="grounding")

    # 1. DESIGN — resumes grounding (sees the real exploration, not a digest).
    design = call("design", {"work_item": work_item}, store_as="design")
    tree = design.get("spec_tree") or []
    needs_tree = design.get("sizing") == "needs-tree" and len(tree) >= 2

    proposal = audit = None
    verdict, rounds, escalated = "accept", 0, False
    spec_tree_specs: list[dict] = []

    if needs_tree:
        log(f"  lead-sdk: decomposing into {len(tree)} specs")
        for leaf in tree:
            s = call("spec-author", {"work_item": work_item, "design": design, "leaf": leaf,
                                     "human_note": human_note}, store_as=f"spec:{leaf.get('spec_id', '?')}")
            spec_tree_specs.append(s)
        proposal = spec_tree_specs[0] if spec_tree_specs else {}
        outputs["spec"] = proposal
        audit = call("spec-audit", {"work_item": work_item, "proposal": spec_tree_specs, "design": design},
                     store_as="crit", critic=True)
        rounds = 1
    else:
        for rnd in range(1, max_rounds + 1):
            rounds = rnd
            proposal = call("spec-author", {"work_item": work_item, "design": design,
                                            "prior_audit": audit, "human_note": human_note}, store_as="spec")
            audit = call("spec-audit", {"work_item": work_item, "proposal": proposal},
                         store_as="crit", critic=True)
            arb = call("lead", {"phase": "arbitrate-round", "work_item": work_item, "design": design,
                                "proposal": proposal, "audit": audit, "round": rnd, "max_rounds": max_rounds},
                       store_as=f"lead-round-{rnd}")
            verdict = arb.get("verdict") or "accept"
            if verdict == "accept":
                break
            if verdict == "escalate":
                escalated = True
                break
        spec_tree_specs = [proposal]

    # 2. REVIEWERS — fork (independent eyes, full context); findings return via payload to the Lead.
    for r in REVIEWERS:
        call(r, {"work_item": work_item, "proposal": proposal}, critic=True)

    # 3. LEAD recommendation — resumes the shared thread; reviews handed in explicitly.
    final = call("lead", {"phase": "recommend", "work_item": work_item, "design": design,
                          "proposal": proposal, "audit": audit,
                          "spec_tree": [{"spec_id": s.get("spec_id"), "title": s.get("title")}
                                        for s in spec_tree_specs] if needs_tree else None,
                          "decisions_needed": design.get("decisions_needed"),
                          "reviews": {k: outputs.get(k) for k in (*REVIEWERS, "crit")},
                          "rounds": rounds, "converged": verdict == "accept", "escalated": escalated,
                          "human_note": human_note}, store_as="lead")
    rec = final.get("recommendation") or {
        "action": "change" if (escalated or verdict != "accept") else "approve",
        "why": final.get("summary", ""),
    }
    log(f"  lead-sdk: {rounds} round(s), {len(spec_tree_specs)} spec(s), recommend={rec.get('action')}"
        + (" (escalated)" if escalated else "") + f", session={(sess['id'] or '-')[:8]}")
    return {"proposal": proposal, "spec_tree": spec_tree_specs, "recommendation": rec,
            "outputs": outputs, "rounds": rounds, "escalated": escalated,
            "code_context": None, "session_id": sess["id"]}
