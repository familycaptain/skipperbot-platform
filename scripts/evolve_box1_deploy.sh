#!/usr/bin/env bash
# Safe box-1 (the Evolve brain) deploy — RELEASE-FIRST model.
#
# `release` is the SHARED staging branch on origin: engine/platform changes are pushed there
# (by the dev/operator) and agent feature merges are pushed there (by box 1's push_release()).
# box 1 RUNS `release`, grounds its agents on it, and cuts feature worktrees from it.
#
# `main` is the world. It is touched ONLY by the operator's `release -> main` promotion —
# NEVER by box 1 (the .git/hooks/pre-push hook hard-refuses any push to main).
#
# Deploy = reconcile box 1's `release` with `origin/release` by MERGE (never reset — that
# would drop box 1's locally-merged-but-not-yet-pushed feature work), then republish.
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch origin
git checkout release
git merge --no-edit origin/release    # pull shared release (engine + others' pushes); keep local merges
git push origin release || true       # republish the reconciled release (no-op if read-only)
echo "deployed: release synced with origin/release"
git log --oneline -4
