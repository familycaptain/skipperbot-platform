#!/usr/bin/env bash
# =============================================================================
# skipper.sh — one-command launcher + first-run setup for the Skipperbot platform
# =============================================================================
# After cloning the repo, run `./scripts/skipper.sh` (or install it onto your PATH
# with `./scripts/skipper.sh install`, then just `skipper`). Behaviour:
#
#   * Every start/setup first ASKS how to run Skipper — Docker or native —
#     and verifies that runtime's prerequisites before doing anything else.
#       - Docker: bundles Postgres + Python + Node in containers (recommended).
#       - Native: runs on the host; you must already have PostgreSQL 18 +
#         pgvector, Python 3.12, and Node 24+ installed. The launcher then
#         installs the project's own deps for you (venv + pip + npm ci).
#   * First run (no usable .env): asks for your OpenAI key and a Postgres
#     password, writes .env, offers to install the deploy-watcher service,
#     then starts Skipper.
#   * Later runs: just starts Skipper.
#
# Think `claude` / `openclaw`: one short command to bring Skipper up.
#
# Subcommands:  setup | start | stop | restart | update | logs | status |
#               install | uninstall | help   (no subcommand = setup-if-needed + start)
# =============================================================================

set -euo pipefail

# --- locate the repo root (works whether run directly or via a PATH symlink) -
_src="${BASH_SOURCE[0]}"
_real="$(readlink -f "$_src" 2>/dev/null || echo "$_src")"
REPO="$(cd "$(dirname "$_real")/.." && pwd)"
cd "$REPO"

ENV_FILE="$REPO/.env"
EXAMPLE_ENV="$REPO/.env.example"
WATCHER_SVC="skipperbot-deploy-watcher"

# --- pretty output -----------------------------------------------------------
_blue=$'\033[34m'; _green=$'\033[32m'; _yellow=$'\033[33m'; _red=$'\033[31m'; _cyan=$'\033[36m'; _dim=$'\033[2m'; _rst=$'\033[0m'
log()  { printf '%s==>%s %s\n' "$_blue" "$_rst" "$*"; }
ok()   { printf '%s✓%s %s\n'  "$_green" "$_rst" "$*"; }
warn() { printf '%s!%s %s\n'  "$_yellow" "$_rst" "$*"; }
die()  { printf '%s✗%s %s\n'  "$_red" "$_rst" "$*" >&2; exit 1; }

confirm() {  # confirm "Question?"  -> 0 if yes
    local reply
    read -r -p "$1 [Y/n] " reply || true
    [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

# --- helpers -----------------------------------------------------------------
has_docker() { command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; }

env_get() {  # env_get KEY -> value (empty if unset/missing)
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true
}

set_env() {  # set_env KEY VALUE — safe literal replace-or-append (handles / & special chars)
    KEY="$1" VAL="$2" ENVF="$ENV_FILE" python3 - <<'PY'
import os, pathlib
key, val = os.environ["KEY"], os.environ["VAL"]
p = pathlib.Path(os.environ["ENVF"])
lines = p.read_text().splitlines() if p.exists() else []
out, found = [], False
for ln in lines:
    if ln.startswith(key + "="):
        out.append(f"{key}={val}"); found = True
    else:
        out.append(ln)
if not found:
    out.append(f"{key}={val}")
p.write_text("\n".join(out) + "\n")
PY
}

needs_setup() {
    [ -f "$ENV_FILE" ] || return 0
    [ -z "$(env_get OPENAI_API_KEY)" ] && return 0
    local pw; pw="$(env_get POSTGRES_PASSWORD)"
    { [ -z "$pw" ] || [ "$pw" = "CHANGE_ME" ]; } && return 0
    return 1
}

# --- runtime selection -------------------------------------------------------
# skipper supports two runtimes:
#   docker — bundles Postgres + Python + Node in containers (recommended)
#   native — runs on the host; YOU must have Postgres/Python/Node installed
# We always ASK which one to use, then verify that runtime's prerequisites
# before doing anything else (so we never get half-way and then fail).
RUNTIME=""

resolve_runtime() {
    [ -n "$RUNTIME" ] && return 0
    echo
    log "How do you want to run Skipper?"
    echo "  [D] Docker — bundles Postgres 18 + pgvector, Python, and Node in containers."
    if has_docker; then
        ok "      Recommended. Docker was detected on this machine."
    else
        warn "      Recommended, but Docker was NOT detected — you'd install Docker first."
    fi
    echo "  [N] Native — run directly on this machine. You must ALREADY have"
    echo "      PostgreSQL 18 + pgvector, Python 3.12, and Node 24+ installed."
    local reply
    read -r -p "Choose D or N (default D): " reply || true
    [ -z "$reply" ] && reply="D"
    case "$reply" in
        [Dd]*) RUNTIME="docker" ;;
        [Nn]*) RUNTIME="native" ;;
        *)     die "Unrecognized choice '$reply'. Run again and enter D (Docker) or N (native)." ;;
    esac
}

