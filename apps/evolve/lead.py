"""The Lead-orchestrated spec phase (EVOLVE.md §8) — the agentic inner loop inside the
deterministic walker.

The deterministic backbone owns the gates and promotion; THIS owns the messy creative
phase. The Lead runs a small team: Design sets the approach (reading the real code first),
Spec-author drafts the C/F/S, Spec-auditor critiques it, the Lead arbitrates each round
(accept / revise / escalate, bounded), then reviewers weigh in and the Lead produces the
final proposal + the Gate-1 recommendation.

When Design sizes a request as `needs-tree`, the Lead **decomposes**: it authors one spec
per leaf in the design's `spec_tree` instead of cramming a multi-behavior feature into a
single spec. `run_lead_phase` returns the (root) proposal, the full `spec_tree` of authored
specs, the recommendation, and every sub-agent's output (keyed for the packet + UI panels).
It takes a Runner so it shares the cost ledger + kill-switch and is testable with a FakeBackend.
"""
from __future__ import annotations

REVIEWERS = ("security", "architecture", "interop", "ux")


def run_lead_phase(runner, work_item: dict, *, context: dict | None = None,
                   max_rounds: int = 3, log=lambda *a: None, instance_id=None) -> dict:
    context = context or {}
    human_note = context.get("human_note")
    outputs: dict[str, dict] = {}

    def call(name, payload, store_as=None):
        res = runner.run(name, payload, instance_id=instance_id)
        out = res.output or {}
        outputs[store_as or name] = out
        log(f"    lead/{store_as or name} ok={res.ok} ${getattr(res, 'cost_usd', 0):.4f}")
        return out

    # 0. GROUNDING: scan the code ONCE; the whole team reuses this digest (no re-scan tax).
    code_context = call("grounding", {"work_item": work_item, "context": context},
                        store_as="grounding")

    # 1. Design sets the approach + decides the technical choices (grounded in the digest).
    design = call("design", {"work_item": work_item, "context": context,
                             "code_context": code_context}, store_as="design")
    tree = design.get("spec_tree") or []
    needs_tree = design.get("sizing") == "needs-tree" and len(tree) >= 2

    proposal = audit = None
    verdict, rounds, escalated = "accept", 0, False
    spec_tree_specs: list[dict] = []

    if needs_tree:
        # 2a. DECOMPOSE: author one spec per leaf, then audit the whole set once.
        log(f"  lead: decomposing into {len(tree)} specs")
        for leaf in tree:
            s = call("spec-author", {"work_item": work_item, "design": design, "leaf": leaf,
                                     "code_context": code_context, "human_note": human_note},
                     store_as=f"spec:{leaf.get('spec_id', '?')}")
            spec_tree_specs.append(s)
        proposal = spec_tree_specs[0] if spec_tree_specs else {}
        outputs["spec"] = proposal                              # root spec drives the panel/serialize
        audit = call("spec-audit", {"work_item": work_item, "proposal": spec_tree_specs,
                                    "design": design, "code_context": code_context}, store_as="crit")
        rounds = 1
    else:
        # 2b. SINGLE SPEC: author <-> auditor, arbitrated by the Lead each round (bounded).
        for rnd in range(1, max_rounds + 1):
            rounds = rnd
            proposal = call("spec-author", {"work_item": work_item, "design": design,
                                            "code_context": code_context,
                                            "prior_audit": audit, "human_note": human_note}, store_as="spec")
            audit = call("spec-audit", {"work_item": work_item, "proposal": proposal,
                                        "code_context": code_context}, store_as="crit")
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

    # 3. Reviewers weigh in once, on the (root) proposal.
    for r in REVIEWERS:
        call(r, {"work_item": work_item, "proposal": proposal})

    # 4. The Lead produces the final proposal + the Gate-1 recommendation.
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
    log(f"  lead: {rounds} round(s), {len(spec_tree_specs)} spec(s), recommend={rec.get('action')}"
        + (" (escalated)" if escalated else ""))
    return {"proposal": proposal, "spec_tree": spec_tree_specs, "recommendation": rec,
            "outputs": outputs, "rounds": rounds, "escalated": escalated,
            "code_context": code_context}


def run_result_review(runner, work_item: dict, *, spec: dict, diff: str, validation: dict,
                      instance_id=None, log=lambda *a: None) -> dict:
    """The Gate-2 review (EVOLVE.md §8). The intent was already approved at Gate 1; here the
    same domain reviewers look at the ACTUAL diff and report — in past tense, from each one's
    perspective — what was CHANGED (architecture: what structure moved; UX: which screens and
    how; interop: how modules now interact; security: what surface changed). The Lead then
    gives the verdict: the fix was made, briefly what was done, and whether it worked. These
    become the Gate-2 packet panels + recommendation (not the Gate-1 'we should…' proposals)."""
    outputs: dict[str, dict] = {}
    passed = validation.get("passed") is True

    def call(name, payload, store_as=None):
        res = runner.run(name, payload, instance_id=instance_id)
        outputs[store_as or name] = res.output or {}
        log(f"    result/{store_as or name} ok={res.ok} ${getattr(res, 'cost_usd', 0):.4f}")
        return outputs[store_as or name]

    base = {"phase": "result", "gate": "gate2", "work_item": work_item, "spec": spec,
            "diff": diff, "validation": validation}
    for r in REVIEWERS:
        call(r, base, store_as=r)     # describe what changed in this domain (past tense)
    final = call("lead", {**base, "phase": "result-verdict",
                          "reviews": {k: outputs.get(k) for k in REVIEWERS}}, store_as="lead")
    rec = final.get("recommendation") or {
        "action": "approve" if passed else "change",
        "why": final.get("summary", ""),
    }
    log(f"  result review: tests {'green' if passed else 'RED'}, recommend={rec.get('action')}")
    return {"outputs": outputs, "recommendation": rec}
