#!/usr/bin/env bash
# =============================================================================
# skipper.sh — one-command launcher + first-run setup for the Skipperbot platform
# =============================================================================
# After cloning the repo, run `./scripts/skipper.sh` (or install it onto your PATH
# with `./scripts/skipper.sh install`, then just `skipper`). Behaviour:
#
#   * First run (no usable .env): asks for your OpenAI key and a Postgres
#     password, writes .env, offers to install the deploy-watcher service,
#     then starts Skipper.
#   * Later runs: just starts Skipper — via Docker if available, otherwise
#     natively (start_agent.sh).
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
_blue=$'\033[34m'; _green=$'\033[32m'; _yellow=$'\033[33m'; _red=$'\033[31m'; _dim=$'\033[2m'; _rst=$'\033[0m'
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
    # SKIPPERBOT_SECRET_KEY is intentionally left blank: the platform
    # auto-generates and persists it to .env on first boot (ensure_secret_key).
    ok ".env written (the secret-encryption key is auto-generated on first boot)."

    if confirm "Install the deploy-watcher service now? (enables the in-app 'deploy + restart' button)"; then
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
    if has_docker; then
        log "Starting Skipper via Docker (docker compose up -d) — first boot builds the UI, can take a few minutes…"
        docker compose up -d
        ok "Skipper is starting. Open http://localhost:8000   (follow logs: skipper.sh logs)"
    else
        warn "Docker not found — starting natively via start_agent.sh."
        [ -x "$REPO/start_agent.sh" ] || die "start_agent.sh not found/executable. See README 'Path 2: Native install'."
        log "Running start_agent.sh (Ctrl-C to stop)…"
        exec "$REPO/start_agent.sh"
    fi
}

stop() {
    if has_docker; then
        log "Stopping Docker stack (docker compose down)…"; docker compose down; ok "Stopped."
    else
        warn "Native run: stop the start_agent.sh process (Ctrl-C in its terminal, or systemctl stop skipperbot-agent if installed as a service)."
    fi
}

logs()   { has_docker && docker compose logs -f agent || journalctl -u skipperbot-agent -f; }
status() {
    if has_docker; then docker compose ps; fi
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

  (no command)   First-run setup if needed, then start Skipper.
  setup          (Re)configure .env (OpenAI key + Postgres password).
  start          Start Skipper (Docker if available, else native).
  stop           Stop the Docker stack.
  restart        Restart (stop + start).
  update         git pull + recycle (scripts/update_server.sh).
  logs           Follow the agent logs.
  status         Show container + health status.
  install        Symlink this script to /usr/local/bin/skipper.
  uninstall      Remove the /usr/local/bin/skipper symlink.
  help           Show this help.

Note: Run './scripts/skipper.sh install' to add 'skipper' to your PATH (Linux/Mac).
      On Windows, use scripts/skipper.bat or: powershell -ExecutionPolicy Bypass -File scripts/skipper.ps1
EOF
}

# --- dispatch ----------------------------------------------------------------
cmd="${1:-}"
case "$cmd" in
    ""|up|launch)   needs_setup && setup; start ;;
    setup|config)   setup ;;
    start)          start ;;
    stop|down)      stop ;;
    restart)        stop; start ;;
    update)         update ;;
    logs)           logs ;;
    status|ps)      status ;;
    install)        install_cli ;;
    uninstall)      uninstall_cli ;;
    help|-h|--help) usage ;;
    *)              warn "Unknown command: $cmd"; usage; exit 1 ;;
esac
