"""Git workspace manager — the box-1 / box-2 mechanics (EVOLVE.md §5).

Stage 1: prove the whole feature -> release promotion loop on ONE machine with git
worktrees + a local clone standing in for box 2. The logic here is host-agnostic;
"real box 2" later is just pointing `box2_*` at an ssh remote + a real Postgres
instead of a local clone. Nothing else changes.

Topology (per §5):
  - box-1 repo: holds `main` (what runs) + `release` (staging) + per-feature worktrees.
  - feature work happens in a `git worktree` (an isolated checkout — NOT the running
    code), so an agent can write freely without touching what's live.
  - box-2: a separate clone that checks out the feature branch to validate it; reset
    to `release` between runs.
  - Gate-2 approval merges feature -> release (publish release -> main is the
    operator's separate release gate; not done here).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

# commit identity so this works without any global git config
_ID = ["-c", "user.email=evolve@box1.local", "-c", "user.name=Evolve"]


class GitError(RuntimeError):
    pass


def git(repo: str, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {repo}:\n{r.stderr.strip()}")
    return r.stdout.strip()


def _slug(item_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in item_id)


def spec_relpath(record: dict) -> str:
    """The repo-relative file path a C/F/S record serializes to (mirror of §4 layout)."""
    parts = record["id"].split(".")
    cap = parts[0]
    if record["kind"] == "capability":
        return f"specs/{cap}/_capability.yaml"
    if record["kind"] == "feature":
        return f"specs/{cap}/{parts[1]}/_feature.yaml"
    return f"specs/{cap}/{parts[1]}/{parts[2]}.yaml"


@dataclass
class Feature:
    item_id: str
    branch: str
    path: str           # the worktree checkout (where the agent writes)


class WorkspaceManager:
    def __init__(self, repo_dir: str, *, worktrees_dir: str | None = None,
                 release: str = "release", main: str = "main"):
        self.repo = os.path.abspath(repo_dir)
        self.release = release
        self.main = main
        self.worktrees_dir = worktrees_dir or (self.repo.rstrip("/") + "-wt")
        os.makedirs(self.worktrees_dir, exist_ok=True)

    # --- box 1: feature workspace ----------------------------------------
    def start_feature(self, item_id: str) -> Feature:
        """Cut feature/<id> from `release` into an isolated worktree."""
        slug = _slug(item_id)
        branch = f"feature/{slug}"
        path = os.path.join(self.worktrees_dir, slug)
        git(self.repo, "worktree", "add", "-b", branch, path, self.release)
        return Feature(item_id, branch, path)

    def write_file(self, feature: Feature, relpath: str, content: str) -> str:
        """Write a file inside the feature worktree (bounded to it)."""
        full = os.path.realpath(os.path.join(feature.path, relpath))
        if not full.startswith(os.path.realpath(feature.path)):
            raise GitError("path escapes the worktree")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        return relpath

    def serialize_spec(self, feature: Feature, record: dict) -> str:
        """Serialize a C/F/S record to its file in the worktree (the `serialize` node)."""
        from apps.evolve.store import serialize_record
        return self.write_file(feature, spec_relpath(record), serialize_record(record))

    def commit(self, feature: Feature, message: str) -> str:
        """Stage everything in the worktree and commit on the feature branch."""
        git(feature.path, "add", "-A")
        git(feature.path, *_ID, "commit", "-m", message)
        return git(feature.path, "rev-parse", "HEAD")

    def is_dirty(self, feature: Feature) -> bool:
        return bool(git(feature.path, "status", "--porcelain"))

    def changed_files(self, feature: Feature) -> list[str]:
        """Files this feature's COMMITTED history changes vs the release baseline
        (three-dot: diff against the merge-base). Used to gate on a real change and to
        find the bound tests the validate step must actually run."""
        out = git(feature.path, "diff", "--name-only", f"{self.release}...HEAD", check=False)
        return [ln.strip() for ln in out.splitlines() if ln.strip()]

    # --- box 2: validate the branch in isolation -------------------------
    def box2_deploy(self, feature: Feature, box2_dir: str) -> str:
        """Stand up / update a box-2 clone checked out to the feature branch."""
        if not os.path.exists(os.path.join(box2_dir, ".git")):
            git(os.path.dirname(box2_dir) or ".", "clone", "--quiet", self.repo, box2_dir)
        git(box2_dir, "fetch", "--quiet", "origin")
        git(box2_dir, "checkout", "-B", feature.branch, f"origin/{feature.branch}")
        return box2_dir

    def box2_reset(self, box2_dir: str) -> str:
        """Reset box 2 to a clean `release` baseline (between runs). Fixture reload is a
        separate concern (the box-2 DB) — a no-op hook here in Stage 1."""
        git(box2_dir, "fetch", "--quiet", "origin")
        git(box2_dir, "checkout", "-B", self.release, f"origin/{self.release}")
        git(box2_dir, "reset", "--hard", f"origin/{self.release}")
        git(box2_dir, "clean", "-fd")
        return git(box2_dir, "rev-parse", "HEAD")

    # --- promotion: feature -> release -----------------------------------
    def merge_to_release(self, feature: Feature, message: str | None = None) -> str:
        """Gate-2 approval: merge the feature branch into `release` (per-change cycle
        ends here; release -> main publish is the operator's separate gate)."""
        git(self.repo, "checkout", self.release)
        git(self.repo, *_ID, "merge", "--no-ff", "--no-edit",
            "-m", message or f"merge {feature.branch} -> {self.release}", feature.branch)
        return git(self.repo, "rev-parse", self.release)

    def finish_feature(self, feature: Feature) -> None:
        """Remove the worktree + delete the feature branch (after merge)."""
        git(self.repo, "worktree", "remove", "--force", feature.path, check=False)
        git(self.repo, "branch", "-D", feature.branch, check=False)
