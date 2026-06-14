"""Variance detection (EVOLVE.md §3/§4; spec evolve.cfs-store.variance-detect).

A spec is *in variance* when the code doesn't (provably) satisfy it. Reasons:

  untested      — the spec has no bound test (can't be mechanically satisfied)
  missing-impl  — an `implements` path doesn't exist on disk
  drifted       — an `implements` file changed vs the recorded baseline checksum
  test-failing  — a bound test is red (requires a test runner — box-2 territory)

The first two are fully deterministic and computed here. `drifted` needs a baseline
checksum map (recorded at last reconcile). `test-failing` needs an injected test
runner (the deterministic Playwright/unit runner lives on box 2); both are optional
dependencies so this module stays pure and testable standalone.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Callable

from apps.evolve.schema import Record

UNTESTED = "untested"
MISSING_IMPL = "missing-impl"
DRIFTED = "drifted"
TEST_FAILING = "test-failing"

# A test runner takes a spec's bound tests and returns the failing ones (empty = green).
TestRunner = Callable[[Record], list[dict]]


@dataclass
class Variance:
    spec_id: str
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.spec_id}: {self.reason}" + (f" ({self.detail})" if self.detail else "")


def file_checksum(repo_root: str, relpath: str) -> str | None:
    path = os.path.join(repo_root, relpath)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def detect(records: list[Record], *, repo_root: str,
           baselines: dict[str, dict] | None = None,
           test_runner: TestRunner | None = None) -> list[Variance]:
    """Compute variances across the spec records.

    baselines: {spec_id: {relpath: checksum}} recorded at last reconcile (for drift).
    test_runner: optional; if given, red tests become TEST_FAILING variances.
    """
    baselines = baselines or {}
    out: list[Variance] = []
    for r in records:
        if r.kind != "specification":
            continue
        if not r.tests:
            out.append(Variance(r.id, UNTESTED, "no bound tests"))
        for rel in r.implements:
            cur = file_checksum(repo_root, rel)
            if cur is None:
                out.append(Variance(r.id, MISSING_IMPL, rel))
                continue
            base = (baselines.get(r.id) or {}).get(rel)
            if base is not None and base != cur:
                out.append(Variance(r.id, DRIFTED, rel))
        if test_runner is not None:
            for failing in test_runner(r):
                out.append(Variance(r.id, TEST_FAILING, str(failing)))
    return out


def baseline_for(record: Record, *, repo_root: str) -> dict[str, str]:
    """Snapshot the current checksums of a spec's implements files (call at reconcile)."""
    snap = {}
    for rel in record.implements:
        cs = file_checksum(repo_root, rel)
        if cs is not None:
            snap[rel] = cs
    return snap


if __name__ == "__main__":
    import sys
    from apps.evolve import schema
    root = sys.argv[1] if len(sys.argv) > 1 else "specs/evolve"
    recs, _ = schema.load_and_validate(root, repo_root=os.getcwd(),
                                       capability=os.path.basename(root.rstrip("/")))
    vs = detect(recs, repo_root=os.getcwd())
    print(f"{len(vs)} variances:")
    for v in vs:
        print("  " + str(v))