# Prerequisite checks come in two phases:
#   Tooling  — Node + Python; checked BEFORE setup (no .env needed), so we
#              never ask for your OpenAI key on a machine that can't run.
#   Database — Postgres reachability; checked AFTER setup, because setup is
#              what asks you for the DB host and writes it into .env.
# For native, the tooling phase auto-installs the project's own deps (venv, pip,
# npm ci) but never the system runtimes (Node/Python/Postgres — those are yours).
ensure_runtime_tooling() {
    resolve_runtime
    if [ "$RUNTIME" = "docker" ]; then require_docker; else require_native_tooling; fi
}

ensure_runtime_database() {
    resolve_runtime
    [ "$RUNTIME" = "native" ] && require_native_database
    # Docker: Postgres runs in the bundled 'db' container, started by
    # 'docker compose up' — nothing to verify on the host.
    return 0
}

require_docker() {
    if ! has_docker; then
        echo
        warn "You chose Docker, but 'docker compose' isn't available on this machine."
        echo "   Install Docker, then re-run this script:"
        echo "     Linux:  https://docs.docker.com/engine/install/   (or: curl -fsSL https://get.docker.com | sudo sh)"
        echo "     macOS:  https://docs.docker.com/desktop/"
        echo "   Verify with:  docker run --rm hello-world"
        echo
        die "Docker not found. Install it, or re-run and choose Native."
    fi
    ok "Docker detected."
}

