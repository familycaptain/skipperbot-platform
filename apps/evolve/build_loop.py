"""Build loop — the box-1 implement→validate→merge cycle (EVOLVE.md §5/§8).

Strings the workspace mechanics together: cut a feature worktree, serialize the
approved spec, let `implement` write code INTO the worktree (writes are safe there —
it's isolated, not the running code), commit, deploy to box 2, validate, and on green
merge feature -> release.

`run_build` takes injected `implement_fn` / `validate_fn` so the orchestration is
unit-testable with fakes (no live Claude, no real edits). The real adapters
(`implement_with_agent`, `validate_with_tests`) wire the tool-use `implement` agent +
a box-2 test run — ready to use once box 2 exists.
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable

from apps.evolve.workspace import WorkspaceManager, Feature

# implement_fn(feature) -> object with .ok (writes code into feature.path)
ImplementFn = Callable[[Feature], object]
# validate_fn(feature) -> bool (deploy to box 2 + run bound tests; True = all green)
ValidateFn = Callable[[Feature], bool]


@dataclass
class BuildResult:
    ok: bool
    stage: str                  # serialized | implemented | validated | merged | failed:<stage>
    feature: Feature | None = None
    release_sha: str | None = None
    detail: str = ""


def run_build(wm: WorkspaceManager, spec_record: dict, *, implement_fn: ImplementFn,
              validate_fn: ValidateFn, log=lambda *a: None) -> BuildResult:
    """validate_fn(feature) -> bool encapsulates deploy-to-box-2 + run the bound tests
    there (local stand-in or a real remote box 2 — see local_validate / remote_validate)."""
    f = wm.start_feature(spec_record["id"])
    try:
        # serialize the approved spec into the branch (the `serialize` node)
        wm.serialize_spec(f, spec_record)
        wm.commit(f, f"spec: {spec_record['id']}")
        log(f"  serialized {spec_record['id']} on {f.branch}")

        # implement: the agent writes code into the isolated worktree
        impl = implement_fn(f)
        if not getattr(impl, "ok", False):
            return BuildResult(False, "failed:implement", f, detail=getattr(impl, "error", ""))
        if wm.is_dirty(f):
            wm.commit(f, f"implement {spec_record['id']}")
        log("  implemented + committed")

        # deploy to box 2 + validate the bound tests there (box 1 never validates itself)
        if not validate_fn(f):
            return BuildResult(False, "failed:validate", f, detail="bound tests not green")
        log("  validated on box 2")

        # green -> merge feature into release (per-change cycle ends here)
        sha = wm.merge_to_release(f)
        wm.finish_feature(f)
        log(f"  merged -> release @ {sha[:8]}")
        return BuildResult(True, "merged", f, release_sha=sha)
    except Exception as e:
        return BuildResult(False, "failed:error", f, detail=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Real adapters (used once box 2 + a working repo exist; needs Claude for implement)
# --------------------------------------------------------------------------- #
def implement_with_agent(work_item: dict, spec_record: dict, *, model: str,
                         skills_dir: str = ".claude/skills", ledger=None,
                         monthly_limit_usd: float | None = None):
    """Return an implement_fn that runs the `implement` agent (tool-use, writes ON)
    rooted at the feature worktree, THROUGH a Runner so its cost is recorded to the
    shared ledger and the monthly kill-switch applies."""
    from apps.evolve.agents.tooluse import ToolUseBackend
    from apps.evolve.agents.runner import Runner, FakeBackend
    from apps.evolve.agents.registry import ROSTER

    def _impl(feature: Feature):
        tb = ToolUseBackend(repo_root=feature.path, skills_dir=skills_dir,
                            allow_writes=True, max_turns=40)
        runner = Runner(FakeBackend({}), dict(ROSTER), tool_backend=tb,
                        tiers={"fast": model, "smart": model, "deep": model},
                        ledger=ledger, monthly_limit_usd=monthly_limit_usd)
        return runner.run("implement", {"work_item": work_item, "spec": spec_record},
                          instance_id=spec_record.get("id"))
    return _impl


def local_validate(wm: WorkspaceManager, box2_dir: str,
                   test_path: str = "tests/evolve") -> ValidateFn:
    """Stage-1 stand-in: deploy to a LOCAL box-2 clone on this machine and run the
    bound unit tests there."""
    def _val(feature: Feature) -> bool:
        wm.box2_deploy(feature, box2_dir)
        r = subprocess.run(["python3", "-m", "unittest", "discover", "-s", test_path],
                           cwd=box2_dir, capture_output=True, text=True, timeout=300)
        return r.returncode == 0
    return _val


class RemoteBox2:
    """Drive a real box-2 host over ssh (box 1 -> box 2). Box 2's git origin is box 1,
    so it fetches feature/`release` branches straight from the brain."""

    def __init__(self, host: str, repo_path: str, *, python: str = ".venv/bin/python"):
        self.host, self.repo, self.python = host, repo_path, python

    def _ssh(self, remote_cmd: str):
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
             self.host, f"cd {shlex.quote(self.repo)} && {remote_cmd}"],
            capture_output=True, text=True, timeout=600)

    def deploy(self, branch: str) -> None:
        b = shlex.quote(branch)
        r = self._ssh(f"git fetch -q origin && git checkout -q -B {b} origin/{b}")
        if r.returncode:
            raise RuntimeError(f"box2 deploy failed: {r.stderr.strip()}")

    def reset(self, release: str = "release") -> None:
        self._ssh(f"git fetch -q origin && git checkout -q -B {release} origin/{release} "
                  f"&& git reset -q --hard origin/{release} && git clean -fdq")

    def run_tests(self, test_path: str = "tests/evolve") -> tuple[bool, str]:
        r = self._ssh(f"{self.python} -m unittest discover -s {shlex.quote(test_path)}")
        return r.returncode == 0, (r.stdout + r.stderr)[-2000:]


def remote_validate(box2: RemoteBox2, *, release: str = "release",
                    test_path: str = "tests/evolve", log=lambda *a: None) -> ValidateFn:
    """The real validate: deploy the feature branch to box 2, run its bound tests
    there, then reset box 2 to a clean `release` baseline."""
    def _val(feature: Feature) -> bool:
        box2.deploy(feature.branch)
        ok, out = box2.run_tests(test_path)
        log(f"  box2 tests {'green' if ok else 'RED'}: {out.strip().splitlines()[-1] if out.strip() else ''}")
        box2.reset(release)
        return ok
    return _val
