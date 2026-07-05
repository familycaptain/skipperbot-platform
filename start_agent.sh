#!/usr/bin/env bash
# =============================================================================
# Skipperbot Agent — native start script (Linux / macOS)
# =============================================================================
# Rebuilds the web bundle on every start (cheap — ~5–15s with cached
# node_modules) so the install-an-app or git-pull-the-platform flow never
# leaves stale UI behind.
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

WEB_DIR="$APP_ROOT/web"

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
    echo "       Copy .env.example to .env and fill in SKIPPERBOT_DB_DSN (your LLM provider + key are set later in the web UI)." >&2
    echo "       See docs/01-base-platform-setup.md step 8." >&2
    exit 1
fi

log() {
    echo "[$(date '+%F %T')] $*"
}

# ---------------------------------------------------------------------------
# Always rebuild the web bundle. Mirrors deploy/entrypoint.sh — the cost
# (~5–15s with cached node_modules) is small next to DB init + per-app
# loader, and it eliminates an entire class of "stale UI after git pull"
# bugs that conditional-rebuild logic kept stumbling into.
# ---------------------------------------------------------------------------

if [ ! -f "$WEB_DIR/package.json" ]; then
    log "WARNING: no $WEB_DIR/package.json; skipping web build."
else
    # Keep node_modules in sync with the lock file (installs new deps after a
    # git pull that added one — e.g. three.js). Fast no-op when unchanged.
    (
        cd "$WEB_DIR" || exit 0
        if [ -f package-lock.json ]; then LOCK=package-lock.json; else LOCK=package.json; fi
        STAMP="node_modules/.skipper-deps-stamp"
        SIG="$(sha1sum "$LOCK" 2>/dev/null | cut -d' ' -f1)"
        if [ ! -d node_modules ] || [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$SIG" ]; then
            log "web dependencies changed (or first run) — installing ..."
            if [ -f package-lock.json ]; then npm ci; else npm install; fi && echo "$SIG" > "$STAMP"
        fi
    )
    # Install packaged-app frontend deps (mirrors deploy/entrypoint.sh). Apps
    # declare extra npm deps in apps/<id>/ui/package.json; this installs the
    # union into web/node_modules so the vite build below can resolve them
    # (e.g. an app that needs three.js). Runs AFTER the base npm ci above (which
    # would prune these --no-save installs) and BEFORE the build. Without it,
    # native (non-Docker) installs couldn't build any app needing extra deps.
    if [ -f "$WEB_DIR/packaged-app-deps.mjs" ]; then
        if ! (cd "$WEB_DIR" && node packaged-app-deps.mjs --install); then
            log "WARNING: packaged-app dep install failed; build may fail for apps needing extra deps." >&2
        fi
    fi
    log "building web bundle (npm run build) ..."
    if (cd "$WEB_DIR" && npm run build); then
        log "web build OK"
    else
        log "ERROR: web build failed. Starting agent with stale dist/." >&2
    fi
fi

# ---------------------------------------------------------------------------
# Install packaged-app Python dependencies (mirrors deploy/entrypoint.sh §0c).
# Optional/community apps cloned into apps/<id>/ may import Python packages the
# platform's requirements.txt doesn't bundle (e.g. newsletter -> yfinance,
# scriptures -> pymupdf). Each declares them in apps/<id>/requirements.txt;
# install the union so a cloned app's imports resolve at runtime — no manual
# pip step. Fast no-op when unchanged via a checksum stamp beside site-packages.
# ---------------------------------------------------------------------------
(
    shopt -s nullglob
    reqs=( "$APP_ROOT"/apps/*/requirements.txt )
    [ "${#reqs[@]}" -eq 0 ] && exit 0
    SITE="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("purelib"))' 2>/dev/null || echo /tmp)"
    STAMP="$SITE/.skipper-app-pydeps-stamp"
    SIG="$(cat "${reqs[@]}" 2>/dev/null | sha1sum | cut -d' ' -f1)"
    if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$SIG" ]; then
        log "installing packaged-app Python dependencies (${#reqs[@]} file(s)) ..."
        args=(); for r in "${reqs[@]}"; do args+=( -r "$r" ); done
        if "$PYTHON" -m pip install "${args[@]}"; then
            echo "$SIG" > "$STAMP"
        else
            log "WARNING: packaged-app Python dep install failed; apps needing extra packages may error." >&2
        fi
    fi
) || true

# The agent mounts /assets from web/dist/assets and exits non-zero if it's
# missing. Fail fast with a clear message rather than a confusing traceback
# (and, under systemd, an immediate restart loop).
if [ ! -d "$WEB_DIR/dist/assets" ]; then
    log "FATAL: $WEB_DIR/dist/assets is missing — the web UI build produced no output." >&2
    log "Fix the build error shown above, then re-run. Common causes: web deps not" >&2
    log "installed (run 'npm ci' in web/), or a packaged-app dependency failed to install." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Initialise the database (idempotent — fast no-op after first run).
# Runs the platform baseline + every app's pending migration so the agent
# can boot cleanly on a fresh install. Set SKIPPERBOT_SKIP_INIT_DB=1 in
# the environment to skip (e.g. if you're running init_db.py by hand from
# a CI step).
# ---------------------------------------------------------------------------

if [ "${SKIPPERBOT_SKIP_INIT_DB:-0}" != "1" ]; then
    log "running scripts/init_db.py ..."
    if ! "$PYTHON" "$APP_ROOT/scripts/init_db.py"; then
        log "ERROR: init_db.py failed; not starting the agent." >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Start the agent.
# ---------------------------------------------------------------------------

export PYTHONUTF8=1

PORT="$(grep -E '^[[:space:]]*SKIPPERBOT_PORT[[:space:]]*=' "$APP_ROOT/.env" | head -1 | cut -d= -f2- | tr -d '[:space:]')"
[ -z "$PORT" ] && PORT="8000"
log "starting agent on :$PORT with $($PYTHON --version)"
exec "$PYTHON" "$APP_ROOT/agent.py"
