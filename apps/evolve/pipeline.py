"""The full gated pipeline (EVOLVE.md §8) — the capstone integration.

Walks a work-item through the WHOLE SDLC graph: intake → triage → vision → spec-author
→ reviews (security/arch/interop/spec-audit/ux) → prioritize → GATE 1 → serialize →
implement → tests → deploy → validate (box 2) → GATE 2 → merge → release.

It wires together everything built so far:
  - reasoning agents      → the Runner (Opus, shared cost ledger + kill-switch)
  - code-acting agents    → implement_fn / validate_fn (workspace worktree + box 2)
  - system nodes          → the WorkspaceManager (serialize / merge / resync)
  - exclusive gateways    → output_driven_decider (agents steer control flow)
  - GATE 1 / GATE 2       → BLOCK + persist the instance + build a review packet;
                            resume on the human's decision (approve / reject / change)

Gates are real: submit() walks to the first gate and pauses (durable); approve()
resumes. The reasoning Runner carries the cost ledger, so a full run's per-item cost
lands in the ledger automatically.
"""
from __future__ import annotations

from apps.evolve.engine.instance import (Instance, InMemoryInstanceStore,
                                         BLOCKED, DONE, REJECTED, PARKED)
from apps.evolve.engine.walker import Walker
from apps.evolve.orchestrator import output_driven_decider
from apps.evolve.workspace import Feature

CODE_ACTING = {"implement", "test-author", "validate"}


def spec_record_from(spec_out: dict, work_item: dict) -> dict:
    """Build a C/F/S record from the spec-author agent's output."""
    sid = spec_out.get("spec_id") or "evolve.intake.unspecified"
    return {"kind": "specification", "id": sid,
            "title": spec_out.get("title") or (work_item.get("title", "") or "")[:60],
            "state": "proposed", "behavior": spec_out.get("behavior", ""),
            "implements": spec_out.get("implements", []),
            "tests": spec_out.get("tests", []), "links": {}, "notes": ""}


