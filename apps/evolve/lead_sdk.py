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

import time

from apps.evolve.agents import base
from apps.evolve.lead import REVIEWERS

_RETRY_ATTEMPTS = 3          # a transient API/SDK blip must not drop a REQUIRED review
_RETRY_BACKOFF = (3, 8)      # seconds between attempts (2 retries)

# ONE frozen system prompt for the whole session — the per-agent role goes in the user turn
# (varying `system` per turn would invalidate the conversation cache). Kept short + stable.
_SHARED_SYSTEM = (
    "You are part of Skipper's Evolve spec team, collaborating in ONE shared conversation to "
    "turn a single work item into a sound, buildable specification. Each turn names the role "
    "you must play right now (Grounding, Design, Spec-author, Spec-auditor, a domain reviewer, "
    "or the Lead) and the exact structured result to emit. Build on the shared context above — "
    "the code already explored and the prior agents' reasoning — instead of starting over. "
    "Honor Skipper's engineering principles: preconfigure once, minimize external calls, config "
    "in Settings, build for the self-hoster, degrade gracefully, and guard the context window — "
    "wire a capability's tools/guidance/memory to load just-in-time and scoped to relevance "
    "(tool-router categories, guide-with-tool, relevant-memories-only), never bloating the "
    "always-on system prompt; lean means defer-and-scope, not omit. The LLM determines chat "
    "intent — NEVER string-match a user's message for hardcoded phrases to trigger behavior; "
    "expose a tool and let the model decide when to call it. "
    "Be concise: state each point ONCE, no narration or restatement. Your output is re-read by the "
    "whole team and rides in this shared conversation, so brevity is both correctness and cost — "
    "the shortest result that covers all the cases, never the longest."
)


def _emit(on_event, instance_id, agent, kind, message) -> None:
    try:
        on_event(instance_id, agent, kind, message)
    except Exception:
        pass   # observability must never break a run