# Where will the native agent look for Postgres? Mirrors data_layer/dsn.py:
# an explicit SKIPPERBOT_DB_DSN wins; otherwise host/port default to the
# docker-compose 'db' service — which is wrong for a native run.
# Prints: "<host> <port> <fromdsn:0|1>"
native_db_target() {
    local dsn host port fromdsn
    dsn="$(env_get SKIPPERBOT_DB_DSN)"
    if [ -n "$dsn" ]; then
        host="localhost"; port="5432"; fromdsn=1
        [[ "$dsn" =~ host=([^[:space:]]+) ]] && host="${BASH_REMATCH[1]}"
        [[ "$dsn" =~ port=([0-9]+) ]] && port="${BASH_REMATCH[1]}"
        [[ "$dsn" =~ ://[^/@]+@([^:/]+):([0-9]+) ]] && { host="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[2]}"; }
    else
        host="$(env_get DB_HOST)"; [ -z "$host" ] && host="db"
        port="$(env_get DB_PORT)"; [ -z "$port" ] && port="5432"
        fromdsn=0
    fi
    printf '%s %s %s' "$host" "$port" "$fromdsn"
}

tcp_open() {  # tcp_open HOST PORT -> 0 if a TCP connection succeeds
    local host="$1" port="$2"
    if command -v timeout >/dev/null 2>&1; then
        timeout 3 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null
    else
        ( exec 3<>/dev/tcp/"$host"/"$port" ) 2>/dev/null
    fi
}

# Echo a command that runs Python 3.12 (to build the venv with), or nothing.
find_python312() {
    local c
    for c in python3.12 python3 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" --version 2>&1 | grep -q "3\.12"; then
            echo "$c"; return 0
        fi
    done
    return 0
}

# Checks the system runtimes (Node 24+, Python 3.12) — which the user must
# install themselves — and then AUTO-INSTALLS the project's own dependencies
# (creates the venv, pip install, npm ci) when those runtimes are present.
require_native_tooling() {
    log "Native run selected — checking runtimes; project dependencies are installed for you…"
    local problems=()
    local node_ok=0 py_ok=0

    # --- Node.js >= 24 (system runtime; must match web/package.json "engines") ---
    if ! command -v node >/dev/null 2>&1; then
        problems+=("Node.js not found. Install Node.js 24 LTS or newer from https://nodejs.org/ (needed to build the web UI).")
    else
        local nodev major
        nodev="$(node --version 2>/dev/null)"
        major="${nodev#v}"; major="${major%%.*}"
        if ! [[ "$major" =~ ^[0-9]+$ ]] || [ "$major" -lt 24 ]; then
            problems+=("Node.js 24+ required (found $nodev). Update from https://nodejs.org/ or your package manager.")
        else
            ok "Node.js $nodev"; node_ok=1
        fi
    fi

    # --- Python 3.12 venv (auto-created) ---
    # The platform pins 3.12 (pyproject.toml requires-python ==3.12.*); newer
    # versions (3.13/3.14) are unsupported and break the voice companion's deps.
    local venv_py="$REPO/.venv/bin/python"
    if [ -x "$venv_py" ]; then
        local venv_ver; venv_ver="$("$venv_py" --version 2>&1)"
        if [[ "$venv_ver" != *"3.12"* ]]; then
            problems+=("Project requires Python 3.12, but .venv is '$venv_ver' (3.13/3.14 unsupported). Remove it and re-run:  rm -rf .venv")
        else
            ok "Python virtual-env present ($venv_ver)"; py_ok=1
        fi
    else
        local py312; py312="$(find_python312)"
        if [ -z "$py312" ]; then
            problems+=("Python 3.12 not found. Install it (e.g. 'sudo apt install python3.12 python3.12-venv', or 'brew install python@3.12').")
        else
            log "Creating Python 3.12 virtual-env (.venv)…"
            if "$py312" -m venv "$REPO/.venv" 2>/dev/null && [ -x "$venv_py" ]; then
                ok "Created .venv (Python 3.12)"; py_ok=1
            else
                problems+=("Failed to create the Python 3.12 virtual-env. Create it by hand:  python3.12 -m venv .venv")
            fi
        fi
    fi

    # --- Python dependencies (auto-installed into the venv) ---
    if [ "$py_ok" -eq 1 ]; then
        if "$venv_py" -c "import fastapi" >/dev/null 2>&1; then
            ok "Python dependencies installed"
        else
            log "Installing Python dependencies (pip install -r requirements.txt)…"
            if "$venv_py" -m pip install -r "$REPO/requirements.txt"; then
                ok "Python dependencies installed"
            else
                problems+=("Python dependency install failed. Run it by hand:  ./.venv/bin/python -m pip install -r requirements.txt")
            fi
        fi
    fi

    # --- Web UI dependencies (auto npm ci; needed by start_agent.sh's build) ---
    if [ "$node_ok" -eq 1 ]; then
        if [ -d "$REPO/web/node_modules/vite" ]; then
            ok "Web UI dependencies installed"
        elif ! command -v npm >/dev/null 2>&1; then
            problems+=("npm not found on PATH (it ships with Node.js). Reinstall Node 24+, then re-run.")
        else
            log "Installing web UI dependencies (npm ci) — first time can take a minute or two…"
            if ( cd "$REPO/web" && npm ci ) && [ -d "$REPO/web/node_modules/vite" ]; then
                ok "Web UI dependencies installed"
            else
                problems+=("Web UI dependency install (npm ci) failed. Run it by hand:  (cd web && npm ci)")
            fi
        fi
    fi

    if [ "${#problems[@]}" -gt 0 ]; then
        echo
        warn "Native prerequisites are not satisfied:"
        for p in "${problems[@]}"; do printf '   - %s\n' "$p"; done
        echo
        die "Install the missing runtimes above, then re-run 'skipper' (it installs the project dependencies for you). Or choose Docker. Full native guide: docs/01-base-platform-setup.md"
    fi
    ok "Node + Python ready (project dependencies installed)."
}

# Checked AFTER setup, so the host/port reflect what you were asked for and
# .env now contains (setup writes DB_HOST/DB_PORT for a native run). The DB may
# live on THIS machine or on another server on your network — we just verify
# we can reach whatever host you gave.
require_native_database() {
    local target host port fromdsn rest
    target="$(native_db_target)"
    host="${target%% *}"; rest="${target#* }"; port="${rest%% *}"; fromdsn="${rest##* }"
    if [ "$fromdsn" -eq 0 ] && [ "$host" = "db" ]; then
        echo
        die "Postgres host is still 'db' (the Docker service name), which won't work natively. Re-run 'skipper setup' and enter your Postgres host. See docs/01-base-platform-setup.md step 6."
    fi

    local venv_py="$REPO/.venv/bin/python"
    local check="$REPO/scripts/check_db_connection.py"

    if ! { [ -x "$venv_py" ] && [ -f "$check" ]; }; then
        # Fallback: TCP-only reachability (venv not usable for a real check).
        if tcp_open "$host" "$port"; then
            ok "PostgreSQL reachable at $host:$port (TCP only — credentials unverified)"
            return 0
        fi
        echo
        die "Cannot reach PostgreSQL at $host:$port. Start it (or fix the host), then re-run 'skipper'. Your .env is already written."
    fi

    local err code
    err="$("$venv_py" "$check" 2>&1)" && code=0 || code=$?
    if [ "$code" -eq 0 ]; then
        ok "PostgreSQL ready at $host:$port (connected, pgvector present)."
        return 0
    fi
    if [ "$code" -eq 2 ]; then
        if tcp_open "$host" "$port"; then
            ok "PostgreSQL reachable at $host:$port (could not fully verify)."
            return 0
        fi
        die "Cannot reach PostgreSQL at $host:$port. $err"
    fi

    # code 1 = can't connect (role/db missing or wrong password);
    # code 4 = connected but pgvector not installed. Either way, offer to fix it.
    echo
    warn "PostgreSQL is reachable but not set up for Skipper yet:"
    printf '   %s\n' "$err"
    invoke_native_db_bootstrap "$host" "$venv_py" "$check"
}

# Offer to create the role + database + pgvector with a superuser login. The
# superuser password goes to the helper via an environment variable (never
# stored, never on a command line) and is dropped immediately after.
invoke_native_db_bootstrap() {
    local host="$1" venv_py="$2" check="$3"
    echo
    echo "Skipper can set this up for you: it will create the 'skipperbot' role + database"
    echo "+ the pgvector extension on $host, using your PostgreSQL superuser login."
    if ! confirm "Set up the database now?"; then
        echo
        printf '   To do it by hand, connect as the postgres superuser and run:\n'
        printf "     CREATE USER skipperbot_user WITH PASSWORD '<the password you entered>';\n"
        printf '     CREATE DATABASE skipperbot OWNER skipperbot_user;\n'
        printf '     \\c skipperbot\n'
        printf '     CREATE EXTENSION IF NOT EXISTS vector;\n'
        printf '   Then re-run '\''skipper'\''. Full guide: docs/01-base-platform-setup.md steps 1-3.\n'
        echo
        die "Database not set up yet."
    fi

    local su_user su_pass out code
    read -r -p "PostgreSQL superuser name [postgres]: " su_user; [ -z "$su_user" ] && su_user="postgres"
    read -r -s -p "Password for '$su_user': " su_pass; echo

    out="$(SKIPPER_SUPERUSER="$su_user" SKIPPER_SUPERPASS="$su_pass" "$venv_py" "$REPO/scripts/bootstrap_db.py" 2>&1)" && code=0 || code=$?
    su_pass=""
    [ -n "$out" ] && printf '%s\n' "$out"

    case "$code" in
        0)
            if "$venv_py" "$check" >/dev/null 2>&1; then
                ok "Database is ready (role + database + pgvector created)."
                return 0
            fi
            die "Database was created but the app user still can't connect. Check .env, then re-run 'skipper'."
            ;;
        3)
            echo
            warn "pgvector isn't installed on this PostgreSQL server, so a native install can't finish here."
            printf '   Install pgvector for your server, then re-run '\''skipper'\'':\n'
            printf '   - Debian/Ubuntu:  sudo apt install -y postgresql-18-pgvector\n'
            printf '   - RHEL/Fedora:    sudo dnf install -y pgvector_18\n'
            printf '   - macOS (brew):   brew install pgvector\n'
            printf '   Or re-run '\''skipper'\'' and choose Docker (it bundles Postgres 18 + pgvector),\n'
            printf '   or point at a Postgres on your network that already has pgvector.\n'
            echo
            die "pgvector required but not available on this server."
            ;;
        1)
            die "Could not log in as superuser '$su_user'. Re-run 'skipper' and try again, or set the database up by hand (docs/01-base-platform-setup.md steps 1-3)."
            ;;
        *)
            die "Database setup didn't complete (see the message above). You can set it up by hand per docs/01-base-platform-setup.md steps 1-3, then re-run 'skipper'."
            ;;
    esac
}

