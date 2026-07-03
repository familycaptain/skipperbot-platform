#!/usr/bin/env bash
# =============================================================================
# skipper.sh — one-command launcher + first-run setup for the Skipperbot platform
# =============================================================================
# After cloning the repo, run `./skipper.sh` (or install it onto your PATH
# with `./skipper.sh install`, then just `skipper`). Behaviour:
#
#   * First run ASKS how to run Skipper — Docker or native — and REMEMBERS the
#     choice in .env (SKIPPER_RUNTIME); later runs reuse it without asking.
#     Run 'skipper setup' to change it. Each run verifies that runtime's
#     prerequisites before doing anything else.
#       - Docker: bundles Postgres + Python + Node in containers (recommended).
#       - Native: runs on the host; you must already have PostgreSQL 18 +
#         pgvector, Python 3.12, and Node 24+ installed. The launcher then
#         installs the project's own deps for you (venv + pip + npm ci).
#   * First run (no usable .env): asks for a Postgres password, writes .env,
#     offers to install the deploy-watcher service,
#     then starts Skipper.
#   * Later runs: start Skipper, wait until it has finished booting, then drop
#     you into the live log (Ctrl+C stops watching; Skipper keeps running).
#
# Think `claude` / `openclaw`: one short command to bring Skipper up.
#
# Subcommands:  setup | start | stop | restart | update | logs | status |
#               install | uninstall | help   (no subcommand = setup-if-needed + start)
# =============================================================================

set -euo pipefail

# --- locate the repo root (works whether run directly or via a PATH symlink) -
# This launcher lives at the repo root, so the repo root is its own directory.
_src="${BASH_SOURCE[0]}"
_real="$(readlink -f "$_src" 2>/dev/null || echo "$_src")"
REPO="$(cd "$(dirname "$_real")" && pwd)"
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

# The web UI / API port (SKIPPERBOT_PORT in .env, default 8000). Used for the
# readiness poll, status check, and the "open http://localhost:PORT" messages so
# they all follow a custom port instead of assuming 8000.
skipper_port() {
    local p; p="$(env_get SKIPPERBOT_PORT)"
    [ -z "$p" ] && p="8000"
    printf '%s' "$p"
}

needs_setup() {
    [ -f "$ENV_FILE" ] || return 0
    # MODEL_FLEXIBILITY (#44): boot is no longer gated on OPENAI_API_KEY. The agent boots
    # keyless+healthy and the model/provider is chosen in the first-run modal (or seeded from an
    # existing .env key on upgrade). Only the DB password still gates setup here.
    local pw; pw="$(env_get POSTGRES_PASSWORD)"
    { [ -z "$pw" ] || [ "$pw" = "CHANGE_ME" ]; } && return 0
    return 1
}

# --- runtime selection -------------------------------------------------------
# skipper supports two runtimes:
#   docker — bundles Postgres + Python + Node in containers (recommended)
#   native — runs on the host; YOU must have Postgres/Python/Node installed
# The choice is remembered in .env (SKIPPER_RUNTIME) so we only ASK once; later
# runs reuse it silently. 'skipper setup' forces the question again (it sets
# FORCE_ASK_RUNTIME=1). After resolving we verify that runtime's prerequisites
# before doing anything else (so we never get half-way and then fail).
RUNTIME=""
FORCE_ASK_RUNTIME=0

resolve_runtime() {
    [ -n "$RUNTIME" ] && return 0

    # Reuse a previously-saved choice unless the user explicitly ran 'setup'.
    if [ "$FORCE_ASK_RUNTIME" != "1" ]; then
        local saved; saved="$(env_get SKIPPER_RUNTIME)"
        case "$saved" in
            docker|native) RUNTIME="$saved"; log "Using saved runtime: $saved (run 'skipper setup' to change)."; return 0 ;;
        esac
    fi

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
    # Persist the choice so later runs don't re-ask. On a brand-new install .env
    # doesn't exist yet (setup creates it and re-saves this too); guard for that.
    # NB: must be an `if`, not `[ -f ] && set_env` — when .env is absent the `&&`
    # returns 1, and as the function's last command that propagates out and trips
    # `set -e`, silently killing the script on first run (the no-.env case).
    if [ -f "$ENV_FILE" ]; then set_env SKIPPER_RUNTIME "$RUNTIME"; fi
}

