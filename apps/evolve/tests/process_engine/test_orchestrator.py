"""Tests for output-driven routing (apps/evolve/orchestrator.py) — OFFLINE.

Proves agent outputs steer the exclusive gateways, using a fake agent_handler that
injects predetermined structured outputs (no network, no spend).
"""
import os
import unittest

from apps.evolve.engine import model as M
from apps.evolve.engine.instance import DONE, REJECTED, PARKED
from apps.evolve.engine.walker import Walker
from apps.evolve import orchestrator

REPO = __import__("repo_paths").ROOT
SDLC = os.path.join(REPO, "apps", "evolve", "specs", "sdlc.yaml")


def walk_with(outputs: dict):
    """Walk from s_issue with fake agent outputs keyed by node id; auto-approve gates."""
    model = M.load(SDLC)

    def agent_handler(node, inst):
        out = outputs.get(node.id, {})
        inst.context.setdefault("agent_outputs", {})[node.id] = {"ok": True, "output": out}
        return {"ok": True, "output": out}

    w = Walker(model, system_handler=lambda n, i: "ok",
               agent_handler=agent_handler,
               exclusive_decider=orchestrator.output_driven_decider)
    inst = w.start(context={"work_item": {}}, at="s_issue")
    while inst.status == "blocked":
        gate = next(n for n in inst.tokens if model.node(n).type == "gate")
        w.resume_gate(inst, "approve", gate)
    return inst


class TestOutputDrivenRouting(unittest.TestCase):
    def test_feature_fits_surface_completes(self):
        inst = walk_with({
            "triage": {"kind": "feature"},
            "vision": {"verdict": "fits"},
            "prio": {"decision": "surface"},
            "interop": {"conflicts": []},
        })
        self.assertEqual(inst.status, DONE)

    def test_off_vision_is_rejected(self):
        inst = walk_with({"triage": {"kind": "feature"}, "vision": {"verdict": "off-vision"}})
        self.assertEqual(inst.status, REJECTED)
        self.assertIn("e_rejected", inst.context["ended_at"])

    def test_bug_skips_vision(self):
        inst = walk_with({
            "triage": {"kind": "bug"},
            "prio": {"decision": "surface"},
            "interop": {"conflicts": []},
        })
        # bug routes straight to spec (no vision node visited)
        visited = {t.dst for t in inst.history}
        self.assertNotIn("vision", visited)
        self.assertEqual(inst.status, DONE)

    def test_park_low_priority(self):
        inst = walk_with({
            "triage": {"kind": "feature"},
            "vision": {"verdict": "fits"},
            "prio": {"decision": "park"},
        })
        self.assertEqual(inst.status, PARKED)
        self.assertIn("e_parked", inst.context["ended_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
