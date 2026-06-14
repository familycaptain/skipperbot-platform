"""Tests for the tool-use backend (apps/evolve/agents/tooluse.py).

Offline: the bash sandbox, skill parsing, the agentic loop (mocked client), and
Runner routing. Live (gated): a real code-acting agent executing a skill.
"""
import os
import tempfile
import types
import unittest

from apps.evolve.agents import tooluse, registry
from apps.evolve.agents.base import AgentResult
from apps.evolve.agents.runner import Runner, FakeBackend
from apps.evolve.agents.tooluse import (ToolUseBackend, run_bash, read_file, write_file,
                                        load_skill)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SKILLS = os.path.join(REPO, ".claude", "skills")


class TestBashSandbox(unittest.TestCase):
    def test_denies_metacharacters(self):
        out = run_bash("python3 --version; rm -rf /", ["python3 *"], cwd=REPO)
        self.assertIn("DENIED", out)
        self.assertIn("metacharacter", out)

    def test_denies_unlisted_command(self):
        out = run_bash("rm -rf /", ["python3 -m unittest*"], cwd=REPO)
        self.assertIn("DENIED", out)

    def test_allows_and_runs_listed_command(self):
        out = run_bash("python3 --version", ["python3 --version"], cwd=REPO)
        self.assertIn("exit 0", out)
        self.assertIn("Python", out)

    def test_read_file_denies_escape(self):
        self.assertIn("DENIED", read_file("../../../etc/passwd", cwd=REPO))

    def test_read_file_reads_repo_file(self):
        self.assertIn("Skipper", read_file("specs/CHARTER.md", cwd=REPO))


class TestSkillLoading(unittest.TestCase):
    def test_parses_allow_patterns(self):
        sk = load_skill("cfs-validate", SKILLS)
        self.assertTrue(sk["body"])
        self.assertTrue(any("apps.evolve.schema" in p for p in sk["allow"]))

    def test_run_evolve_tests_allows_unittest(self):
        sk = load_skill("run-evolve-tests", SKILLS)
        self.assertTrue(any("unittest" in p for p in sk["allow"]))


# --- mocked agentic loop --------------------------------------------------- #
def _block(**kw):
    return types.SimpleNamespace(type="tool_use", **kw)


def _msg(blocks):
    return types.SimpleNamespace(content=blocks, stop_reason="tool_use",
                                 usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))


class _FakeClient:
    def __init__(self, responses):
        self._responses, self._i = responses, 0
        self.messages = self

    def create(self, **kw):
        r = self._responses[self._i]
        self._i += 1
        return r


class TestAgenticLoop(unittest.TestCase):
    def test_executes_tool_then_emits(self):
        responses = [
            _msg([_block(name="bash", input={"command": "python3 -m unittest --help"}, id="t1")]),
            _msg([_block(name="emit", input={"passed": True, "failures": [], "notes": "ran the suite"}, id="t2")]),
        ]
        be = ToolUseBackend(client=_FakeClient(responses), repo_root=REPO, skills_dir=SKILLS)
        res = be.run(registry.ROSTER["validate"], {"task": "check"}, None, "claude-x", system="sys")
        self.assertTrue(res.ok, res.error)
        self.assertTrue(res.output["passed"])
        self.assertIn("python3 -m unittest --help", res.raw_text)   # the tool actually ran
        self.assertGreater(res.input_tokens, 0)

    def test_gives_up_without_emit(self):
        # agent keeps calling bash, never emits -> bounded by max_turns
        loop = [_msg([_block(name="bash", input={"command": "python3 --version"}, id="t")])]
        be = ToolUseBackend(client=_FakeClient(loop * 5), repo_root=REPO,
                            skills_dir=SKILLS, max_turns=3)
        res = be.run(registry.ROSTER["validate"], {}, None, "claude-x", system="s")
        self.assertFalse(res.ok)
        self.assertIn("did not emit", res.error)


class TestWrites(unittest.TestCase):
    def test_write_file_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("wrote", write_file("pkg/a.py", "x = 1\n", cwd=d))
            self.assertTrue(os.path.exists(os.path.join(d, "pkg/a.py")))
            self.assertIn("DENIED", write_file("../escape.py", "no", cwd=d))

    def test_write_tool_gated_by_allow_writes(self):
        spec = registry.ROSTER["implement"]
        on = ToolUseBackend(allow_writes=True)._tools(spec)
        off = ToolUseBackend(allow_writes=False)._tools(spec)
        self.assertTrue(any(t["name"] == "write_file" for t in on))
        self.assertFalse(any(t["name"] == "write_file" for t in off))

    def test_loop_writes_then_emits(self):
        with tempfile.TemporaryDirectory() as d:
            responses = [
                _msg([_block(name="write_file",
                             input={"path": "apps/demo/x.py", "content": "print(1)\n"}, id="w")]),
                _msg([_block(name="emit",
                             input={"summary": "wrote x", "files_changed": ["apps/demo/x.py"],
                                    "ok": True}, id="e")]),
            ]
            be = ToolUseBackend(client=_FakeClient(responses), repo_root=d,
                                skills_dir=SKILLS, allow_writes=True)
            res = be.run(registry.ROSTER["implement"], {"spec": "make x"}, None, "claude-x", system="s")
            self.assertTrue(res.ok, res.error)
            self.assertTrue(res.output["ok"])
            self.assertTrue(os.path.exists(os.path.join(d, "apps/demo/x.py")))


class TestRunnerRouting(unittest.TestCase):
    def test_requires_tools_routes_to_tool_backend(self):
        class Spy(FakeBackend):
            def __init__(self):
                super().__init__({})
                self.hit = False

            def run(self, spec, payload, context, model, system=""):
                self.hit = True
                return AgentResult(spec.name, ok=True, output={"summary": "s", "ok": True}, model=model)

        reasoning, tool = Spy(), Spy()
        r = Runner(reasoning, dict(registry.ROSTER), tool_backend=tool)
        r.run("implement", {})          # requires_tools -> tool backend
        self.assertTrue(tool.hit)
        self.assertFalse(reasoning.hit)
        reasoning.hit = tool.hit = False
        r.run("triage", {})             # reasoning -> normal backend
        self.assertTrue(reasoning.hit)
        self.assertFalse(tool.hit)


@unittest.skipUnless(os.getenv("EVOLVE_LIVE_TESTS") == "1",
                     "live tool-use test (set EVOLVE_LIVE_TESTS=1)")
class TestToolUseLive(unittest.TestCase):
    def test_validate_agent_runs_the_suite(self):
        from apps.evolve.orchestrator import _load_env
        from apps.evolve.agents.runner import MODEL_TIERS
        _load_env()
        be = ToolUseBackend(repo_root=REPO, skills_dir=SKILLS, max_turns=6)
        spec = registry.ROSTER["validate"]
        res = be.run(spec, {"task": "Confirm the Evolve offline test suite is green."},
                     None, MODEL_TIERS["fast"], system=spec.resolved_prompt())
        print(f"\n[live tool-use] ok={res.ok} output={res.output} ${res.cost_usd:.5f}")
        print("transcript:\n" + res.raw_text[:600])
        self.assertTrue(res.ok, res.error)
        self.assertIn("unittest", res.raw_text)     # it actually ran the skill's command


if __name__ == "__main__":
    unittest.main(verbosity=2)