# Prerequisite checks come in two phases:
#   Tooling  — Node + Python; checked BEFORE setup (no .env needed), so we
#              never run setup on a machine that can't run Skipper.
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

    local pw pw2
    while :; do
        read -r -s -p "Choose a Postgres password (any strong value): " pw; echo
        read -r -s -p "Confirm password: " pw2; echo
        [ -n "$pw" ] && [ "$pw" = "$pw2" ] && break
        warn "Passwords were empty or didn't match — try again."
    done

    # No LLM provider key is collected here (#44): the platform boots keyless and
    # you choose your provider + enter its key in the web UI on first run.
    set_env POSTGRES_PASSWORD "$pw"
    # Remember how to run Skipper so later starts don't re-ask Docker-vs-native.
    set_env SKIPPER_RUNTIME "$RUNTIME"

    # Web server port (default 8000). Just press Enter unless 8000 is taken.
    local port
    while :; do
        read -r -p "Web server port [8000]: " port
        [ -z "$port" ] && port="8000"
        if [[ "$port" =~ ^[0-9]+$ ]] && [ "$port" -ge 1 ] && [ "$port" -le 65535 ]; then break; fi
        warn "Enter a port number between 1 and 65535 (or press Enter for 8000)."
    done
    set_env SKIPPERBOT_PORT "$port"

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
    # NOTE: the optional deploy-watcher (remote 'deploy' = git pull + rebuild) is
    # NOT installed during setup — it's an advanced extra that confused first-run
    # installs. Install it later on a Docker+systemd host with 'skipper.sh watcher'.
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

# --- enable-voice (opt-in voice speaker-ID extra) ----------------------------
# Multi-speaker voice attribution needs resemblyzer + torch (~500MB), which is
# NOT in the base install. This installs the opt-in extra (requirements-voice.txt)
# after setup. Like the deploy-watcher, it's a deliberately separate, on-demand
# step. The torch BUILD is the user's choice: DEFAULT = the CPU wheel (smaller,
# works everywhere), --gpu = the CUDA build, --cpu = force CPU. A compatible torch
# that's already installed is honored (not overridden). Runtime-aware: native pips
# into the .venv; Docker bakes deps into the image, so it prints the documented
# rebuild path instead (a host-venv pip would never reach the container).
#   --dry-run   print the exact pip command without running it.
# SKIPPER_RUNTIME / SKIPPER_VENV_PY may be set in the environment to override the
# saved runtime and the venv interpreter (used by the bound tests).
enable_voice() {
    local mode="cpu" dry_run=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --gpu)      mode="gpu" ;;
            --cpu)      mode="cpu" ;;
            --dry-run)  dry_run=1 ;;
            -h|--help)
                printf 'Usage: ./skipper.sh enable-voice [--gpu|--cpu] [--dry-run]\n'
                printf '  Install the opt-in voice speaker-ID extra (per-speaker attribution).\n'
                printf '  Default installs the CPU torch wheel; --gpu installs the CUDA build.\n'
                return 0 ;;
            *) warn "Unknown 'enable-voice' option: $1"; return 1 ;;
        esac
        shift
    done

    # Runtime: honor a live SKIPPER_RUNTIME override, else the saved choice.
    local runtime="${SKIPPER_RUNTIME:-}"
    if [ -z "$runtime" ]; then resolve_runtime; runtime="$RUNTIME"; fi

    if [ "$runtime" = "docker" ]; then
        # Docker bakes Python deps into the image at build time, so a pip run on
        # the host venv would never reach the container. The supported path is a
        # documented image rebuild that carries the extra.
        log "Docker runtime detected — voice speaker-ID is enabled by REBUILDING the image."
        cat <<'EOF'
   A host-side pip install cannot reach the container, so add the extra to the
   image and rebuild:
     1. In the Dockerfile, after 'RUN pip install -r requirements.txt', add:
          RUN pip install -r requirements-voice.txt \
              --extra-index-url https://download.pytorch.org/whl/cpu
        (drop the --extra-index-url line to build the CUDA/GPU torch instead.)
     2. Rebuild + recycle the stack:  ./skipper.sh update
   See docs/03-extended-functionality.md → Voice for the full walkthrough.
