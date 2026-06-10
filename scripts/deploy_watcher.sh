#!/bin/bash
# Host-side deploy watcher (option B).
#
# The containerized agent can't `git pull` the host repo or run `docker compose`
# on itself. A *deploy* (the deploy_skipper flow / POST /api/admin/deploy) drains
# gracefully and drops a `.deploy_pending` sentinel in the repo root (bind-mounted
# into the container at /app). This script — running on the HOST — watches for
# that sentinel and performs the pull + rebuild + recycle. It mirrors
# `skipper update`: `git pull` then `docker compose up -d --build`, so changes to
# requirements.txt / Dockerfile take effect, not just bind-mounted code.
#
# Note: this is the *deploy* path, deliberately heavier than a restart. The UI
# "restart" button hits /api/admin/restart, which just bounces the agent on the
# current code (no sentinel, so this watcher does nothing).
#
# It only matters for DOCKER runs (native installs restart themselves). The
# script itself is portable — bash + git + `docker compose` — so it runs on any
# host (Linux, macOS, WSL, Git-Bash on Windows). How you keep it running differs
# by OS; pick one:
#   - any OS, quick:  nohup scripts/deploy_watcher.sh >> /tmp/skipper-deploy-watcher.log 2>&1 &
#   - Linux/systemd:  deploy/skipperbot-deploy-watcher.service.example
#                     (or let `skipper` install it for you)
#   - macOS:          a launchd agent;  Windows: a Scheduled Task / NSSM
# See docs/04-running-as-a-service.md.
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
        echo "[deploy_watcher] $(date '+%F %T') deploy requested — pull + rebuild + recycle"
        rm -f "$SENTINEL"   # remove first so the recycled agent doesn't re-trigger
        git pull \
            && docker compose down \
            && docker compose up -d --build \
            && echo "[deploy_watcher] $(date '+%F %T') deploy complete" \
            || echo "[deploy_watcher] $(date '+%F %T') deploy FAILED — see output above"
    fi
    sleep "$INTERVAL"
done
