"""Tests for the process engine (apps/evolve/engine/*) against the REAL sdlc.yaml.

Bound to specs evolve.process-engine.{load-model,instance-state,walk-step,mermaid-render}.
Pure stdlib — no DB, no network.
"""
import os
import unittest

from apps.evolve.engine import model as M
from apps.evolve.engine import mermaid
from apps.evolve.engine.instance import SqliteInstanceStore, DONE, BLOCKED, REJECTED
from apps.evolve.engine.walker import Walker, _default_decider

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SDLC = os.path.join(REPO, "specs", "evolve", "sdlc.yaml")

# happy-path branch preferences for the exclusive gateways
_PREFER = {"gw_kind": "feature", "gw_vision": "fits", "gw_prio": "top-n",
           "gw_conf": "clear", "gw_tests": "green"}


def happy_decider(node, inst, outs):
    pref = _PREFER.get(node.id)
    if pref:
        for e in outs:
            if e.when and pref in e.when.lower():
                return e
    return _default_decider(node, inst, outs)


def make_walker():
    model = M.load(SDLC)
    ran = []
    return Walker(model,
                  system_handler=lambda n, i: ran.append(("sys", n.id)) or "ok",
                  agent_handler=lambda n, i: (ran.append(("agent", n.id)), {"ran": n.agent})[1],
                  exclusive_decider=happy_decider), model, ran


class TestModel(unittest.TestCase):
    def test_loads_and_validates(self):
        m = M.load(SDLC)
        # spec + the 5 review nodes + their gateways collapsed into the single `lead` node
        # (apps/evolve/lead.run_lead_phase runs them as an agentic inner loop).
        self.assertEqual(len(m.nodes), 31)
        self.assertEqual(len(m.edges), 43)   # + gw_kind -> prio (trusted: operator-authored skips vision-fit)
        self.assertIsNotNone(m.node("lead"))
        self.assertEqual(sorted(m.starts()), ["gen_design", "qa_sweep", "s_issue", "s_pr"])
        self.assertEqual(sorted(m.ends()), ["e_done", "e_parked", "e_rejected"])


class TestWalkHappyPath(unittest.TestCase):
    def test_issue_walks_to_done_through_both_gates(self):
        w, model, ran = make_walker()
        inst = w.start(context={"issue": "add an Edit button"}, at="s_issue")
        # blocks at gate 1
        self.assertEqual(inst.status, BLOCKED)
        self.assertIn("gate1", inst.tokens)
        w.resume_gate(inst, "approve")
        # blocks at gate 2
        self.assertEqual(inst.status, BLOCKED)
        self.assertIn("gate2", inst.tokens)
        w.resume_gate(inst, "approve")
        # done
        self.assertEqual(inst.status, DONE)
        self.assertIn("e_done", inst.context["ended_at"])
        visited = {d for _, d in [(t.src, t.dst) for t in inst.history]}
        for must in ("triage", "vision", "lead", "serialize", "impl", "merge", "resync", "e_done"):
            self.assertIn(must, visited, f"{must} should be on the path")

    def test_lead_orchestrates_the_spec_phase(self):
        # The reviewers (security/arch/interop/spec-audit/ux) now run INSIDE the lead node
        # (apps/evolve/lead.run_lead_phase), not as parallel graph nodes — so the graph
        # walk just shows `lead`, and the old per-reviewer nodes are gone.
        w, model, ran = make_walker()
        inst = w.start(at="s_issue")          # runs up to gate1
        agents_run = {nid for kind, nid in ran if kind == "agent"}
        self.assertIn("lead", agents_run, "the lead node owns the spec phase")
        for gone in ("spec", "sec", "arch", "crit"):
            self.assertNotIn(gone, agents_run, f"{gone} should no longer be a graph node")

    def test_rejection_ends_rejected(self):
        w, _, _ = make_walker()
        inst = w.start(at="s_issue")
        w.resume_gate(inst, "reject")
        self.assertEqual(inst.status, REJECTED)
        self.assertIn("e_rejected", inst.context["ended_at"])


class TestResumability(unittest.TestCase):
    def test_serialize_reload_midflight_then_finish(self):
        w, model, _ = make_walker()
        inst = w.start(at="s_issue")          # blocked at gate1
        self.assertEqual(inst.status, BLOCKED)
        # persist + reload (simulates a restart of either box)
        store = SqliteInstanceStore(":memory:")
        store.save(inst)
        reloaded = store.load(inst.id)
        self.assertEqual(reloaded.tokens, inst.tokens)
        self.assertEqual(reloaded.status, BLOCKED)
        # a fresh walker (new process) resumes the reloaded instance to completion
        w2 = Walker(model, system_handler=lambda n, i: "ok",
                    agent_handler=lambda n, i: {}, exclusive_decider=happy_decider)
        w2.resume_gate(reloaded, "approve")
        w2.resume_gate(reloaded, "approve")
        self.assertEqual(reloaded.status, DONE)


class TestMermaid(unittest.TestCase):
    def test_render_contains_all_nodes_and_highlight(self):
        m = M.load(SDLC)
        out = mermaid.render(m, highlight="gate1")
        self.assertTrue(out.startswith("flowchart TD"))
        for nid in m.nodes:
            self.assertIn(nid, out)
        self.assertIn("style gate1 stroke:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
