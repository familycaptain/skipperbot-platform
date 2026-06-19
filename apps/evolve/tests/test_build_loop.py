"""Tests for apps/evolve/build_loop.py — the implement→validate→merge orchestration.

Uses fake implement/validate so the loop is exercised end-to-end on a throwaway repo
with no live Claude and no real edits.
"""
import os
import shutil
import tempfile
import types
import unittest

from apps.evolve import build_loop
from apps.evolve.build_loop import run_build
from apps.evolve.workspace import WorkspaceManager, git
from apps.evolve.tests.test_workspace import init_box1

SPEC = {"kind": "specification", "id": "demo.area.thing", "title": "Thing",
        "state": "proposed", "behavior": "adds a thing", "implements": [], "tests": []}


def _ok():
    return types.SimpleNamespace(ok=True)


def _fail(err="nope"):
    return types.SimpleNamespace(ok=False, error=err)


class TestBuildLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = init_box1(self.tmp)
        self.wm = WorkspaceManager(self.repo, worktrees_dir=os.path.join(self.tmp, "wt"))
        self.box2 = os.path.join(self.tmp, "box2")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _release_has(self, rel):
        try:
            git(self.repo, "show", f"release:{rel}")
            return True
        except Exception:
            return False

    def test_happy_path_merges_to_release(self):
        def implement(feature):
            self.wm.write_file(feature, "apps/demo/thing.py", "x = 1\n")
            return _ok()
        res = run_build(self.wm, SPEC, implement_fn=implement, validate_fn=lambda f: True)
        self.assertTrue(res.ok, res.detail)
        self.assertEqual(res.stage, "merged")
        # both the spec file and the implemented code reached release
        self.assertTrue(self._release_has("apps/demo/specs/area/thing.yaml"))
        self.assertTrue(self._release_has("apps/demo/thing.py"))

    def test_validation_failure_stops_before_merge(self):
        def implement(feature):
            self.wm.write_file(feature, "apps/demo/thing.py", "x = 1\n")
            return _ok()
        res = run_build(self.wm, SPEC, implement_fn=implement, validate_fn=lambda f: False)
        self.assertFalse(res.ok)
        self.assertEqual(res.stage, "failed:validate")
        self.assertFalse(self._release_has("apps/demo/thing.py"))   # NOT merged

    def test_implement_failure_stops_early(self):
        res = run_build(self.wm, SPEC, implement_fn=lambda f: _fail("could not converge"),
                        validate_fn=lambda f: True)
        self.assertFalse(res.ok)
        self.assertEqual(res.stage, "failed:implement")
        # the spec was serialized but no code merged
        self.assertFalse(self._release_has("apps/demo/thing.py"))

    def test_adapters_constructible(self):
        # smoke: the adapters build without invoking Claude / box 2
        self.assertTrue(callable(build_loop.local_validate(self.wm, self.box2)))
        self.assertTrue(callable(build_loop.implement_with_agent({}, SPEC, model="claude-x")))
        box2 = build_loop.RemoteBox2("evolve-test.local", "repos/skipperbot-platform")
        self.assertTrue(callable(build_loop.remote_validate(box2)))

    def test_local_validate_runs_and_merges(self):
        # exercise the local stand-in validate end to end (deploy to box-2 clone +
        # a REAL unittest run there), then merge on green.
        def implement(feature):
            self.wm.write_file(feature, "apps/demo/thing.py", "VALUE = 1\n")
            self.wm.write_file(feature, "tests/test_demo.py",
                               "import unittest\n"
                               "class T(unittest.TestCase):\n"
                               "    def test_value(self): self.assertEqual(1, 1)\n")
            return _ok()
        vfn = build_loop.local_validate(self.wm, self.box2, test_path="tests")
        res = run_build(self.wm, SPEC, implement_fn=implement, validate_fn=vfn)
        self.assertTrue(res.ok, res.detail)
        self.assertTrue(self._release_has("apps/demo/thing.py"))


class TestBoundTestSelection(unittest.TestCase):
    def test_is_test_file(self):
        for p in ("tests/weather/test_zip.py", "apps/weather/test_tools.py",
                  "apps/x/tests/test_y.py", "foo_test.py"):
            self.assertTrue(build_loop.is_test_file(p), p)
        for p in ("apps/weather/tools.py", "apps/weather/specs/spec.yaml",
                  "tests/weather/fixtures.json", "README.md"):
            self.assertFalse(build_loop.is_test_file(p), p)

    def test_select_bound_tests_picks_only_tests(self):
        changed = ["apps/weather/tools.py", "tests/weather/test_zip.py", "README.md"]
        self.assertEqual(build_loop.select_bound_tests(changed), ["tests/weather/test_zip.py"])
        self.assertEqual(build_loop.select_bound_tests([]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
