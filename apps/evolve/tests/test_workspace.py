"""Tests for apps/evolve/workspace.py — the box-1/box-2 git mechanics (EVOLVE.md §5).

Runs entirely on throwaway git repos in a temp dir. No network, no live deploy,
never touches the real repo.
"""
import os
import shutil
import tempfile
import unittest

from apps.evolve import workspace
from apps.evolve.workspace import WorkspaceManager, spec_relpath, GitError, git, _ID


def init_box1(root: str) -> str:
    """A minimal repo with `main` + `release` + one commit."""
    repo = os.path.join(root, "box1")
    os.makedirs(repo)
    git(repo, "init", "-q")
    with open(os.path.join(repo, "README.md"), "w") as fh:
        fh.write("seed\n")
    git(repo, "add", "-A")
    git(repo, *_ID, "commit", "-q", "-m", "init")
    git(repo, "branch", "-M", "main")
    git(repo, "branch", "release")
    return repo


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = init_box1(self.tmp)
        self.wm = WorkspaceManager(self.repo, worktrees_dir=os.path.join(self.tmp, "wt"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _release_has(self, relpath: str) -> bool:
        try:
            git(self.repo, "show", f"release:{relpath}")
            return True
        except GitError:
            return False

    def test_spec_relpath_layout(self):
        self.assertEqual(spec_relpath({"id": "evolve", "kind": "capability"}),
                         "apps/evolve/specs/_capability.yaml")
        self.assertEqual(spec_relpath({"id": "evolve.cfs-store", "kind": "feature"}),
                         "apps/evolve/specs/cfs-store/_feature.yaml")
        self.assertEqual(spec_relpath({"id": "evolve.cfs-store.boot-sync", "kind": "specification"}),
                         "apps/evolve/specs/cfs-store/boot-sync.yaml")

    def test_ensure_baseline_switches_to_release_and_reports_sha(self):
        # init_box1 leaves the repo on main; ensure_baseline must move it to release,
        # report a sha, and (offline, no origin) not claim a sync
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        info = self.wm.ensure_baseline()
        self.assertEqual(info["branch"], "release")
        self.assertTrue(info["sha"])
        self.assertFalse(info["synced"])      # no origin in the test repo
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "release")

    def test_start_feature_from_release(self):
        f = self.wm.start_feature("evolve.demo.thing")
        self.assertTrue(os.path.isdir(f.path))
        self.assertEqual(f.branch, "feature/evolve.demo.thing")
        self.assertEqual(git(f.path, "rev-parse", "--abbrev-ref", "HEAD"), f.branch)

    def test_write_commit_isolated_until_merge(self):
        f = self.wm.start_feature("evolve.demo.thing")
        self.wm.write_file(f, "apps/demo/thing.py", "print('hi')\n")
        self.assertTrue(self.wm.is_dirty(f))
        self.wm.commit(f, "implement thing")
        self.assertFalse(self.wm.is_dirty(f))
        # the change exists on the feature branch but NOT yet on release
        self.assertTrue(os.path.exists(os.path.join(f.path, "apps/demo/thing.py")))
        self.assertFalse(self._release_has("apps/demo/thing.py"))

    def test_serialize_spec_writes_layout(self):
        f = self.wm.start_feature("evolve.demo.thing")
        rec = {"kind": "specification", "id": "demo.area.thing", "title": "T",
               "state": "proposed", "behavior": "does a thing", "implements": [], "tests": []}
        rel = self.wm.serialize_spec(f, rec)
        self.assertEqual(rel, "apps/demo/specs/area/thing.yaml")
        self.assertTrue(os.path.exists(os.path.join(f.path, rel)))

    def test_merge_to_release(self):
        f = self.wm.start_feature("evolve.demo.thing")
        self.wm.write_file(f, "apps/demo/thing.py", "x = 1\n")
        self.wm.commit(f, "implement")
        self.wm.merge_to_release(f)
        self.assertTrue(self._release_has("apps/demo/thing.py"))   # now on release

    def test_box2_deploy_then_reset(self):
        f = self.wm.start_feature("evolve.demo.thing")
        self.wm.write_file(f, "apps/demo/thing.py", "x = 1\n")
        self.wm.commit(f, "implement")
        box2 = os.path.join(self.tmp, "box2")
        self.wm.box2_deploy(f, box2)
        self.assertTrue(os.path.exists(os.path.join(box2, "apps/demo/thing.py")))  # has the branch
        self.wm.box2_reset(box2)
        self.assertFalse(os.path.exists(os.path.join(box2, "apps/demo/thing.py")))  # back to release

    def test_path_escape_blocked(self):
        f = self.wm.start_feature("evolve.demo.thing")
        with self.assertRaises(GitError):
            self.wm.write_file(f, "../escape.py", "nope")


if __name__ == "__main__":
    unittest.main(verbosity=2)