class Pipeline:
    def __init__(self, model, *, runner, wm, implement_fn, validate_fn,
                 store=None, cfs_store=None, log=lambda *a: None, on_gate=None):
        self.model = model
        self.runner = runner               # reasoning agents (shares the cost ledger)
        self.wm = wm                        # WorkspaceManager (box 1)
        self.implement_fn = implement_fn    # (feature) -> result with .ok (writes the worktree)
        self.validate_fn = validate_fn      # (feature) -> bool (deploy to box 2 + run bound tests)
        self.cfs_store = cfs_store          # apps.evolve.store.Store: triage checks specs against the report
        self.store = store or InMemoryInstanceStore()
        self.log = log
        self.on_gate = on_gate              # callback(packet) fired when an instance BLOCKS at a human gate
        self.walker = Walker(model, system_handler=self._system, agent_handler=self._agent,
                             exclusive_decider=output_driven_decider)

    def _maybe_notify_gate(self, inst: Instance) -> None:
        """When the walk parks at a human gate, fire the on_gate hook (e.g. Pushover).
        Best-effort: a notification failure never breaks the pipeline."""
        if self.on_gate is None or inst.status != BLOCKED or self.gate_waiting(inst) is None:
            return
        try:
            self.on_gate(self.packet(inst))
        except Exception as e:
            self.log(f"  on_gate hook failed: {type(e).__name__}: {e}")

    # public API ------------------------------------------------------------
    def submit(self, work_item: dict, at: str = "s_issue") -> Instance:
        inst = self.walker.start(context={"work_item": work_item}, at=at)
        self.store.save(inst)
        self._maybe_notify_gate(inst)
        return inst

    def approve(self, instance_id: str, decision: str) -> Instance:
        inst = self.store.load(instance_id)
        if inst is None:
            raise ValueError(f"no such instance {instance_id}")
        self.walker.resume_gate(inst, decision)
        self.store.save(inst)
        self._maybe_notify_gate(inst)
        return inst

    def gate_waiting(self, inst: Instance) -> str | None:
        gates = [n for n in inst.tokens if self.model.node(n).type == "gate"]
        return gates[0] if gates else None

    def packet(self, inst: Instance) -> dict:
        """The pre-digested review packet the human reads at a gate (§8/§10). ALWAYS
        leads with a `recommendation` — nothing reaches the human as a blank choice."""
        ao = {k: (v or {}).get("output") for k, v in inst.context.get("agent_outputs", {}).items()}
        gate = self.gate_waiting(inst)
        return {
            "instance": inst.id, "status": inst.status, "gate": gate,
            "recommendation": self._recommendation(inst, gate, ao),
            "work_item": inst.context.get("work_item"),
            "proposal": inst.context.get("proposal"),          # the spec-author C/F/S
            "triage": ao.get("triage"),                        # incl. spec_status (violates/no-spec/conflicts)
            "reviews": {k: ao.get(k) for k in ("security", "architecture", "interop", "crit", "ux")},
            "prioritize": ao.get("prio"),
            "validation": inst.context.get("validation"),
            "review_packet": ao.get("packet"),
            "release_sha": inst.context.get("release_sha"),
        }

    def _recommendation(self, inst, gate, ao) -> dict:
        """Synthesize a recommended action so the human never faces a bare decision.
        Even when uncertain, return the best call + why (+ what's unresolved)."""
        if gate == "gate1":
            concerns = []
            for k in ("security", "architecture", "ux"):
                r = ao.get(k) or {}
                if r.get("approve") is False:
                    concerns.append({k: r.get("concerns")})
            crit = ao.get("crit") or {}
            if crit.get("sound") is False:
                concerns.append({"spec-audit": crit.get("findings")})
            interop = ao.get("interop") or {}
            if interop.get("conflicts"):
                concerns.append({"interop": interop["conflicts"]})
            triage = ao.get("triage") or {}
            if triage.get("spec_status") == "conflicts-spec":
                return {"action": "decide-spec-change", "why":
                        f"report conflicts with live spec {triage.get('conflicting_spec','?')}; "
                        "amend the spec or reject the report as intended", "concerns": concerns}
            if concerns:
                return {"action": "change", "why": f"{len(concerns)} review concern(s) to resolve first",
                        "concerns": concerns[:3]}
            prio = ao.get("prio") or {}
            return {"action": "approve", "why":
                    f"reviews clean; prioritized {prio.get('decision','')} (score {prio.get('score','?')})"}
        if gate == "gate2":
            val = inst.context.get("validation") or {}
            pkt = ao.get("packet") or {}
            if val.get("passed") is False:
                return {"action": "change", "why": "bound tests did not pass on box 2 — send back to implement"}
            return {"action": "approve", "why": pkt.get("summary", "built + validated on box 2"),
                    "risk": pkt.get("risk", "low")}
        return {"action": "review", "why": "no gate is waiting"}

    # handlers --------------------------------------------------------------
    def _agent(self, node, inst) -> dict:
        agent = node.agent or node.id
        if agent in CODE_ACTING:
            return self._code_acting(agent, inst)
        payload = {"work_item": inst.context.get("work_item", {}),
                   "proposal": inst.context.get("proposal")}
        if agent == "triage" and self.cfs_store is not None:
            # give triage the existing specs so it can tell violates-spec / no-spec /
            # conflicts-spec apart (the §8 three-way classification)
            payload["existing_specs"] = [
                {"id": r["id"], "behavior": r.get("behavior", "")}
                for r in self.cfs_store.by_kind("specification")]
        res = self.runner.run(agent, payload, instance_id=inst.id)
        out = res.output or {}
        if agent == "spec-author" and res.ok:
            inst.context["proposal"] = out
        self.log(f"  agent {node.id}[{agent}] ok={res.ok} ${res.cost_usd:.4f}")
        return {"ok": res.ok, "output": out, "error": res.error}

    def _code_acting(self, agent, inst) -> dict:
        feat = self._feature(inst)
        if agent == "implement":
            r = self.implement_fn(feat)
            if getattr(r, "ok", False) and self.wm.is_dirty(feat):
                self.wm.commit(feat, f"implement {feat.item_id}")
            self.log(f"  implement ok={getattr(r,'ok',False)}")
            return {"ok": getattr(r, "ok", False), "output": getattr(r, "output", None) or {}}
        if agent == "test-author":
            # implement writes its own bound tests in this flow; a dedicated test-author
            # pass is a future refinement. Commit anything it leaves.
            if self.wm.is_dirty(feat):
                self.wm.commit(feat, "tests")
            return {"ok": True, "output": {}}
        if agent == "validate":
            passed = self.validate_fn(feat)
            inst.context["validation"] = {"passed": passed}
            self.log(f"  validate passed={passed}")
            return {"ok": True, "output": {"passed": passed}}
        return {"ok": True, "output": {}}

    def _system(self, node, inst) -> str:
        nid = node.id
        if nid == "serialize":
            spec_out = (inst.context.get("agent_outputs", {}).get("spec") or {}).get("output") or {}
            rec = spec_record_from(spec_out, inst.context.get("work_item", {}))
            feat = self.wm.start_feature(rec["id"])
            inst.context["feature"] = {"item_id": feat.item_id, "branch": feat.branch, "path": feat.path}
            inst.context["spec_record"] = rec
            self.wm.serialize_spec(feat, rec)
            self.wm.commit(feat, f"spec: {rec['id']}")
            self.log(f"  serialized {rec['id']} on {feat.branch}")
            return "serialized"
        if nid == "deploy":
            return "deploy (box 2 handled by validate)"   # validate_fn deploys + tests + resets
        if nid == "merge":
            feat = self._feature(inst)
            sha = self.wm.merge_to_release(feat)
            inst.context["release_sha"] = sha
            self.wm.finish_feature(feat)
            self.log(f"  merged -> release @ {sha[:8]}")
            return f"merged@{sha[:8]}"
        if nid == "resync":
            return "resync (files->DB)"
        return nid

    def _feature(self, inst) -> Feature:
        fd = inst.context.get("feature") or {}
        return Feature(fd.get("item_id", ""), fd.get("branch", ""), fd.get("path", ""))