# --- first-run setup ---------------------------------------------------------
setup() {
    log "First-time setup — creating $ENV_FILE"
    [ -f "$ENV_FILE" ] || cp "$EXAMPLE_ENV" "$ENV_FILE"

    local key pw pw2
    while :; do
        read -r -p "OpenAI API key (from https://platform.openai.com/api-keys): " key
        [ -n "$key" ] && break
        warn "An OpenAI key is required."
    done
    while :; do
        read -r -s -p "Choose a Postgres password (any strong value): " pw; echo
        read -r -s -p "Confirm password: " pw2; echo
        [ -n "$pw" ] && [ "$pw" = "$pw2" ] && break
        warn "Passwords were empty or didn't match — try again."
    done

    set_env OPENAI_API_KEY "$key"
    set_env POSTGRES_PASSWORD "$pw"

    # For a native run, ask where Postgres lives and write it into .env so the
    # agent connects to your host DB (not the docker-compose 'db' service).
    # Docker uses the bundled 'db' service automatically, so we don't ask.
    if [ "$RUNTIME" = "native" ]; then
        local dbhost dbport
        echo "Where is your PostgreSQL server? Use 'localhost' for this machine, or a"
        echo "hostname/IP for an existing Postgres server on your network."
        read -r -p "Postgres host [localhost]: " dbhost; [ -z "$dbhost" ] && dbhost="localhost"
        read -r -p "Postgres port [5432]: " dbport; [ -z "$dbport" ] && dbport="5432"
        set_env DB_HOST "$dbhost"
        set_env DB_PORT "$dbport"
    fi

    # SKIPPERBOT_SECRET_KEY is intentionally left blank: the platform
    # auto-generates and persists it to .env on first boot (ensure_secret_key).
    ok ".env written (the secret-encryption key is auto-generated on first boot)."

    # The deploy-watcher is a systemd service that recycles the Docker stack, so
    # only offer it for a Docker run on a systemd host (skips macOS, WSL without
    # systemd, and native runs - matching the Windows launcher, which has none).
    if [ "$RUNTIME" = "docker" ] && command -v systemctl >/dev/null 2>&1 \
        && confirm "Install the deploy-watcher service now? (enables the in-app 'deploy + restart' button)"; then
        install_watcher || warn "Deploy watcher not installed — you can run 'skipper.sh' again later or install it by hand."
    fi
}

