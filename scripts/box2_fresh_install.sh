#!/usr/bin/env bash
#
# box2_fresh_install.sh — tear box2's Skipper down to a CLEAN install and bring it back up
# freshly seeded, optionally deploying a branch first. box2 is the expendable Evolve test box.
#
# A "true fresh install": drop the named DATA volumes (db/uploads/logs/backups) so the DB is
# empty, then `docker compose up` — the entrypoint re-runs scripts/init_db.py (baseline +
# migrations + seed). The anonymous web-build volumes are kept, so there's no slow UI rebuild.
# After this, no non-bot user exists, so POST /api/onboarding/create-user will seed onboarding.
#
#   ./box2_fresh_install.sh                  # fresh-install whatever branch is checked out
#   ./box2_fresh_install.sh feature/ev-19    # deploy this branch first, then fresh-install
#
set -euo pipefail
cd ~/repos/skipperbot-platform
BRANCH="${1:-}"
PROJECT="skipperbot-platform"
DATA_VOLUMES=(skipper-db skipper-uploads skipper-logs skipper-backups)

if [ -n "$BRANCH" ]; then
  echo "==> deploy branch: $BRANCH"
  git fetch origin --prune
  git checkout -B "$BRANCH" "origin/$BRANCH"
  git --no-pager log --oneline -1
fi

echo "==> stop stack (keeps web-build anon volumes — no UI rebuild)"
docker compose down

echo "==> drop data volumes (TRUE fresh install)"
for v in "${DATA_VOLUMES[@]}"; do
  full="${PROJECT}_${v}"
  if docker volume inspect "$full" >/dev/null 2>&1; then
    docker volume rm "$full" >/dev/null && echo "    dropped $full"
  fi
done

echo "==> up fresh — entrypoint re-runs init_db (migrations + seed)"
docker compose up -d

echo "==> wait for API (init_db seeds on boot)"
ok=""
for i in $(seq 1 120); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null || echo 000)
  if [ "$code" = "200" ]; then ok="yes"; echo "    API up (200) after ~$((i*2))s"; break; fi
  sleep 2
done
[ -z "$ok" ] && { echo "ERROR: API never came up. recent agent logs:"; docker compose logs --tail 40 agent; exit 1; }

echo "==> verify CLEAN (no non-bot users => onboarding not yet done)"
docker compose exec -T agent python -c "
from data_layer.users import get_all_users
us = get_all_users()
nonbot = [u['name'] for u in us if 'bot' not in (u.get('role') or '')]
print('all users:', [u['name'] for u in us])
print('non-bot users:', nonbot)
print('FRESH_OK' if not nonbot else 'NOT_FRESH (onboarding already done)')
" 2>&1 | tail -6
echo "DONE: box2 is a fresh Skipper install on branch $(git branch --show-current)"
