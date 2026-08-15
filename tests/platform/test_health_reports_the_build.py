"""Health says which branch and commit is running.

"What is actually deployed?" has been unanswerable without shell access to the box, and
that has cost real time: an app silently failing every night because its code was five
weeks stale, a fix sitting on a branch the host was not tracking while `skipper update`
correctly reported "already up to date", a schedule that existed and was healthy but
invisible. Every one of those was a five-second check if the running build were visible.

The production host is moved between branches deliberately — `main` normally, because that
is what the public runs, and `release` when fixes are being pre-tested — so the BRANCH
matters as much as the commit.

Read from .git directly rather than by shelling out: the container has no git binary, only
the bind-mounted working tree. And it must fail soft — health answering is more important
than health being complete.
"""
import ast
import functools
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "apps")) and os.path.isdir(os.path.join(d, "tests")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("repo root not found")


REPO = _repo_root()


def _load(fake_root=None):
    """Compile _build_info from the real source, rooted at a directory we control.

    Compiled from agent.py itself so the test cannot drift from the code it guards, and
    without importing agent.py, which needs the whole runtime.
    """
    with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
        src = fh.read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_build_info")
    mod = types.ModuleType("shim")
    mod.__dict__.update({
        "functools": functools, "Path": Path, "logger": logging.getLogger("test"),
        # _build_info resolves .git relative to the module file's parent.
        "__file__": os.path.join(fake_root or REPO, "agent.py"),
    })
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<shim>", "exec"), mod.__dict__)
    return mod._build_info


class _Checkout:
    """A throwaway .git directory in whatever shape we want to test."""

    def __init__(self, head, refs=None, packed=None, gitdir_is_file=False):
        self.head, self.refs, self.packed = head, refs or {}, packed
        self.gitdir_is_file = gitdir_is_file

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        real = root / (".realgit" if self.gitdir_is_file else ".git")
        real.mkdir(parents=True)
        (real / "HEAD").write_text(self.head, encoding="utf-8")
        for ref, sha in self.refs.items():
            p = real / ref
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(sha, encoding="utf-8")
        if self.packed is not None:
            (real / "packed-refs").write_text(self.packed, encoding="utf-8")
        if self.gitdir_is_file:
            (root / ".git").write_text(f"gitdir: {real}\n", encoding="utf-8")
        return str(root)

    def __exit__(self, *exc):
        self.tmp.cleanup()
        return False


class ItReportsTheRunningBuild(unittest.TestCase):
    def test_a_normal_checkout(self):
        with _Checkout("ref: refs/heads/main\n",
                       {"refs/heads/main": "abcdef1234567890\n"}) as root:
            self.assertEqual(_load(root)(), {"branch": "main", "commit": "abcdef1"})

    def test_the_branch_is_reported_not_just_the_commit(self):
        # The host is moved between main and release on purpose; the commit alone does not
        # say which of those it is following.
        with _Checkout("ref: refs/heads/release\n",
                       {"refs/heads/release": "1234567890abcdef\n"}) as root:
            self.assertEqual(_load(root)()["branch"], "release")

    def test_a_freshly_cloned_checkout_with_packed_refs(self):
        # A clone has no loose ref file — reading only .git/refs would report an empty
        # commit on exactly the hosts that were just deployed.
        with _Checkout("ref: refs/heads/main\n", {},
                       packed="# pack-refs with: peeled fully-peeled sorted\n"
                              "fedcba9876543210 refs/heads/main\n"
                              "0000000000000000 refs/remotes/origin/main\n") as root:
            self.assertEqual(_load(root)(), {"branch": "main", "commit": "fedcba9"})

    def test_a_detached_head_says_so(self):
        with _Checkout("9876543210fedcba\n") as root:
            info = _load(root)()
            self.assertEqual(info["branch"], "(detached)")
            self.assertEqual(info["commit"], "9876543")

    def test_a_worktree_whose_git_is_a_file(self):
        with _Checkout("ref: refs/heads/wt\n", {"refs/heads/wt": "aaaabbbbccccdddd\n"},
                       gitdir_is_file=True) as root:
            self.assertEqual(_load(root)(), {"branch": "wt", "commit": "aaaabbb"})


class ItNeverBreaksHealth(unittest.TestCase):
    """A health probe that raises takes the container down. Completeness is secondary."""

    def test_no_git_directory_at_all(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_load(root)(), {"branch": "", "commit": ""})

    def test_an_unreadable_head(self):
        with _Checkout("") as root:
            self.assertEqual(_load(root)(), {"branch": "", "commit": ""})

    def test_a_read_that_raises_is_swallowed(self):
        # The cases above are handled by explicit branches. This one genuinely throws
        # inside the read — HEAD present but not a file — which is what the except is for.
        # Without it, an odd checkout would take the health endpoint down with it.
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / ".git" / "HEAD").mkdir(parents=True)
            self.assertEqual(_load(root)(), {"branch": "", "commit": ""})

    def test_a_ref_that_points_nowhere(self):
        with _Checkout("ref: refs/heads/main\n", {}) as root:   # no loose ref, no packed-refs
            info = _load(root)()
            self.assertEqual(info["branch"], "main")
            self.assertEqual(info["commit"], "")


class TheEndpointIncludesIt(unittest.TestCase):
    def test_health_returns_the_build_info(self):
        with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index('@app.get("/api/health")')
        body = src[start:start + 300]
        self.assertIn("_build_info()", body)

    def test_it_is_computed_once_not_per_request(self):
        # Health is polled constantly; re-reading .git every time is waste.
        with open(os.path.join(REPO, "agent.py"), encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _build_info(")
        self.assertIn("lru_cache", src[max(0, start - 120):start])


if __name__ == "__main__":
    unittest.main()
