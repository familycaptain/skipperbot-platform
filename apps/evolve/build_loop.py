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

from dataclasses import dataclass
from typing import Callable

from apps.evolve.workspace import WorkspaceManager, Feature

# implement_fn(feature) -> object with .ok (writes code into feature.path)
ImplementFn = Callable[[Feature], object]
# validate_fn(box2_dir) -> bool (True = all bound tests green)
ValidateFn = Callable[[str], bool]


@dataclass
class BuildResult:
    ok: bool
    stage: str                  # serialized | implemented | validated | merged | failed:<stage>
    feature: Feature | None = None
    release_sha: str | None = None
    detail: str = ""


def run_build(wm: WorkspaceManager, spec_record: dict, *, implement_fn: ImplementFn,
              validate_fn: ValidateFn, box2_dir: str, log=lambda *a: None) -> BuildResult:
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

        # deploy to box 2 and validate the bound tests there
        wm.box2_deploy(f, box2_dir)
        if not validate_fn(box2_dir):
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
                         skills_dir: str = ".claude/skills"):
    """Return an implement_fn that runs the `implement` agent (tool-use, writes ON)
    rooted at the feature worktree."""
    from apps.evolve.agents.tooluse import ToolUseBackend
    from apps.evolve.agents.registry import ROSTER

    def _impl(feature: Feature):
        backend = ToolUseBackend(repo_root=feature.path, skills_dir=skills_dir,
                                 allow_writes=True, max_turns=20)
        spec = ROSTER["implement"]
        return backend.run(spec, {"work_item": work_item, "spec": spec_record},
                           None, model, system=spec.resolved_prompt())
    return _impl


def validate_with_tests(test_path: str = "tests/evolve") -> ValidateFn:
    """Return a validate_fn that runs the bound unit tests on box 2 (deterministic
    half). Full Playwright/agentic validation is added once box 2 runs the app."""
    import subprocess

    def _val(box2_dir: str) -> bool:
        r = subprocess.run(["python3", "-m", "unittest", "discover", "-s", test_path],
                           cwd=box2_dir, capture_output=True, text=True, timeout=300)
        return r.returncode == 0
    return _val
