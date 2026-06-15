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


def _norm_impl_path(p) -> str:
    """Normalize an `implements` entry to a bare repo path: drop a `::symbol` suffix and any
    trailing parenthetical/space description — 'apps/x.py::fn' and 'apps/x.py (does Y)' both
    become 'apps/x.py' — so overlap detection compares real files, not cosmetics."""
    s = str(p).split("::")[0].strip()
    for sep in (" (", "("):
        if sep in s:
            s = s.split(sep)[0]
    parts = s.split()
    return parts[0].strip() if parts else ""


def spec_record_from(spec_out: dict, work_item: dict) -> dict:
    """Build a C/F/S record from the spec-author agent's output."""
    sid = spec_out.get("spec_id") or "evolve.intake.unspecified"
    return {"kind": "specification", "id": sid,
            "title": spec_out.get("title") or (work_item.get("title", "") or "")[:60],
            "state": "proposed", "behavior": spec_out.get("behavior", ""),
            "implements": spec_out.get("implements", []),
            "tests": spec_out.get("tests", []), "links": {}, "notes": ""}


class Pipeline:
    # build-half nodes -> (stage label, human detail) for the live mission-control view
    _STAGES = {
        "serialize": ("serializing", "writing the spec to the feature branch"),
        "impl":      ("implementing", "writing the code + bound test"),
        "implement": ("implementing", "writing the code + bound test"),
        "deploy":    ("deploying", "box 2: checking out the feature branch"),
        "validate":  ("validating", "running the bound tests on box 2"),
        "merge":     ("merging", "feature → release"),
    }

    def __init__(self, model, *, runner, wm, implement_fn, validate_fn,
                 store=None, cfs_store=None, log=lambda *a: None, on_gate=None,
                 on_event=None, on_run=None, sdk_backend=None):
        self.model = model
        self.runner = runner               # reasoning agents (shares the cost ledger)
        self.sdk_backend = sdk_backend     # ClaudeSDKBackend: when set, the spec phase runs as ONE shared session
        self.wm = wm                        # WorkspaceManager (box 1)
        self.implement_fn = implement_fn    # (feature) -> result with .ok (writes the worktree)
        self.validate_fn = validate_fn      # (feature) -> bool (deploy to box 2 + run bound tests)
        self.cfs_store = cfs_store          # apps.evolve.store.Store: triage checks specs against the report
        self.store = store or InMemoryInstanceStore()
        self.log = log
        self.on_gate = on_gate              # callback(packet) fired when an instance BLOCKS at a human gate
        # live observability: on_event(inst_id, agent, kind, msg); on_run(inst_id, **fields)
        self.on_event = on_event
        self.on_run = on_run
        if runner is not None and on_event is not None:
            runner.on_event = on_event      # so every agent (incl. Lead sub-agents) streams
        self.walker = Walker(model, system_handler=self._system, agent_handler=self._agent,
                             exclusive_decider=output_driven_decider)

    # --- live activity helpers (best-effort) -------------------------------
    def _ev(self, inst, agent, kind, msg) -> None:
        if self.on_event:
            try:
                self.on_event(inst.id, agent, kind, msg)
            except Exception:
                pass

    def _run(self, inst, **fields) -> None:
        if self.on_run:
            try:
                self.on_run(inst.id, **fields)
            except Exception:
                pass

    def _ensure_baseline(self, inst, where: str) -> None:
        """Before any agent reads code/specs, make box 1's checkout the right + current
        baseline (fetch, on the release branch, latest folded in) and STAMP the exact
        branch@sha into the run + packet so every grounding is auditable. A hard sync
        failure aborts the run rather than letting an agent read stale/wrong code."""
        info = self.wm.ensure_baseline()
        inst.context["baseline"] = info
        msg = f"grounded on {info['branch']}@{info.get('sha', '?')}"
        if info.get("synced"):
            msg += " (pulled latest)"
        if info.get("dirty"):
            msg += " ⚠ working tree dirty"
        self._ev(inst, "engine", "info", f"{where}: {msg}")
        self.log(f"  baseline [{where}]: {msg}")

    def _maybe_notify_gate(self, inst: Instance) -> None:
        """When the walk parks at a human gate, fire the on_gate hook (e.g. Pushover).
        Best-effort: a notification failure never breaks the pipeline."""
        if self.on_gate is None or inst.status != BLOCKED or self.gate_waiting(inst) is None:
            return
        try:
            self.on_gate(self.packet(inst))
        except Exception as e:
            self.log(f"  on_gate hook failed: {type(e).__name__}: {e}")

    def _sync_run(self, inst) -> None:
        """Project the instance's lifecycle state onto the mission-control run row."""
        gate = self.gate_waiting(inst)
        if inst.status == DONE:
            self._run(inst, status="merged", phase="done", current_agent="")
        elif inst.status == REJECTED:
            self._run(inst, status="rejected", phase="done", current_agent="")
        elif gate:
            self._run(inst, status="waiting", current_node=gate, current_agent="")
            self._ev(inst, "engine", "info", f"parked at {gate} — waiting on the operator")
        else:
            self._run(inst, status="running")

    # public API ------------------------------------------------------------
    def submit(self, work_item: dict, at: str = "s_issue") -> Instance:
        inst = self.walker.start(context={"work_item": work_item}, at=at)
        wi = work_item or {}
        self._run(inst, title=wi.get("title", ""), source=wi.get("source", ""),
                  phase="intake", status="running")
        self._ev(inst, "engine", "info", f"intake: {wi.get('title', '(work item)')}")
        self._sync_run(inst)
        self.store.save(inst)
        self._maybe_notify_gate(inst)
        return inst

    def approve(self, instance_id: str, decision: str) -> Instance:
        inst = self.store.load(instance_id)
        if inst is None:
            raise ValueError(f"no such instance {instance_id}")
        self._run(inst, status="building")
        self._ev(inst, "engine", "info", f"operator decision: {decision} — resuming")
        self.walker.resume_gate(inst, decision)
        if inst.status == REJECTED:
            self._teardown(inst)
        self._sync_run(inst)
        self.store.save(inst)
        self._maybe_notify_gate(inst)
        if inst.status == DONE:
            self._propagate_conflicts(inst)   # warn other in-flight items this merge may collide with
        return inst

    def _propagate_conflicts(self, merged) -> None:
        """When an item MERGES, its change lands in `release` — and any OTHER in-flight item
        was planned against the OLD release. Reach out to each overlapping item (shared
        C/F/S or files), ask the interop agent whether the just-merged change conflicts with
        that item's plan, and if so annotate it + re-surface its gate so the operator can send
        it back for the Lead to re-evaluate. Best-effort: never let it break the merge."""
        try:
            m_cfs, m_files = self._touched(merged)
            if not (m_cfs or m_files):
                return
            m_spec = merged.context.get("spec_record") or merged.context.get("proposal") or {}
            m_title = (merged.context.get("work_item") or {}).get("title", "")
            for other in self.store.all():
                if other.id == merged.id or other.status in (DONE, REJECTED, PARKED):
                    continue
                o_cfs, o_files = self._touched(other)
                shared = sorted((m_cfs & o_cfs) | (m_files & o_files))
                if not shared:
                    continue
                merged_desc = {"id": m_spec.get("spec_id") or m_spec.get("id") or merged.id,
                               "behavior": m_spec.get("behavior", "")}
                res = self.runner.run("interop", {
                    "phase": "post-merge", "work_item": other.context.get("work_item", {}),
                    "proposal": other.context.get("proposal") or {},
                    "existing_specs": [merged_desc],
                    "merged": {"title": m_title, "files": sorted(m_files)}},
                    instance_id=other.id)
                conflicts = (res.output or {}).get("conflicts") or []
                other.context.setdefault("conflict_alerts", []).append({
                    "from": merged.id, "from_title": m_title, "shared": shared[:6],
                    "conflicts": conflicts, "gate": self.gate_waiting(other)})
                self._ev(other, "interop", "info",
                         f"⚠ {merged.id} merged changes to {', '.join(shared[:3])} — "
                         + (f"CONFLICT: {conflicts[0].get('detail', '')}" if conflicts
                            else "overlap; this item's plan may be stale — re-review"))
                self.store.save(other)
                self._maybe_notify_gate(other)    # re-push so the alert reaches the operator
                self.log(f"  conflict-propagation: flagged {other.id} "
                         f"({'CONFLICT' if conflicts else 'overlap'} on {shared[:3]})")
        except Exception as e:
            self.log(f"  conflict-propagation failed (non-fatal): {type(e).__name__}: {e}")

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
        # Gate 1 shows the spec-phase proposal panels ("we should…"); Gate 2 shows the
        # result-review panels ("here's what we changed…", past tense, per domain).
        if gate == "gate2":
            panels = [("r_lead", "Lead"), ("r_architecture", "Architecture"),
                      ("r_ux", "UX / UI"), ("r_interop", "Interop"), ("r_security", "Security")]
        else:
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
            "conflict_alerts": inst.context.get("conflict_alerts"),  # a related item MERGED — this plan may be stale
            "baseline": inst.context.get("baseline"),           # branch@sha the agents were grounded on
            "triage": ao.get("triage"),                        # incl. spec_status (violates/no-spec/conflicts)
            "reviews": {k: ao.get(k) for k in ("security", "architecture", "interop", "crit", "ux")},
            "prioritize": ao.get("prio"),
            "validation": inst.context.get("validation"),
            "review_packet": ao.get("packet"),
            "release_sha": inst.context.get("release_sha"),
        }

    @staticmethod
    def _touched(inst) -> tuple[set, set]:
        """The C/F/S ids + files this instance affects — across its WHOLE spec tree (every
        authored leaf, not just the root) so a decomposed feature's real file footprint is
        seen, with paths normalized (drop '::symbol' and parenthetical descriptions) so two
        items that touch the same file aren't missed over cosmetic differences."""
        ao = inst.context.get("agent_outputs", {})
        triage = (ao.get("triage") or {}).get("output") or {}
        specs = list(inst.context.get("spec_tree") or [])
        proposal = inst.context.get("proposal") or {}
        if proposal and proposal not in specs:
            specs.append(proposal)
        cfs = set(triage.get("touches_cfs") or [])
        files: set = set()
        for sp in specs:
            if not isinstance(sp, dict):
                continue
            cfs.add(sp.get("spec_id"))
            for p in (sp.get("implements") or []):
                np = _norm_impl_path(p)
                if np:
                    files.add(np)
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
                return {"action": lead_rec["action"], "why": lead_rec.get("why", ""),
                        "current": lead_rec.get("current", ""), "after": lead_rec.get("after", "")}
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
            if val.get("passed") is not True:
                # Never recommend approve over an unverified build. Say WHY it failed:
                # implement never produced a good change, or the bound tests went red.
                reason = val.get("reason")
                why = (f"do NOT ship — {reason}; send back to implement" if reason
                       else "bound tests did not pass on box 2 — send back to implement")
                return {"action": "change", "why": why}
            # The Lead's result verdict owns the Gate-2 recommendation (it reviewed the diff).
            res_rec = inst.context.get("result_recommendation")
            if res_rec and res_rec.get("action"):
                return {"action": res_rec["action"], "why": res_rec.get("why", ""),
                        "current": res_rec.get("current", ""), "after": res_rec.get("after", ""),
                        "risk": pkt.get("risk", "low")}
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
        if agent == "review-packet":
            self._result_review(inst)   # Gate-2: domain agents review the real diff + Lead verdict
        else:
            self._run(inst, phase="intake", current_node=node.id, current_agent=agent)
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
        self._run(inst, phase="spec", current_node="lead", current_agent="lead")
        self._ensure_baseline(inst, "spec phase")   # agents read the right, current code/specs
        self._ev(inst, "lead", "info", "spec phase: Design → author ⇄ auditor → reviewers")
        ctx = {"human_note": inst.context.get("human_note"),
               "triage": (ao.get("triage") or {}).get("output"),
               "vision": (ao.get("vision") or {}).get("output")}
        if self.sdk_backend is not None:
            # Stage 2/3: ONE shared, prompt-cached claude-agent-sdk session — constructive chain
            # resumes (no digest), critics fork; per-agent tool calls stream to the live lanes.
            from apps.evolve.lead_sdk import run_lead_phase_sdk
            result = run_lead_phase_sdk(self.runner, self.sdk_backend, inst.context.get("work_item", {}),
                                        context=ctx, log=self.log, instance_id=inst.id,
                                        on_event=self.on_event)
        else:
            result = run_lead_phase(self.runner, inst.context.get("work_item", {}),
                                    context=ctx, log=self.log, instance_id=inst.id)
        for key, output in result["outputs"].items():
            ao[key] = {"ok": True, "output": output}      # keyed for the packet + per-agent panels
        inst.context["proposal"] = result["proposal"]
        inst.context["spec_tree"] = result.get("spec_tree") or [result["proposal"]]
        inst.context["lead_recommendation"] = result["recommendation"]
        inst.context["code_context"] = result.get("code_context")   # shared grounding for implement
        inst.context["sdk_session_id"] = result.get("session_id")    # the spec conversation (build half can resume)
        inst.context["human_note"] = None                  # consumed by this pass
        return {"ok": True, "output": result["outputs"].get("lead", {})}

    def _result_review(self, inst) -> None:
        """Gate-2 review: the domain agents look at the ACTUAL diff and report what was
        CHANGED in their area (past tense), and the Lead gives the 'fix made / worked or
        not' verdict. Stored under r_* keys so the Gate-2 packet shows these — not the
        Gate-1 'we should…' proposals."""
        from apps.evolve.lead import run_result_review
        self._run(inst, phase="build", status="building",
                  current_node="result-review", current_agent="lead")
        self._ev(inst, "lead", "info", "gate 2: reviewing what actually changed")
        feat = self._feature(inst)
        try:
            diff = self.wm.diff(feat)
        except Exception:
            diff = ""
        spec = inst.context.get("spec_record") or (inst.context.get("proposal") or {})
        result = run_result_review(self.runner, inst.context.get("work_item", {}), spec=spec,
                                   diff=diff, validation=inst.context.get("validation") or {},
                                   instance_id=inst.id, log=self.log)
        ao = inst.context.setdefault("agent_outputs", {})
        for key, output in result["outputs"].items():
            ao[f"r_{key}"] = {"ok": True, "output": output}    # gate-2 panels (separate keys)
        inst.context["result_recommendation"] = result["recommendation"]

    def _code_acting(self, agent, inst) -> dict:
        feat = self._feature(inst)
        stage, detail = self._STAGES.get(agent, ("building", agent))
        self._run(inst, phase="build", status="building", current_node=agent, current_agent=agent)
        self._ev(inst, agent, "node", f"{stage}: {detail}")
        if agent == "implement":
            return self._finish_implement(inst, feat, self.implement_fn(feat))
        if agent == "test-author":
            # implement writes its own bound tests in this flow; a dedicated test-author
            # pass is a future refinement. Commit anything it leaves.
            if self.wm.is_dirty(feat):
                self.wm.commit(feat, "tests")
            return {"ok": True, "output": {}}
        if agent == "validate":
            # Gate on implement: a failed (or empty) implement must NEVER reach a green
            # gate2. Don't waste a box-2 run on it — fail validation with the reason.
            if not inst.context.get("implement_ok", False):
                reason = inst.context.get("implement_error") or "implement did not succeed"
                inst.context["validation"] = {"passed": False, "ran": False, "reason": reason}
                self.log(f"  validate SKIPPED — {reason}")
                self._ev(inst, "validate", "error", f"skipped — {reason}")
                return {"ok": True, "output": {"passed": False, "reason": reason}}
            passed = bool(self.validate_fn(feat))
            inst.context["validation"] = {"passed": passed, "ran": True}
            self.log(f"  validate passed={passed}")
            self._ev(inst, "validate", "agent_end",
                     "✓ bound tests green on box 2" if passed else "✗ bound tests RED on box 2")
            return {"ok": True, "output": {"passed": passed}}
        return {"ok": True, "output": {}}

    def _finish_implement(self, inst, feat, r) -> dict:
        """Commit the implement agent's work and decide whether it actually succeeded.
        `ok` ALONE is not trustworthy — an agent can report success while changing
        nothing. Real success = ok AND it left a code change. Record the verdict +
        reason in context so `validate` can gate on it and gate2 can explain it.
        Shared by the base pipeline and the live RealPipeline (which builds its own
        implement_fn from the work item + spec)."""
        from apps.evolve.build_loop import select_bound_tests
        ok = bool(getattr(r, "ok", False))
        changed = self.wm.is_dirty(feat)
        if ok and changed:
            self.wm.commit(feat, f"implement {feat.item_id}")
        # Real success = ok AND a code change AND a bound test in that change. A change with
        # no test can't be validated (its behavior is unproven), so it must NOT reach green.
        bound = select_bound_tests(self.wm.changed_files(feat)) if (ok and changed) else []
        inst.context["bound_tests"] = bound
        implemented = ok and changed and bool(bound)
        inst.context["implement_ok"] = implemented
        inst.context["implement_error"] = None if implemented else (
            getattr(r, "error", None)
            or ("agent reported success but added no bound test — the change is unverifiable"
                if ok and changed else
                "agent reported success but changed no files" if ok
                else "implement agent did not complete"))
        self.log(f"  implement ok={ok} changed={changed} bound_tests={len(bound)} "
                 f"-> implemented={implemented}")
        self._ev(inst, "implement", "agent_end",
                 (f"✓ wrote code + {len(bound)} bound test(s)" if implemented
                  else f"✗ {inst.context['implement_error']}"))
        return {"ok": implemented, "output": getattr(r, "output", None) or {}}

    def _system(self, node, inst) -> str:
        nid = node.id
        if nid == "serialize":
            self._ensure_baseline(inst, "build")   # cut the feature worktree from CURRENT release
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
            self._run(inst, phase="build", status="building", current_node="serialize",
                      current_agent="serialize")
            self._ev(inst, "serialize", "node", f"wrote {len(tree)} spec(s) to {feat.branch}")
            return "serialized"
        if nid == "deploy":
            return "deploy (box 2 handled by validate)"   # validate_fn deploys + tests + resets
        if nid == "merge":
            feat = self._feature(inst)
            self._ev(inst, "merge", "node", "merging feature → release")
            sha = self.wm.merge_to_release(feat)
            inst.context["release_sha"] = sha
            self.wm.finish_feature(feat)
            # publish the candidate to origin/release — the staging branch the Pi tracks
            pushed = self.wm.push_release()
            inst.context["release_published"] = pushed
            self.log(f"  merged -> release @ {sha[:8]}"
                     + ("  + published origin/release" if pushed else "  (origin/release NOT pushed)"))
            self._ev(inst, "merge", "agent_end", f"✓ merged → release @ {sha[:8]}"
                     + (" · published to origin/release (Pi can pull it)" if pushed
                        else " · ⚠ not published to origin/release (box 1 push rights?)"))
            return f"merged@{sha[:8]}"
        if nid == "resync":
            return "resync (files->DB)"
        return nid

    def _feature(self, inst) -> Feature:
        fd = inst.context.get("feature") or {}
        return Feature(fd.get("item_id", ""), fd.get("branch", ""), fd.get("path", ""))
