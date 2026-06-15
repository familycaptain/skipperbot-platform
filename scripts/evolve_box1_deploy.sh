#!/usr/bin/env bash
# Safe box-1 (the Evolve brain) deploy.
#
# Box 1's HOME branch is `release` = origin/main (the engine + published code) PLUS the
# SDLC feature merges that have landed but are not yet published to main. The engine runs
# from this checkout, the spec-phase read tools ground on it, and feature worktrees are cut
# from it.
#
# So a deploy must UPDATE main and then FOLD it into release — never `git reset --hard
# origin/main` while on release, which silently drops the merged-but-unpublished features.
# (That bit us once: it detached a merged weather fix off release.)
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch origin
git checkout main
git reset --hard origin/main          # main mirrors the shared engine source
git checkout release
git merge --no-edit main              # release = main + local (unpublished) feature merges
echo "deployed: release = origin/main + local feature merges"
git log --oneline -4
