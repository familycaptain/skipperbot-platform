# Windows / PowerShell equivalent of scripts/update_server.sh.
# Pulls the latest code and recycles the docker compose stack.
#
# Run from anywhere (it cd's to the repo root):
#   pwsh scripts/update_server.ps1
# Requires Git and Docker Desktop (with `docker compose`) on PATH.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)   # repo root

git pull
docker compose down
docker compose up -d
docker compose logs -f agent