EOF
        return 0
    fi

    # Native: the .venv must already exist (base setup creates it).
    local venv_py="${SKIPPER_VENV_PY:-$REPO/.venv/bin/python}"
    if [ ! -x "$venv_py" ]; then
        die "No Python virtual-env found (expected $venv_py). Run base setup first:  ./skipper.sh setup"
    fi

    # Honor a pre-installed compatible torch — don't override the user's build.
    local have_torch=0
    if "$venv_py" -c "import torch" >/dev/null 2>&1; then have_torch=1; fi

    local pip_cmd=("$venv_py" -m pip install -r "$REPO/requirements-voice.txt")
    if [ "$have_torch" -eq 1 ]; then
        ok "A compatible torch is already installed — honoring it (won't reinstall torch)."
        # No torch index: pip sees the floor satisfied and leaves the build as-is.
    elif [ "$mode" = "gpu" ]; then
        log "Installing the CUDA (GPU) torch build from the default index."
        # Default PyPI index resolves the CUDA-capable wheel; no extra flags.
    else
        log "Installing the CPU-only torch build (default — smaller, works everywhere)."
        pip_cmd+=(--extra-index-url https://download.pytorch.org/whl/cpu)
    fi

    if [ "$dry_run" -eq 1 ]; then
        printf 'DRY RUN — would run:\n  %s\n' "${pip_cmd[*]}"
        return 0
    fi

    log "Enabling voice speaker identification (this can take a few minutes)…"
    if "${pip_cmd[@]}"; then
        ok "Voice speaker-ID enabled. Verify:"
        printf "   %s -c 'from app_platform.voice import speaker_id; print(speaker_id.available())'\n" "$venv_py"
        printf "   (should print True; then restart Skipper to pick it up).\n"
    else
        # Repo-standard failure report: name the platform + link the docs, never a
        # bare pip traceback. Most likely no prebuilt torch wheel for this OS/arch.
        local plat; plat="$(uname -sm 2>/dev/null || echo unknown)"
        warn "Could not install the voice speaker-ID extra on this platform ($plat)."
        printf '   There may be no prebuilt torch wheel for your OS/arch, or the network was unreachable.\n'
        printf '   Supported platforms + options:  docs/03-extended-functionality.md → Voice\n'
        printf '   To retry by hand:  %s\n' "${pip_cmd[*]}"
        return 1
    fi
}

# Announce readiness from the BACKGROUND while the boot log streams in the
# foreground. The Docker entrypoint does npm install + build + init_db BEFORE
# binding port 8000, so 'docker compose up -d' returns long before the site is
# reachable. We poll health quietly (no dots spinner hiding the boot) and print a
# banner the moment it answers — interleaved into the live log. Returns 0 once
# HTTP responds, 1 if it never came up in time.
# $1 = port, $2 = mode ('docker' default, or 'native'). The footer differs: under
# Docker the tail is detached so Ctrl+C just stops watching; natively the agent
# runs in THIS terminal, so we drop the Ctrl+C wording (there it would stop it).
_announce_when_ready() {
    local port="$1"
    local mode="${2:-docker}"
    local url="http://localhost:$port/api/onboarding/status"
    local open="http://localhost:$port"
    local foot=""
    [ "$mode" = "docker" ] && \
        foot=$'\n  (boot log continues below; Ctrl+C stops watching, Skipper keeps running)'
    local tries=120 i=0   # ~10 min at 5s; first build on a slow box can be minutes
    while [ "$i" -lt "$tries" ]; do
        if curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null; then
            # Repeat the READY banner every 10s for the first minute. The agent
            # logs scroll fast once it boots, so a single line vanishes — a
            # first-time user needs to keep seeing exactly which page to open.
            local rule="════════════════════════════════════════════════════════════"
            local r
            for r in 1 2 3 4 5 6; do
                printf '\n%s%s\n  ✓  Skipper is READY  —  open this page in your browser:\n\n        %s\n%s\n%s%s\n' \
                    "$_green" "$rule" "$open" "$foot" "$rule" "$_rst"
                [ "$r" -lt 6 ] && sleep 10
            done
            return 0
        fi
        sleep 5; i=$((i+1))
    done
    echo
    warn "Skipper still isn't responding after ~10 min — scroll up for build errors. Skipper keeps running in the background."
    return 1
}

