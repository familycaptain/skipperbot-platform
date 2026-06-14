"""Tests for apps/evolve/pipeline.py — the full gated pipeline, offline.

Walks a work-item through the whole SDLC graph with fake agents + a temp-repo
workspace, exercising both real gates (block → approve/reject → resume). No spend.
"""
import os
import shutil
import tempfile
import types
import unittest

from apps.evolve.engine import model as M
from apps.evolve.engine.instance import BLOCKED, DONE, REJECTED
from apps.evolve.agents.runner import Runner, FakeBackend
from apps.evolve.agents import registry
from apps.evolve.pipeline import Pipeline
from apps.evolve.workspace import WorkspaceManager, git
from tests.evolve.test_workspace import init_box1

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SDLC = os.path.join(REPO, "specs", "evolve", "sdlc.yaml")

# canned reasoning outputs keyed by AGENT name (happy path: feature, fits, surface, clean)
FAKE = {
    "triage": {"kind": "feature", "spec_status": "no-spec", "rationale": "new behavior, new scope"},
    "vision-fit": {"verdict": "fits", "rationale": "in charter"},
    "spec-author": {"spec_id": "demo.area.thing", "title": "Thing", "behavior": "adds a thing",
                    "implements": [], "tests": []},
    "security": {"approve": True, "concerns": []},
    "architecture": {"approve": True, "concerns": []},
    "interop": {"conflicts": []},
    "spec-audit": {"sound": True, "findings": []},
    "ux": {"approve": True, "concerns": []},
    "prioritize": {"score": 80, "decision": "surface", "rationale": "high value"},
    "review-packet": {"summary": "added a thing", "risk": "low",
                      "recommendation": "approve", "recommendation_why": "built + validated, low risk"},
}


class TestGatedPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = init_box1(self.tmp)
        self.wm = WorkspaceManager(self.repo, worktrees_dir=os.path.join(self.tmp, "wt"))
        self.model = M.load(SDLC)
        self.implemented = {}

        def implement_fn(feat):
            self.wm.write_file(feat, "apps/demo/thing.py", "VALUE = 1\n")
            self.implemented["did"] = True
            return types.SimpleNamespace(ok=True, output={"ok": True}, cost_usd=0.0)

        self.pipe = Pipeline(
            self.model,
            runner=Runner(FakeBackend(FAKE), dict(registry.ROSTER)),
            wm=self.wm, implement_fn=implement_fn, validate_fn=lambda feat: True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _release_has(self, rel):
        try:
            git(self.repo, "show", f"release:{rel}")
            return True
        except Exception:
            return False

    def test_blocks_at_gate1_with_packet(self):
        inst = self.pipe.submit({"title": "add a thing"})
        self.assertEqual(inst.status, BLOCKED)
        self.assertEqual(self.pipe.gate_waiting(inst), "gate1")
        pkt = self.pipe.packet(inst)
        self.assertEqual(pkt["proposal"]["spec_id"], "demo.area.thing")   # spec-author ran
        self.assertEqual(pkt["prioritize"]["decision"], "surface")

    def test_full_happy_path_through_both_gates_merges(self):
        inst = self.pipe.submit({"title": "add a thing"})
        self.assertEqual(self.pipe.gate_waiting(inst), "gate1")
        inst = self.pipe.approve(inst.id, "approve")          # gate 1
        self.assertEqual(inst.status, BLOCKED)
        self.assertEqual(self.pipe.gate_waiting(inst), "gate2")
        self.assertTrue(self.implemented.get("did"))           # implement ran between gates
        self.assertEqual(self.pipe.packet(inst)["validation"], {"passed": True})
        inst = self.pipe.approve(inst.id, "approve")          # gate 2
        self.assertEqual(inst.status, DONE)
        self.assertTrue(self._release_has("specs/demo/area/thing.yaml"))   # spec merged
        self.assertTrue(self._release_has("apps/demo/thing.py"))           # code merged

    def test_packet_always_carries_a_recommendation(self):
        inst = self.pipe.submit({"title": "add a thing"})
        rec1 = self.pipe.packet(inst)["recommendation"]      # gate 1
        self.assertIn("action", rec1)
        self.assertTrue(rec1.get("why"))                      # never a blank choice
        self.assertEqual(rec1["action"], "approve")           # clean reviews + surfaced
        inst = self.pipe.approve(inst.id, "approve")
        rec2 = self.pipe.packet(inst)["recommendation"]      # gate 2
        self.assertEqual(rec2["action"], "approve")
        self.assertTrue(rec2.get("why"))

    def test_reject_at_gate1_ends_rejected_no_code(self):
        inst = self.pipe.submit({"title": "add a thing"})
        inst = self.pipe.approve(inst.id, "reject")
        self.assertEqual(inst.status, REJECTED)
        self.assertFalse(self.implemented.get("did"))          # never implemented
        self.assertFalse(self._release_has("apps/demo/thing.py"))


class TestSpecAwareTriage(unittest.TestCase):
    def test_triage_receives_candidate_specs(self):
        tmp = tempfile.mkdtemp()
        try:
            repo = init_box1(tmp)
            wm = WorkspaceManager(repo, worktrees_dir=os.path.join(tmp, "wt"))
            from apps.evolve import store as cfsstore
            cfs = cfsstore.Store(cfsstore.InMemoryBackend())
            cfs.boot_sync(os.path.join(REPO, "specs", "evolve"), repo_root=REPO,
                          capability="evolve", on_main=True, bootstrap=True)
            captured = {}

            def responder(spec, payload, ctx):
                if spec.name == "triage":
                    captured["payload"] = dict(payload)
                return FAKE.get(spec.name)

            pipe = Pipeline(M.load(SDLC), runner=Runner(FakeBackend(responder), dict(registry.ROSTER)),
                            wm=wm, implement_fn=lambda f: types.SimpleNamespace(ok=True),
                            validate_fn=lambda f: True, cfs_store=cfs)
            pipe.submit({"title": "weather shows the wrong city for my ZIP"})
            specs = captured.get("payload", {}).get("existing_specs")
            self.assertIsNotNone(specs, "triage must receive the existing specs")
            self.assertGreaterEqual(len(specs), 8)
            self.assertIn("id", specs[0])
            self.assertIn("behavior", specs[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestOffVisionShortCircuit(unittest.TestCase):
    def test_off_vision_rejected_before_gate1(self):
        tmp = tempfile.mkdtemp()
        try:
            repo = init_box1(tmp)
            wm = WorkspaceManager(repo, worktrees_dir=os.path.join(tmp, "wt"))
            fake = dict(FAKE, **{"vision-fit": {"verdict": "off-vision", "rationale": "out of scope"}})
            pipe = Pipeline(M.load(SDLC), runner=Runner(FakeBackend(fake), dict(registry.ROSTER)),
                            wm=wm, implement_fn=lambda f: types.SimpleNamespace(ok=True),
                            validate_fn=lambda f: True)
            inst = pipe.submit({"title": "build a crypto trading bot"})
            self.assertEqual(inst.status, REJECTED)            # vision-fit short-circuits
            self.assertIsNone(pipe.gate_waiting(inst))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
