"""The Lead-orchestrated spec phase (EVOLVE.md §8) — the agentic inner loop inside the
deterministic walker.

The deterministic backbone owns the gates and promotion; THIS owns the messy creative
phase. The Lead runs a small team: Design sets the approach, Spec-author drafts the
C/F/S, Spec-auditor critiques it, the Lead arbitrates each round (accept / revise /
escalate, bounded so a stuck negotiation surfaces to the human instead of spinning),
then the reviewers (security/architecture/interop/ux) weigh in and the Lead produces
the final proposal + the Gate-1 recommendation.

`run_lead_phase` returns the proposal, the recommendation, and every sub-agent's output
(keyed for the review packet + the UI panels). It takes a Runner so it shares the cost
ledger + kill-switch and is testable with a FakeBackend.
"""
from __future__ import annotations

REVIEWERS = ("security", "architecture", "interop", "ux")


def run_lead_phase(runner, work_item: dict, *, context: dict | None = None,
                   max_rounds: int = 3, log=lambda *a: None) -> dict:
    context = context or {}
    human_note = context.get("human_note")           # set when the human chose "change" at a gate
    outputs: dict[str, dict] = {}                     # key -> agent output (-> agent_outputs / UI panels)

    def call(name, payload, store_as=None):
        res = runner.run(name, payload)
        out = res.output or {}
        outputs[store_as or name] = out
        log(f"    lead/{store_as or name} ok={res.ok} ${getattr(res, 'cost_usd', 0):.4f}")
        return out

    # 1. Design sets the approach (grounded in vision + the engineering principles).
    design = call("design", {"work_item": work_item, "context": context}, store_as="design")

    # 2. Author <-> auditor, arbitrated by the Lead each round (bounded).
    proposal = audit = None
    verdict, rounds, escalated = "revise", 0, False
    for rnd in range(1, max_rounds + 1):
        rounds = rnd
        proposal = call("spec-author", {"work_item": work_item, "design": design,
                                        "prior_audit": audit, "human_note": human_note},
                        store_as="spec")
        audit = call("spec-audit", {"work_item": work_item, "proposal": proposal},
                     store_as="crit")
        arb = call("lead", {"phase": "arbitrate-round", "work_item": work_item, "design": design,
                            "proposal": proposal, "audit": audit, "round": rnd, "max_rounds": max_rounds},
                   store_as=f"lead-round-{rnd}")
        verdict = arb.get("verdict") or "accept"
        if verdict == "accept":
            break
        if verdict == "escalate":
            escalated = True
            break
        # verdict == "revise": loop — the author gets the auditor's findings next round.

    # 3. Reviewers weigh in once, on the converged proposal.
    for r in REVIEWERS:
        call(r, {"work_item": work_item, "proposal": proposal})

    # 4. The Lead produces the final proposal + the Gate-1 recommendation.
    final = call("lead", {"phase": "recommend", "work_item": work_item, "design": design,
                          "proposal": proposal, "audit": audit,
                          "reviews": {k: outputs.get(k) for k in (*REVIEWERS, "crit")},
                          "rounds": rounds, "converged": verdict == "accept", "escalated": escalated,
                          "human_note": human_note}, store_as="lead")
    rec = final.get("recommendation") or {
        "action": "change" if (escalated or verdict != "accept") else "approve",
        "why": final.get("summary", ""),
    }
    log(f"  lead: {rounds} round(s), recommend={rec.get('action')}"
        + (" (escalated)" if escalated else ""))
    return {"proposal": proposal, "recommendation": rec, "outputs": outputs,
            "rounds": rounds, "escalated": escalated}
