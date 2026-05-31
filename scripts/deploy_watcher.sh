#!/bin/bash
# Host-side deploy watcher (option B).
#
# The containerized agent can't `git pull` the host repo or run `docker compose`
# on itself, so the "deploy + restart" button / API instead drains gracefully
# and drops a `.deploy_pending` sentinel in the repo root (bind-mounted into the
# container at /app). This script — running on the HOST — watches for that
# sentinel and performs the actual pull + recycle (same as update_server.sh).
#
# Run it once on the Pi, e.g.:
#   nohup scripts/deploy_watcher.sh >> /tmp/skipper-deploy-watcher.log 2>&1 &
# or install the systemd unit: deploy/skipperbot-deploy-watcher.service
#
# Security: keeps the container isolated — it never touches the docker socket.
set -u

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SENTINEL="$APP_ROOT/.deploy_pending"
INTERVAL="${DEPLOY_WATCH_INTERVAL:-5}"

cd "$APP_ROOT" || exit 1
echo "[deploy_watcher] watching $SENTINEL (every ${INTERVAL}s)"

while true; do
    if [ -f "$SENTINEL" ]; then
        echo "[deploy_watcher] $(date '+%F %T') deploy requested — pulling + recycling"
        rm -f "$SENTINEL"   # remove first so the recycled agent doesn't re-trigger
        git pull \
            && docker compose down \
            && docker compose up -d \
            && echo "[deploy_watcher] $(date '+%F %T') deploy complete" \
            || echo "[deploy_watcher] $(date '+%F %T') deploy FAILED — see output above"
    fi
    sleep "$INTERVAL"
done