# Stream the agent log IMMEDIATELY (so the whole boot sequence + any errors are
# visible in real time), and announce the URL from the background once health
# responds. Ctrl+C stops the tail but leaves the daemon running. Shared by
# start() and update() so they can't drift.
# Non-interactive readiness wait: poll the app's status endpoint until it answers,
# then RETURN (unlike _follow_boot, which tails the log forever). Used by automation
# so an agent can run `SKIPPER_NO_FOLLOW=1 skipper update` and continue once it's up.
_wait_until_ready() {
    local port="$1" url tries=120 i=0
    url="http://localhost:$port/api/onboarding/status"
    log "Waiting for Skipper to come up on :$port (non-interactive)…"
    while [ "$i" -lt "$tries" ]; do   # ~10 min at 5s; first build on a slow box can be minutes
        if curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null; then
            ok "Skipper is up and serving on :$port."
            return 0
        fi
        sleep 5; i=$((i+1))
    done
    warn "Skipper did not become ready within ~10 min — scroll up for build errors."
    return 1
}

_follow_boot() {
    local port; port="$(skipper_port)"
    echo
    log "Streaming the live boot log — watch the build here and catch any errors as they happen."
    log "Ctrl+C stops watching; Skipper keeps running in the background ('skipper logs' to re-attach, 'skipper stop' to halt)."
    echo
    _announce_when_ready "$port" docker &
    local _watcher=$!
    # Reap the background watcher when the user Ctrl+C's out of the tail.
    trap 'kill "$_watcher" 2>/dev/null' INT
    docker compose logs -f agent || true
    kill "$_watcher" 2>/dev/null || true
    trap - INT
}

# --- start / stop ------------------------------------------------------------
start() {
    resolve_runtime
    if [ "$RUNTIME" = "docker" ]; then
        log "Starting Skipper via Docker (docker compose up -d) — first boot builds the UI, can take a few minutes…"
        docker compose up -d
        _follow_boot
    else
        [ -x "$REPO/start_agent.sh" ] || die "start_agent.sh not found/executable. See README 'Path 2: Native install'."
        log "Starting Skipper natively via start_agent.sh (Ctrl-C to stop)…"
        # Announce the URL (repeating for the first minute) from the background
        # while the agent runs in the foreground here. No exec, so we can reap the
        # watcher when the agent exits or the user Ctrl+C's.
        local port; port="$(skipper_port)"
        _announce_when_ready "$port" native &
        local _watcher=$!
        trap 'kill "$_watcher" 2>/dev/null' INT
        "$REPO/start_agent.sh"
        kill "$_watcher" 2>/dev/null || true
        trap - INT
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
    local port; port="$(skipper_port)"
    printf '%sHealth (port %s):%s ' "$_dim" "$port" "$_rst"
    curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' --max-time 5 "http://localhost:$port/api/onboarding/status" 2>/dev/null || echo "not responding yet"

    # Voice speaker-ID is an opt-in extra — surface whether it's installed so the
    # enable path (./skipper.sh enable-voice) is discoverable.
    local voice_ok=1
    if [ "$RUNTIME" = "docker" ]; then
        docker compose exec -T agent python -c "import resemblyzer" >/dev/null 2>&1 || voice_ok=0
    else
        local venv_py="${SKIPPER_VENV_PY:-$REPO/.venv/bin/python}"
        { [ -x "$venv_py" ] && "$venv_py" -c "import resemblyzer" >/dev/null 2>&1; } || voice_ok=0
    fi
    if [ "$voice_ok" -eq 1 ]; then
        printf '%sVoice speaker-ID:%s installed\n' "$_dim" "$_rst"
    else
        printf "%sVoice speaker-ID:%s not installed (optional) — enable with './skipper.sh enable-voice'\n" "$_dim" "$_rst"
    fi
}
# Runtime-aware update. git pull is the shared first step (both runtimes); only
# the recycle differs. Docker rebuilds the image (up -d --build) so changes to
# requirements.txt / Dockerfile actually take effect, not just bind-mounted code.
update() {
    resolve_runtime
    log "Updating Skipper (git pull)…"
    git pull
    if [ "$RUNTIME" = "docker" ]; then
        log "Rebuilding and recycling the Docker stack (down; up -d --build) so dependency changes take effect…"
        docker compose down
        docker compose up -d --build
        # Interactive operator → tail the boot log (Ctrl+C to stop). Automation
        # (SKIPPER_NO_FOLLOW=1, or no TTY) → block until the app answers, then
        # RETURN — never tail forever, so an agent/CI run can continue.
        if [ "${SKIPPER_NO_FOLLOW:-}" = "1" ] || [ ! -t 1 ]; then
            _wait_until_ready "$(skipper_port)"
        else
            _follow_boot
        fi
    else
        echo
        ok "Code updated (git pull complete)."
        warn "Native run: restart Skipper to apply the update:"
        printf "   - If it's running in a terminal: press Ctrl+C there, then run 'skipper'.\n"
        printf "   - If you installed it as a service: 'skipper service restart'.\n"
    fi
}