# --- deploy watcher (systemd) ------------------------------------------------
install_watcher() {
    command -v systemctl >/dev/null 2>&1 || { warn "systemd not found — skipping deploy watcher (it's optional)."; return 1; }
    [ -x "$REPO/scripts/deploy_watcher.sh" ] || { warn "scripts/deploy_watcher.sh missing — skipping."; return 1; }
    local user; user="$(id -un)"
    local unit="/etc/systemd/system/${WATCHER_SVC}.service"
    log "Installing the deploy watcher (needs sudo): $unit"
    sudo tee "$unit" >/dev/null <<EOF
[Unit]
Description=Skipperbot deploy watcher (git pull + docker recycle on UI/API deploy)
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=$user
WorkingDirectory=$REPO
ExecStart=$REPO/scripts/deploy_watcher.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$WATCHER_SVC"
    ok "Deploy watcher installed and running."
}

# --- start / stop ------------------------------------------------------------
start() {
    resolve_runtime
    if [ "$RUNTIME" = "docker" ]; then
        log "Starting Skipper via Docker (docker compose up -d) — first boot builds the UI, can take a few minutes…"
        docker compose up -d
        ok "Skipper is starting. Open http://localhost:8000   (follow logs: skipper.sh logs)"
    else
        [ -x "$REPO/start_agent.sh" ] || die "start_agent.sh not found/executable. See README 'Path 2: Native install'."
        log "Starting Skipper natively via start_agent.sh (Ctrl-C to stop)…"
        exec "$REPO/start_agent.sh"
    fi
}

