#!/usr/bin/env bash
# =============================================================================
# Skipperbot agent container entrypoint
# =============================================================================
# Runs every time the container starts. Decides whether the web bundle needs
# to be rebuilt (because the user installed/removed an app on the host since
# the last build) and exec's the agent.

set -euo pipefail

APP_ROOT=/app
APPS_DIR="$APP_ROOT/apps"
WEB_DIR="$APP_ROOT/web"
DIST_DIR="$WEB_DIR/dist"
STAMP="$DIST_DIR/.last-build-stamp"

log() {
    echo "[entrypoint] $*"
}

# ---------------------------------------------------------------------------
# 1. Decide whether to rebuild the web bundle.
# Rebuild if:
#   - dist/ doesn't exist or is empty
#   - any apps/<id>/ui/ file is newer than the stamp
#   - the stamp itself is missing
# ---------------------------------------------------------------------------

needs_rebuild=false

if [ ! -d "$DIST_DIR" ] || [ -z "$(ls -A "$DIST_DIR" 2>/dev/null)" ]; then
    log "web/dist is empty or missing; rebuild required"
    needs_rebuild=true
elif [ ! -f "$STAMP" ]; then
    log "build stamp missing; rebuild required"
    needs_rebuild=true
elif [ -d "$APPS_DIR" ] && find "$APPS_DIR" -path '*/ui/*' -newer "$STAMP" -print -quit 2>/dev/null | grep -q .; then
    log "detected app UI changes since last build; rebuild required"
    needs_rebuild=true
fi

if [ "$needs_rebuild" = true ]; then
    log "running 'npm run build' in $WEB_DIR ..."
    cd "$WEB_DIR"
    if ! npm run build; then
        log "ERROR: web build failed. The agent will start but the desktop UI"
        log "       may be stale or incomplete. Check the build output above."
    else
        mkdir -p "$DIST_DIR"
        touch "$STAMP"
        log "web build complete; stamp updated"
    fi
    cd "$APP_ROOT"
fi

# ---------------------------------------------------------------------------
# 2. Exec the agent (replaces the shell so SIGTERM reaches Python).
# ---------------------------------------------------------------------------

log "starting agent"
exec python agent.py
