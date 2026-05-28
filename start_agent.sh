#!/usr/bin/env bash
# =============================================================================
# Skipperbot Agent — native start script (Linux / macOS)
# =============================================================================
# Does the same "rebuild web bundle if apps/ changed" check that the Docker
# entrypoint does, so the user-facing install-an-app flow is the same on
# both paths: clone an app into apps/<id>/, restart the agent, done.
#
# Designed to be run two ways:
#   1. Interactively:  ./start_agent.sh           (no restart loop; Ctrl+C to stop)
#   2. Under systemd:  the unit file calls this. systemd handles restart.
#
# Exit codes (consumed by systemd Restart= policy):
#   0   = clean shutdown, do not restart
#   42  = graceful restart requested via POST /api/admin/restart
#   *   = crash, restart
#
# For Windows native: use start_agent.ps1 instead.

set -e

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_ROOT"

APPS_DIR="$APP_ROOT/apps"
WEB_DIR="$APP_ROOT/web"
DIST_DIR="$WEB_DIR/dist"
STAMP="$DIST_DIR/.last-build-stamp"

# Pick the Python interpreter. Prefer the project's venv if it exists.
if [ -x "$APP_ROOT/.venv/bin/python" ]; then
    PYTHON="$APP_ROOT/.venv/bin/python"
elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON="$(command -v python3.12)"
else
    PYTHON="$(command -v python3)"
fi

if [ ! -f "$APP_ROOT/.env" ]; then
    echo "ERROR: $APP_ROOT/.env not found." >&2
    echo "       Copy .env.example to .env and fill in SKIPPERBOT_DB_DSN and OPENAI_API_KEY." >&2
    echo "       See docs/01-base-platform-setup.md step 8." >&2
    exit 1
fi

log() {
    echo "[$(date '+%F %T')] $*"
}

# ---------------------------------------------------------------------------
# Decide whether to rebuild the web bundle.
# Rebuild if: dist/ is empty, stamp missing, or any apps/*/ui/ file is newer.
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
    if [ ! -f "$WEB_DIR/package.json" ]; then
        log "WARNING: no $WEB_DIR/package.json; cannot rebuild UI. Starting agent anyway."
    else
        log "building web bundle (npm run build) ..."
        if (cd "$WEB_DIR" && npm run build); then
            mkdir -p "$DIST_DIR"
            touch "$STAMP"
            log "web build OK"
        else
            log "ERROR: web build failed. Starting agent with stale dist/." >&2
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Start the agent.
# ---------------------------------------------------------------------------

export PYTHONUTF8=1

log "starting agent on :8000 with $($PYTHON --version)"
exec "$PYTHON" "$APP_ROOT/agent.py"
