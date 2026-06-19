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

# Brain dependencies — make a deploy self-sufficient: a pull that brings in code needing a new
# dep installs it here, no separate manual pip step. SCOPED to the brain's needs
# (apps/evolve/requirements-spec-index.txt), NOT the full base requirements.txt: box 1 is
# deliberately lean (no torch, no full platform stack), and base would drag in heavy deps it
# never runs. Non-fatal — if the install fails the loop still runs (Phase-2 spec retrieval just
# degrades to the Phase-1 capability-scoped read).
PYBIN="./.venv/bin/python"; [ -x "$PYBIN" ] || PYBIN="python3"
REQ="apps/evolve/requirements-spec-index.txt"
if [ -f "$REQ" ]; then
    echo "Installing brain dependencies ($REQ)…"
    "$PYBIN" -m pip install -q -r "$REQ" \
        || echo "WARN: brain dependency install failed — Phase-2 spec retrieval degrades to Phase-1; run by hand: $PYBIN -m pip install -r $REQ"
fi

git push origin release || true       # republish the reconciled release (no-op if read-only)
echo "deployed: release synced with origin/release"
git log --oneline -4
