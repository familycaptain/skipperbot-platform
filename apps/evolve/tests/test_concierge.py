"""Tests for apps/evolve/concierge.py — the conversational liaison, offline.

A scripted fake backend drives the tool-use loop; a real (fake-agent) Pipeline
instance blocked at gate 1 gives the concierge something real to read + act on.
"""
import os
import shutil
import tempfile
import types
import unittest

from apps.evolve.engine import model as M
from apps.evolve.agents.runner import Runner, FakeBackend
from apps.evolve.agents import registry
from apps.evolve.pipeline import Pipeline
from apps.evolve.concierge import Concierge, ConciergeTools
from apps.evolve.workspace import WorkspaceManager
from apps.evolve.tests.test_workspace import init_box1
from apps.evolve.tests.test_pipeline import FAKE, REPO, SDLC


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _tool(name, inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=name, input=inp, id=tid)


class _Script:
    """Fake conversational backend: returns scripted content lists in order."""
    def __init__(self, turns):
        self.turns, self.i = turns, 0

    def respond(self, system, messages, tools):
        blocks = self.turns[self.i]
        self.i += 1
        return types.SimpleNamespace(content=blocks, cost_usd=0.0)


class TestConcierge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        repo = init_box1(self.tmp)
        self.wm = WorkspaceManager(repo, worktrees_dir=os.path.join(self.tmp, "wt"))
        pipe = Pipeline(M.load(SDLC), runner=Runner(FakeBackend(FAKE), dict(registry.ROSTER)),
                        wm=self.wm, implement_fn=self._impl, validate_fn=lambda f: True)
        self.pipe = pipe
        self.inst = pipe.submit({"title": "add a thing"})       # -> blocked at gate1
        self.tools = ConciergeTools(pipe)

    def _impl(self, feat):
        self.wm.write_file(feat, "apps/demo/thing.py", "VALUE = 1\n")
        return types.SimpleNamespace(ok=True, output={"ok": True}, cost_usd=0.0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tools_list_queue_and_packet(self):
        q = self.tools.list_queue()
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["gate"], "gate1")
        self.assertEqual(q[0]["recommendation"]["action"], "approve")
        pkt = self.tools.get_packet(self.inst.id)
        self.assertEqual(pkt["proposal"]["spec_id"], "demo.area.thing")

    def test_decide_relays_and_advances(self):
        res = self.tools.decide(self.inst.id, "approve", note="looks good")
        self.assertEqual(res["new_status"], "blocked")           # advanced to gate2
        self.assertIn("gate2", res["now_at"])
        inst = self.pipe.store.load(self.inst.id)
        self.assertEqual(inst.context["human_input"][0]["note"], "looks good")

    def test_chat_reads_then_answers(self):
        backend = _Script([[_tool("list_queue", {})],
                           [_text("You have 1 item at gate 1; the swarm recommends approve.")]])
        c = Concierge(self.tools, backend=backend, system="sys")
        turn = c.chat("what's waiting on me?")
        self.assertIn("gate 1", turn.reply)
        self.assertEqual(turn.tool_calls[0]["tool"], "list_queue")

    def test_chat_relays_decision(self):
        backend = _Script([
            [_tool("decide", {"instance_id": self.inst.id, "decision": "approve", "note": "go"})],
            [_text("Approved — it implemented, validated on box 2, and is now at gate 2.")],
        ])
        c = Concierge(self.tools, backend=backend, system="sys")
        turn = c.chat("approve it")
        self.assertEqual(turn.tool_calls[0]["tool"], "decide")
        self.assertIn("gate 2", turn.reply)
        self.assertEqual(self.pipe.gate_waiting(self.pipe.store.load(self.inst.id)), "gate2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