# --- install onto PATH -------------------------------------------------------
install_cli() {
    local target=/usr/local/bin/skipper
    log "Linking $target -> $REPO/skipper.sh (needs sudo)"
    sudo ln -sf "$REPO/skipper.sh" "$target"
    ok "Installed. You can now run 'skipper' from anywhere."
}
uninstall_cli() { sudo rm -f /usr/local/bin/skipper && ok "Removed /usr/local/bin/skipper."; }

usage() {
    cat <<EOF
skipper — launch and manage the Skipperbot platform

Usage: ./skipper.sh [command]   (or 'skipper' if installed)

  (no command)   Resolve runtime (asks once, then remembered), verify that
                 runtime's prerequisites, run first-time setup if needed, then
                 start Skipper and follow its log.
  setup          (Re)configure .env (runtime choice + Postgres password;
                 your LLM provider + key are set later in the web UI).
                 Re-asks Docker-vs-native.
  start          Start Skipper, wait until it has booted, then follow the log
                 (Ctrl+C stops watching; Skipper keeps running).
  stop           Stop Skipper (Docker stack, or reminds you for native).
  restart        Restart (stop + start).
  update         git pull, then (Docker) rebuild + recycle so dependency
                 changes apply; (native) pull and prompt you to restart.
  service <sub>  Auto-start on boot: install | uninstall | status | start |
                 stop | restart. systemd (Linux/WSL) or launchd (macOS), chosen
                 from your saved runtime. See docs/04-running-as-a-service.md.
  watcher        Install the OPTIONAL deploy-watcher (Docker+systemd host):
                 enables remote 'deploy' = git pull + rebuild. Not part of setup.
  enable-voice   Install the OPTIONAL voice speaker-ID extra (adds per-speaker
                 attribution). Default installs the CPU torch wheel; --gpu the
                 CUDA build, --cpu forces CPU. Not part of setup.
  logs           Follow the agent logs.
  status         Show container + health status.
  install        Symlink this script to /usr/local/bin/skipper.
  uninstall      Remove the /usr/local/bin/skipper symlink.
  help           Show this help.

On start/setup you'll be asked how to run Skipper:
  Docker — bundles Postgres + Python + Node in containers (recommended).
  Native — runs on the host; you must have PostgreSQL 18 + pgvector,
           Python 3.12, and Node 24+ installed (see docs/01-base-platform-setup.md).

Note: Run './skipper.sh install' to add 'skipper' to your PATH (Linux/Mac).
      On Windows, use skipper.bat or: powershell -ExecutionPolicy Bypass -File skipper.ps1
EOF
}

# --- service (auto-start on boot) --------------------------------------------
# 'skipper service install|uninstall|status|start|stop|restart' makes Skipper
# come back on its own after a reboot. Mechanism depends on OS + saved runtime:
#   Linux  -> systemd unit (docker: 'compose up -d' oneshot tied to docker.service;
#             native: start_agent.sh with Restart=on-failure). Covers WSL too,
#             with an extra note about launching WSL at Windows boot.
#   macOS  -> launchd LaunchAgent at login (docker: waits for Docker then ups;
#             native: start_agent.sh with KeepAlive).
# Windows lives in skipper.ps1. Full picture: docs/04-running-as-a-service.md
SVC_NAME="skipperbot"
SYSTEMD_UNIT="/etc/systemd/system/${SVC_NAME}.service"
LAUNCHD_LABEL="com.skipperbot.agent"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"

