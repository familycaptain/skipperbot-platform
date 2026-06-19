"""Spec index — lets the Evolve spec phase SEE the existing C/F/S corpus instead of
re-deriving it from code, scoped + bounded so it scales to thousands of specs.

Two layers:
- **Phase 1 (here): `capability_specs(cap)`** — read ONE app's co-located tree
  (`apps/<cap>/specs`, or `specs/platform`), returned as a bounded one-line-per-record
  summary. The spec phase reads the *target* capability's tree (always small — one app),
  so design/spec-author author with siblings in view: extend-vs-new, placement,
  intra-app dedup, consistent granularity. Naturally bounded no matter how big the
  corpus gets.
- **Phase 2 (later): a local embedding index** for triage's *cross-corpus* dedup
  (top-K nearest specs across all apps) — the only part that can't be bounded by
  structure. Kept out of this module's import path / deps until built.

Pure stdlib + PyYAML (via schema). No new dependencies; safe to import anywhere.
"""
from __future__ import annotations

import os
import sys

from apps.evolve import schema
from apps.evolve.workspace import specs_root_for

# One-line behavior cap per record — keep the injected payload bounded (a whole app's
# tree is dozens of records; this keeps even a large app well within a sane budget).
_BEHAVIOR_CHARS = 160


def capability_specs(cap: str, *, repo_root: str = ".") -> list[dict]:
    """Existing C/F/S records for one capability as a bounded summary list:
    ``[{id, kind, title, behavior}]`` (behavior trimmed to one line). Empty if the
    capability has no tree yet (a brand-new app). Reads the co-located tree at
    ``apps/<cap>/specs`` (``specs/platform`` for the platform capability)."""
    if not cap:
        return []
    root = os.path.join(repo_root, specs_root_for(cap))
    if not os.path.isdir(root):
        return []
    out: list[dict] = []
    for path in schema.scan_paths(root):
        try:
            rec = schema.parse_file(path)
        except Exception:
            continue
        beh = (rec.behavior or rec.title or "").strip().replace("\n", " ")
        if len(beh) > _BEHAVIOR_CHARS:
            beh = beh[: _BEHAVIOR_CHARS - 1] + "…"
        out.append({"id": rec.id, "kind": rec.kind, "title": rec.title, "behavior": beh})
    out.sort(key=lambda r: r["id"])
    return out


def format_capability_specs(cap: str, *, repo_root: str = ".") -> str:
    """Human/agent-readable rendering of a capability's existing tree (for the spec phase)."""
    recs = capability_specs(cap, repo_root=repo_root)
    if not recs:
        return (f"(no existing specs for capability '{cap}' — apps/{cap}/specs is empty or "
                f"absent; this is a new/unspecified capability)")
    lines = [f"Existing C/F/S for '{cap}' ({len(recs)} records) — EXTEND/PLACE within these, "
             f"do not duplicate an existing feature or spec:"]
    for r in recs:
        lines.append(f"  [{r['kind'][:4]}] {r['id']} — {r['behavior']}")
    return "\n".join(lines)


if __name__ == "__main__":
    cap = sys.argv[1] if len(sys.argv) > 1 else ""
    if not cap:
        print("usage: python3 -m apps.evolve.spec_index <capability>   "
              "(e.g. weather, reminders, platform)")
        raise SystemExit(2)
    print(format_capability_specs(cap, repo_root=os.getcwd()))
