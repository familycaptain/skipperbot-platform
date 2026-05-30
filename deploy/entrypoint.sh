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
# 0. Keep web/node_modules in sync with package-lock.json.
# ---------------------------------------------------------------------------
# docker-compose masks /app/web/node_modules with a *persistent anonymous
# volume* (so the host bind-mount of the repo doesn't shadow the image's
# installed deps). That volume is populated once and survives image rebuilds,
# so when package-lock.json gains a new dependency (e.g. three.js for the
# arcade 3D game) the volume goes stale and the build fails with
# "Could not load .../node_modules/<pkg>". We self-heal: when the lock file's
# checksum changes (tracked by a stamp inside node_modules), reinstall.
# On unchanged deps this is a fast checksum compare and a no-op.
# ---------------------------------------------------------------------------

# Body runs in a subshell so the `cd` never leaks into this script's
# working directory (it must stay $APP_ROOT for the agent exec below).
_deps_sync() (
    cd "$WEB_DIR" || exit 0
    if [ -f package-lock.json ]; then lock=package-lock.json; else lock=package.json; fi
    stamp="node_modules/.skipper-deps-stamp"
    sig="$(sha1sum "$lock" 2>/dev/null | cut -d' ' -f1)"
    if [ -d node_modules ] && [ -f "$stamp" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$sig" ]; then
        exit 0   # deps already match the lock file
    fi
    log "web dependencies changed (or first run) — installing (this can take a few minutes on a Pi) ..."
    if [ -f package-lock.json ]; then
        npm ci && echo "$sig" > "$stamp" && log "npm ci complete" || log "WARNING: npm ci failed; the build below may fail until deps install."
    else
        npm install && echo "$sig" > "$stamp" && log "npm install complete" || log "WARNING: npm install failed."
    fi
)
_deps_sync || true

# ---------------------------------------------------------------------------
# 0b. Install packaged-app frontend dependencies.
# ---------------------------------------------------------------------------
# Optional/community apps cloned into apps/<id>/ may import npm packages the
# base platform doesn't bundle. Each declares them in apps/<id>/ui/package.json;
# this collector unions them and installs into web/node_modules (--no-save, so
# the platform's package.json is never mutated by an app). Vite picks up the
# same set as resolver aliases. Net effect: `git clone <app> apps/<id>` + restart
# just works — no edit to any platform file. Runs after the base npm ci above
# (npm ci would otherwise prune these no-save installs) and before the build.
# ---------------------------------------------------------------------------
log "collecting packaged-app frontend dependencies ..."
if ! ( cd "$WEB_DIR" && node packaged-app-deps.mjs --install ); then
    log "WARNING: packaged-app dependency install failed; the build below may"
    log "         fail for apps that need extra npm packages."
fi

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
cd "$APP_ROOT"
exec python "$APP_ROOT/agent.py"