is_wsl() { grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; }

service_usage() {
    cat <<EOF
skipper service — run Skipper automatically on boot/login.

Usage: skipper service <install|uninstall|status|start|stop|restart>

  install     Install + enable the OS service for your saved runtime
              (systemd on Linux/WSL, launchd on macOS).
  uninstall   Stop and remove it.
  status      Show service + health status.
  start/stop/restart   Control the installed service.

The mechanism is chosen from SKIPPER_RUNTIME + your OS. On Windows, use
skipper.ps1 (NSSM for native). Full details: docs/04-running-as-a-service.md
EOF
}

service() {
    local action="${1:-help}"
    if [ "$action" = "help" ]; then service_usage; return 0; fi
    case "$action" in
        install|uninstall|status|start|stop|restart) ;;
        *) warn "Unknown 'service' action: $action"; service_usage; exit 1 ;;
    esac
    resolve_runtime
    local os; os="$(uname -s)"
    case "$os" in
        Linux)  service_systemd "$action" ;;   # covers WSL too
        Darwin) service_launchd "$action" ;;
        *)      die "'skipper service' isn't supported on this OS ($os). On Windows use scripts\\skipper.ps1." ;;
    esac
}

# --- Linux: systemd ----------------------------------------------------------
service_systemd() {
    local action="$1"
    command -v systemctl >/dev/null 2>&1 || die "systemd (systemctl) not found — 'skipper service' needs it on Linux. See docs/04-running-as-a-service.md for alternatives."
    case "$action" in
        install)   systemd_install ;;
        uninstall) sudo systemctl disable --now "$SVC_NAME" >/dev/null 2>&1 || true
                   sudo rm -f "$SYSTEMD_UNIT"
                   sudo systemctl daemon-reload
                   ok "Removed the '$SVC_NAME' service (the app itself is untouched)." ;;
        status)    systemctl status "$SVC_NAME" --no-pager || true; status ;;
        start)     sudo systemctl start "$SVC_NAME" && ok "Started." ;;
        stop)      sudo systemctl stop "$SVC_NAME" && ok "Stopped." ;;
        restart)   sudo systemctl restart "$SVC_NAME" && ok "Restarted." ;;
    esac
}

systemd_install() {
    local user docker_bin
    user="$(id -un)"
    docker_bin="$(command -v docker || echo /usr/bin/docker)"
    log "Installing systemd service '$SVC_NAME' (needs sudo): $SYSTEMD_UNIT"
    if [ "$RUNTIME" = "docker" ]; then
        sudo tee "$SYSTEMD_UNIT" >/dev/null <<EOF
[Unit]
Description=Skipperbot (Docker Compose stack)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$REPO
ExecStart=$docker_bin compose up -d
ExecStop=$docker_bin compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl enable docker >/dev/null 2>&1 || true   # ensure Docker itself boots
    else
        sudo tee "$SYSTEMD_UNIT" >/dev/null <<EOF
[Unit]
Description=Skipperbot (native agent)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=$user
WorkingDirectory=$REPO
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$REPO/start_agent.sh
Restart=on-failure
RestartSec=5
# start_agent.sh exits: 0 = clean stop (no restart); 42 = graceful restart
# (treated as failure, so systemd restarts it); other = crash -> restart.

[Install]
WantedBy=multi-user.target
EOF
    fi
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SVC_NAME"
    ok "Service '$SVC_NAME' installed and started (auto-starts on boot)."
    is_wsl && service_wsl_note
    log "Check it with: skipper service status"
}

service_wsl_note() {
    echo
    warn "WSL detected: a systemd service inside WSL only runs while the WSL distro is up."
    echo "   To start Skipper at WINDOWS boot you also need:"
    echo "     1. systemd enabled in WSL  (/etc/wsl.conf -> [boot] / systemd=true), and"
    echo "     2. Windows to launch WSL at logon (a Task Scheduler task running"
    echo "        'wsl -d <distro> true'). See docs/04-running-as-a-service.md (WSL)."
}

