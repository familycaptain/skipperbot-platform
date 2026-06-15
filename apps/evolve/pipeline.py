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
        if inst.status == REJECTED:
            self._teardown(inst)
        self.store.save(inst)
        self._maybe_notify_gate(inst)
        return inst

    def _teardown(self, inst: Instance) -> None:
        """Reject cleanup: remove the feature worktree + branch on box 1 so a rejected
        item leaves nothing orphaned. (approve->merge already cleans up via finish_feature;
        box 2 is reset by validate_fn after every run, so only box 1 needs teardown here.)"""
        fd = inst.context.get("feature")
        if not fd:
            return
        try:
            self.wm.finish_feature(Feature(fd.get("item_id", ""), fd.get("branch", ""), fd.get("path", "")))
            self.log(f"  reject teardown: removed worktree + branch {fd.get('branch')}")
            inst.context["feature"] = None
        except Exception as e:
            self.log(f"  reject teardown failed: {type(e).__name__}: {e}")

    def gate_waiting(self, inst: Instance) -> str | None:
        gates = [n for n in inst.tokens if self.model.node(n).type == "gate"]
        return gates[0] if gates else None

    def packet(self, inst: Instance) -> dict:
        """The pre-digested review packet the human reads at a gate (§8/§10). ALWAYS
        leads with a `recommendation` — nothing reaches the human as a blank choice."""
        ao = {k: (v or {}).get("output") for k, v in inst.context.get("agent_outputs", {}).items()}
        gate = self.gate_waiting(inst)
        # Every agent that ran gets a panel (Lead first), each led by its `summary`.
        panels = [("lead", "Lead"), ("design", "Design"), ("triage", "Triage"),
                  ("vision", "Vision-fit"), ("spec", "Spec-author"), ("crit", "Spec-audit"),
                  ("security", "Security"), ("architecture", "Architecture"),
                  ("interop", "Interop"), ("ux", "UX / UI"), ("prio", "Prioritize")]
        agents = [{"key": k, "label": lbl, "output": ao[k]} for k, lbl in panels if ao.get(k)]
        return {
            "instance": inst.id, "status": inst.status, "gate": gate,
            "recommendation": self._recommendation(inst, gate, ao),
            "work_item": inst.context.get("work_item"),
            "proposal": inst.context.get("proposal"),          # the (root) spec-author C/F/S
            "spec_tree": inst.context.get("spec_tree"),         # all specs when the design decomposed (#30)
            "decisions_needed": (ao.get("design") or {}).get("decisions_needed"),  # human forks (with a recommendation)
            "agents": agents,                                  # ordered per-agent panels (summary + output)
            "related": self._related(inst),                    # other in-flight items touching the same C/F/S/files
            "triage": ao.get("triage"),                        # incl. spec_status (violates/no-spec/conflicts)
            "reviews": {k: ao.get(k) for k in ("security", "architecture", "interop", "crit", "ux")},
            "prioritize": ao.get("prio"),
            "validation": inst.context.get("validation"),
            "review_packet": ao.get("packet"),
            "release_sha": inst.context.get("release_sha"),
        }

    @staticmethod
    def _touched(inst) -> tuple[set, set]:
        """The C/F/S ids + files this instance affects (from triage + its proposal)."""
        ao = inst.context.get("agent_outputs", {})
        triage = (ao.get("triage") or {}).get("output") or {}
        proposal = inst.context.get("proposal") or {}
        cfs = set(triage.get("touches_cfs") or []) | {proposal.get("spec_id")}
        files = {str(p).split("::")[0] for p in (proposal.get("implements") or [])}
        return cfs - {None, ""}, files - {None, ""}

    def _related(self, inst) -> list[dict]:
        """Other IN-FLIGHT instances touching the same C/F/S or files — so two items that
        edit the same code can't silently collide at merge (the cross-item gap). Surfaced
        in the packet; the operator decides ordering / supersedes."""
        mine_cfs, mine_files = self._touched(inst)
        mine_src = (inst.context.get("work_item") or {}).get("source")
        out = []
        try:
            others = self.store.all()
        except Exception:
            return []
        for other in others:
            if other.id == inst.id or other.status in (DONE, REJECTED, PARKED):
                continue
            o_cfs, o_files = self._touched(other)
            wi = other.context.get("work_item") or {}
            same_src = bool(mine_src) and wi.get("source") == mine_src   # same GitHub issue = duplicate
            shared = sorted((mine_cfs & o_cfs) | (mine_files & o_files))
            if same_src or shared:
                overlap = (["same issue: " + mine_src] if same_src else []) + shared[:5]
                out.append({"instance": other.id, "title": wi.get("title", ""),
                            "source": wi.get("source", ""), "gate": self.gate_waiting(other),
                            "status": other.status, "overlap": overlap})
        return out

    def _recommendation(self, inst, gate, ao) -> dict:
        """Synthesize a recommended action so the human never faces a bare decision.
        Even when uncertain, return the best call + why (+ what's unresolved)."""
        if gate == "gate1":
            # The Lead owns the Gate-1 recommendation (it arbitrated the spec team).
            lead_rec = inst.context.get("lead_recommendation")
            if lead_rec and lead_rec.get("action"):
                return {"action": lead_rec["action"], "why": lead_rec.get("why", "")}
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
        if agent == "lead":
            return self._lead(inst)
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

    def _lead(self, inst) -> dict:
        """The Lead node: run the agentic spec phase (Design -> author<->auditor -> reviewers,
        arbitrated, bounded) and fan every sub-agent's output into agent_outputs so the
        packet + UI panels find them. The Lead owns the proposal + the Gate-1 recommendation."""
        from apps.evolve.lead import run_lead_phase
        ao = inst.context.setdefault("agent_outputs", {})
        ctx = {"human_note": inst.context.get("human_note"),
               "triage": (ao.get("triage") or {}).get("output"),
               "vision": (ao.get("vision") or {}).get("output")}
        result = run_lead_phase(self.runner, inst.context.get("work_item", {}),
                                context=ctx, log=self.log)
        for key, output in result["outputs"].items():
            ao[key] = {"ok": True, "output": output}      # keyed for the packet + per-agent panels
        inst.context["proposal"] = result["proposal"]
        inst.context["spec_tree"] = result.get("spec_tree") or [result["proposal"]]
        inst.context["lead_recommendation"] = result["recommendation"]
        inst.context["human_note"] = None                  # consumed by this pass
        return {"ok": True, "output": result["outputs"].get("lead", {})}

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
            wi = inst.context.get("work_item", {})
            tree = inst.context.get("spec_tree") or [
                (inst.context.get("agent_outputs", {}).get("spec") or {}).get("output") or {}]
            root = spec_record_from(tree[0], wi)
            feat = self.wm.start_feature(root["id"])           # the feature branch is named for the root spec
            inst.context["feature"] = {"item_id": feat.item_id, "branch": feat.branch, "path": feat.path}
            inst.context["spec_record"] = root
            for spec_out in tree:                              # write EVERY spec in the tree to the branch
                self.wm.serialize_spec(feat, spec_record_from(spec_out, wi))
            extra = f" (+{len(tree) - 1} more)" if len(tree) > 1 else ""
            self.wm.commit(feat, f"spec: {root['id']}{extra}")
            self.log(f"  serialized {len(tree)} spec(s) on {feat.branch}")
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