stop() {
    resolve_runtime
    if [ "$RUNTIME" = "docker" ]; then
        log "Stopping Docker stack (docker compose down)…"; docker compose down; ok "Stopped."
    else
        warn "Native run: stop the start_agent.sh process (Ctrl-C in its terminal, or systemctl stop skipperbot-agent if installed as a service)."
    fi
}

logs() {
    resolve_runtime
    if [ "$RUNTIME" = "docker" ]; then
        docker compose logs -f agent
    else
        journalctl -u skipperbot-agent -f 2>/dev/null || warn "For a native run, check the start_agent.sh console output."
    fi
}
status() {
    resolve_runtime
    if [ "$RUNTIME" = "docker" ]; then docker compose ps; fi
    printf '%sHealth:%s ' "$_dim" "$_rst"
    curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' --max-time 5 http://localhost:8000/api/onboarding/status 2>/dev/null || echo "not responding yet"
}
update() { exec "$REPO/scripts/update_server.sh"; }

# --- install onto PATH -------------------------------------------------------
install_cli() {
    local target=/usr/local/bin/skipper
    log "Linking $target -> $REPO/scripts/skipper.sh (needs sudo)"
    sudo ln -sf "$REPO/scripts/skipper.sh" "$target"
    ok "Installed. You can now run 'skipper' from anywhere."
}
uninstall_cli() { sudo rm -f /usr/local/bin/skipper && ok "Removed /usr/local/bin/skipper."; }

usage() {
    cat <<EOF
skipper — launch and manage the Skipperbot platform

Usage: ./scripts/skipper.sh [command]   (or 'skipper' if installed)

  (no command)   Ask Docker-vs-native, verify that runtime's prerequisites,
                 run first-time setup if needed, then start Skipper.
  setup          (Re)configure .env (OpenAI key + Postgres password).
  start          Start Skipper (asks Docker or native first).
  stop           Stop Skipper (Docker stack, or reminds you for native).
  restart        Restart (stop + start).
  update         git pull + recycle (scripts/update_server.sh).
  logs           Follow the agent logs.
  status         Show container + health status.
  install        Symlink this script to /usr/local/bin/skipper.
  uninstall      Remove the /usr/local/bin/skipper symlink.
  help           Show this help.

On start/setup you'll be asked how to run Skipper:
  Docker — bundles Postgres + Python + Node in containers (recommended).
  Native — runs on the host; you must have PostgreSQL 18 + pgvector,
           Python 3.12, and Node 24+ installed (see docs/01-base-platform-setup.md).

Note: Run './scripts/skipper.sh install' to add 'skipper' to your PATH (Linux/Mac).
      On Windows, use scripts/skipper.bat or: powershell -ExecutionPolicy Bypass -File scripts/skipper.ps1
EOF
}

# --- banner ------------------------------------------------------------------
banner() {
    printf '%s' "$_cyan"
    cat <<'EOF'
##### #   # ##### ##### ##### ##### ##### ####  ##### #####
#     #  #    #   #   # #   # #     #   # #   # #   #   #
##### ###     #   ##### ##### ####  ##### ####  #   #   #
    # #  #    #   #     #     #     #  #  #   # #   #   #
##### #   # ##### #     #     ##### #   # ####  #####   #
EOF
    printf '%s' "$_rst"
    printf '%sAn agentic app platform for your family.%s\n\n' "$_dim" "$_rst"
}

# --- dispatch ----------------------------------------------------------------
banner
cmd="${1:-}"
case "$cmd" in
    ""|up|launch)   ensure_runtime_tooling; needs_setup && setup; ensure_runtime_database; start ;;
    setup|config)   ensure_runtime_tooling; setup; ensure_runtime_database ;;
    start)          ensure_runtime_tooling; needs_setup && setup; ensure_runtime_database; start ;;
    stop|down)      stop ;;
    restart)        ensure_runtime_tooling; needs_setup && setup; ensure_runtime_database; stop; start ;;
    update)         update ;;
    logs)           logs ;;
    status|ps)      status ;;
    install)        install_cli ;;
    uninstall)      uninstall_cli ;;
    help|-h|--help) usage ;;
    *)              warn "Unknown command: $cmd"; usage; exit 1 ;;
esac
