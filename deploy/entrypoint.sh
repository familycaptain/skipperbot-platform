#!/usr/bin/env bash
# =============================================================================
# Skipperbot agent container entrypoint
# =============================================================================
# Runs every time the container starts. Rebuilds the web bundle from source,
# initialises the DB (idempotent), then exec's the agent.

set -euo pipefail

APP_ROOT=/app
WEB_DIR="$APP_ROOT/web"

log() {
    echo "[entrypoint] $*"
}

# ---------------------------------------------------------------------------
# 1. Rebuild the web bundle every start.
# ---------------------------------------------------------------------------
# Rationale: web/dist is NOT bind-mounted from the host (see docker-compose.yml)
# so the container always owns its own dist. Rebuilding on every start removes
# an entire class of bugs around "host's stale dist shadows image's fresh build
# after `git pull && docker compose build agent`" — exactly what happens when
# an operator updates the platform and forgets one of the three steps. The
# rebuild is ~5–15s (node_modules is baked into the image), which is small
# next to the DB init + per-app loader that follow.
# ---------------------------------------------------------------------------

log "running 'npm run build' in $WEB_DIR ..."
if ! ( cd "$WEB_DIR" && npm run build ); then
    log "ERROR: web build failed. The agent will start but the desktop UI"
    log "       may be stale or incomplete. Check the build output above."
else
    log "web build complete"
fi

# ---------------------------------------------------------------------------
# 2. Initialise the database (idempotent — fast no-op after first run).
# Set SKIPPERBOT_SKIP_INIT_DB=1 to skip (e.g. when running migrations
# from a separate job).
# ---------------------------------------------------------------------------

if [ "${SKIPPERBOT_SKIP_INIT_DB:-0}" != "1" ]; then
    log "running scripts/init_db.py ..."
    if ! python "$APP_ROOT/scripts/init_db.py"; then
        log "ERROR: init_db.py failed; not starting the agent." >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 3. Exec the agent (replaces the shell so SIGTERM reaches Python).
# ---------------------------------------------------------------------------

log "starting agent"
exec python agent.py
