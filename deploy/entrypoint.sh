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

# Build cause priority — first hit wins.
if [ ! -d "$DIST_DIR" ] || [ -z "$(ls -A "$DIST_DIR" 2>/dev/null)" ]; then
    log "web/dist is empty or missing; rebuild required"
    needs_rebuild=true
elif [ ! -f "$STAMP" ]; then
    log "build stamp missing; rebuild required"
    needs_rebuild=true
elif [ -d "$APPS_DIR" ] && find "$APPS_DIR" -path '*/ui/*' -newer "$STAMP" -print -quit 2>/dev/null | grep -q .; then
    log "detected app UI changes since last build; rebuild required"
    needs_rebuild=true
elif [ -d "$WEB_DIR/src" ] && find "$WEB_DIR/src" -type f -newer "$STAMP" -print -quit 2>/dev/null | grep -q .; then
    # Platform-side React code changed (App.jsx, components/, pages/, hooks/, etc).
    # Without this check, `git pull` of the platform repo could land a new
    # `web/src/` without ever triggering a rebuild, leaving the host's
    # bind-mounted web/dist serving stale JS.
    log "detected web/src changes since last build; rebuild required"
    needs_rebuild=true
elif [ -f "$WEB_DIR/package.json" ] && [ "$WEB_DIR/package.json" -nt "$STAMP" ]; then
    log "web/package.json newer than last build; rebuild required"
    needs_rebuild=true
elif [ -f "$WEB_DIR/vite.config.js" ] && [ "$WEB_DIR/vite.config.js" -nt "$STAMP" ]; then
    log "web/vite.config.js newer than last build; rebuild required"
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