# --- macOS: launchd ----------------------------------------------------------
service_launchd() {
    local action="$1"
    case "$action" in
        install)   launchd_install ;;
        uninstall) launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
                   rm -f "$LAUNCHD_PLIST"
                   ok "Removed the '$LAUNCHD_LABEL' LaunchAgent (the app itself is untouched)." ;;
        status)    if launchctl list 2>/dev/null | grep -q "$LAUNCHD_LABEL"; then ok "LaunchAgent '$LAUNCHD_LABEL' is loaded."; else warn "LaunchAgent '$LAUNCHD_LABEL' is not loaded (run 'skipper service install')."; fi; status ;;
        start)     launchctl start "$LAUNCHD_LABEL" && ok "Started." ;;
        stop)      launchctl stop "$LAUNCHD_LABEL" && ok "Stopped." ;;
        restart)   launchctl stop "$LAUNCHD_LABEL" 2>/dev/null || true; launchctl start "$LAUNCHD_LABEL" && ok "Restarted." ;;
    esac
}

launchd_install() {
    local docker_bin
    docker_bin="$(command -v docker || echo /usr/local/bin/docker)"
    mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
    if [ "$RUNTIME" = "docker" ]; then
        cat > "$LAUNCHD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>until $docker_bin info >/dev/null 2>&1; do sleep 3; done; $docker_bin compose up -d</string>
  </array>
  <key>StandardOutPath</key><string>$REPO/logs/skipper-service.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/skipper-service.log</string>
</dict>
</plist>
EOF
    else
        cat > "$LAUNCHD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/start_agent.sh</string>
  </array>
  <key>StandardOutPath</key><string>$REPO/logs/skipper-service.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/skipper-service.log</string>
</dict>
</plist>
EOF
    fi
    launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    launchctl load "$LAUNCHD_PLIST"
    ok "LaunchAgent '$LAUNCHD_LABEL' installed (starts at login)."
    warn "macOS LaunchAgents run at LOGIN. For a headless box, enable automatic login (System Settings -> Users & Groups -> Automatically log in as)."
    log "Check it with: skipper service status"
}

# --- banner ------------------------------------------------------------------
banner() {
    # Prefer the shared logo.txt (same art the PowerShell launcher uses); fall
    # back to inline art if it's missing (e.g. a partial checkout).
    printf '%s' "$_cyan"
    if [ -f "$REPO/scripts/logo.txt" ]; then
        cat "$REPO/scripts/logo.txt"
    else
        cat <<'EOF'
##### #   # ##### ##### ##### ##### ##### ####  ##### #####
#     #  #    #   #   # #   # #     #   # #   # #   #   #
##### ###     #   ##### ##### ####  ##### ####  #   #   #
    # #  #    #   #     #     #     #  #  #   # #   #   #
##### #   # ##### #     #     ##### #   # ####  #####   #
EOF
    fi
    printf '%s' "$_rst"
    printf '%sAn agentic app platform for your family.%s\n\n' "$_dim" "$_rst"
}

# --- dispatch ----------------------------------------------------------------
banner
cmd="${1:-}"
case "$cmd" in
    ""|up|launch)   ensure_runtime_tooling; needs_setup && setup; ensure_runtime_database; start ;;
    setup|config)   FORCE_ASK_RUNTIME=1; ensure_runtime_tooling; setup; ensure_runtime_database ;;
    start)          ensure_runtime_tooling; needs_setup && setup; ensure_runtime_database; start ;;
    stop|down)      stop ;;
    restart)        ensure_runtime_tooling; needs_setup && setup; ensure_runtime_database; stop; start ;;
    update)         update ;;
    service)        service "${2:-help}" ;;
    watcher)        install_watcher ;;
    enable-voice)   shift; enable_voice "$@" ;;
    logs)           logs ;;
    status|ps)      status ;;
    install)        install_cli ;;
    uninstall)      uninstall_cli ;;
    help|-h|--help) usage ;;
    *)              warn "Unknown command: $cmd"; usage; exit 1 ;;
esac