def run_lead_phase_sdk(runner, sdk_backend, work_item: dict, *, context: dict | None = None,
                       model: str = "claude-opus-4-8", max_rounds: int = 3,
                       log=lambda *a: None, instance_id=None, on_event=None,
                       resume_session: str | None = None) -> dict:
    context = context or {}
    human_note = context.get("human_note")
    outputs: dict[str, dict] = {}
    reviews_incomplete: list[str] = []        # REQUIRED reviews that didn't complete (surfaced, NEVER skipped)
    # 1 issue == 1 conversation forever: resume the issue's existing session if it has one
    # (an operator Change re-enters the SAME thread), else this is its first-ever pass.
    sess = {"id": resume_session}

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

        # RETRY transient failures — a flaky API/SDK blip (overload, rate-limit, dropped stream)
        # must NOT cost us a required review. run_turn never raises (it returns ok=False), so we
        # retry on a not-ok result with backoff. Every review is required; we fix, we don't skip.
        res = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            res = sdk_backend.run_turn(spec, payload, context, model, _SHARED_SYSTEM,
                                       role_prompt=runner.composed_system(spec),
                                       resume=sess["id"], fork=critic)
            if res.ok:
                break
            if attempt < _RETRY_ATTEMPTS:
                wait = _RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)]
                log(f"    lead-sdk/{lane} attempt {attempt}/{_RETRY_ATTEMPTS} not ok "
                    f"({res.error or 'no output'}) — retrying in {wait}s")
                if on_event:
                    _emit(on_event, instance_id, lane, "info",
                          f"retry {attempt}/{_RETRY_ATTEMPTS}: {res.error or 'no output'}")
                time.sleep(wait)
        sdk_backend.on_tool = None
        if runner.ledger is not None:
            runner.ledger.record_result(res, instance_id=instance_id)
        out = res.output or {}
        if res.ok and out:
            res.schema_errors = base.validate_against_schema(spec.output_schema, out)
        if not critic and res.session_id:    # advance the shared conversation (critics branch off it)
            sess["id"] = res.session_id
        outputs[lane] = out

        # A REQUIRED review that STILL didn't complete after retries is NOT silently dropped.
        # We record it and surface it LOUDLY (error event + flag on the gate) so the operator can
        # never mistake a half-reviewed change for a fully-reviewed one (e.g. a missed security pass).
        if critic and not res.ok:
            reviews_incomplete.append(lane)
            log(f"    lead-sdk/{lane} REVIEW INCOMPLETE after {_RETRY_ATTEMPTS} attempts: {res.error}")
            if on_event:
                _emit(on_event, instance_id, lane, "error",
                      f"⚠ REVIEW INCOMPLETE ({res.error or 'no output'}) — required, will block clean approval")
            return out

        if on_event:
            # full summary on the agent_end line too (the collapsed lane CSS-truncates it to one line
            # for the peek; expanding shows it whole). Never clip agent output — scroll handles length.
            summ = (out.get("summary") or "")[:20000] if isinstance(out, dict) else ""
            _emit(on_event, instance_id, lane, "agent_end",
                  f"{'✓' if res.ok else '✗'} (${res.cost_usd:.4f}) {summ}".strip())
        log(f"    lead-sdk/{lane} ok={res.ok} ${res.cost_usd:.4f} "
            f"sess={(res.session_id or '')[:8]}{' (fork)' if critic else ''}")
        return out

    # 0. GROUNDING — the one cold scan, EVER, for this issue. Skipped when we're resuming the
    # issue's existing conversation (a Change): the code is already explored in that thread.
    if sess["id"] is None:
        call("grounding", {"work_item": work_item}, store_as="grounding")
    else:
        log(f"  lead-sdk: resuming issue conversation {sess['id'][:8]} — grounding already done")
        _emit(on_event, instance_id, "grounding", "info",
              f"resuming conversation {sess['id'][:8]} — code already explored, skipping re-grounding")

    # 1. DESIGN — resumes the conversation (grounding on the first pass; on a Change, the full
    # prior spec + the operator's answers, so it revises rather than re-deriving from scratch).
    design = call("design", {"work_item": work_item, "human_note": human_note}, store_as="design")
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
    # Wrapped: even the load-bearing Lead turn shouldn't lose a whole spec phase to a transient
    # error — we have design + specs + reviews, so we can still park at Gate 1 with a synthesized
    # recommendation for the operator rather than crash and discard ~$9 of completed work.
    try:
        final = call("lead", {"phase": "recommend", "work_item": work_item, "design": design,
                              "proposal": proposal, "audit": audit,
                              "spec_tree": [{"spec_id": s.get("spec_id"), "title": s.get("title")}
                                            for s in spec_tree_specs] if needs_tree else None,
                              "decisions_needed": design.get("decisions_needed"),
                              "reviews": {k: outputs.get(k) for k in (*REVIEWERS, "crit")},
                              "reviews_incomplete": reviews_incomplete,
                              "rounds": rounds, "converged": verdict == "accept", "escalated": escalated,
                              "human_note": human_note}, store_as="lead")
    except Exception as e:
        log(f"    lead-sdk/lead recommend FAILED, synthesizing from reviews: {type(e).__name__}: {e}")
        final = {"summary": f"Lead synthesis unavailable ({type(e).__name__}); recommendation "
                            f"defaulted from review convergence. Operator should weigh the specs + "
                            f"reviews directly."}
    rec = final.get("recommendation") or {
        "action": "change" if (escalated or verdict != "accept") else "approve",
        "why": final.get("summary", ""),
    }
    # Every review is REQUIRED. If any didn't complete (even after retries), a clean approval is not
    # honest — force the action off "approve" and tell the operator exactly which reviews are missing,
    # so a change can't ship with, e.g., the security pass silently absent.
    if reviews_incomplete:
        rec["reviews_incomplete"] = reviews_incomplete
        if rec.get("action") == "approve":
            rec["action"] = "change"
        rec["why"] = (f"⚠ Reviews did not complete: {', '.join(reviews_incomplete)} "
                      f"(required — retried {_RETRY_ATTEMPTS}×). Re-run the spec phase or address the "
                      f"failure before approving. " + (rec.get("why") or "")).strip()
        log(f"  lead-sdk: REVIEWS INCOMPLETE {reviews_incomplete} — clean approval blocked")
    log(f"  lead-sdk: {rounds} round(s), {len(spec_tree_specs)} spec(s), recommend={rec.get('action')}"
        + (" (escalated)" if escalated else "") + f", session={(sess['id'] or '-')[:8]}")
    return {"proposal": proposal, "spec_tree": spec_tree_specs, "recommendation": rec,
            "outputs": outputs, "rounds": rounds, "escalated": escalated,
            "reviews_incomplete": reviews_incomplete,
            "code_context": None, "session_id": sess["id"]}
