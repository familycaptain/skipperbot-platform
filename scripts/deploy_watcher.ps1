# Windows / PowerShell equivalent of scripts/deploy_watcher.sh.
# Host-side deploy watcher: when the agent drops a .deploy_pending sentinel
# (after a graceful drain via the UI/API deploy), this pulls the latest code and
# recycles the docker compose stack. Keeps the container isolated (no docker
# socket). Run once on the host:
#   pwsh scripts/deploy_watcher.ps1
# Set $env:DEPLOY_WATCH_INTERVAL to change the poll interval (seconds).

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$sentinel = Join-Path $root ".deploy_pending"
$interval = if ($env:DEPLOY_WATCH_INTERVAL) { [int]$env:DEPLOY_WATCH_INTERVAL } else { 5 }
Set-Location $root
Write-Host "[deploy_watcher] watching $sentinel (every $interval s)"

while ($true) {
    if (Test-Path $sentinel) {
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[deploy_watcher] $ts deploy requested - pulling + recycling"
        Remove-Item $sentinel -Force   # remove first so the recycled agent doesn't re-trigger
        git pull
        docker compose down
        docker compose up -d
        Write-Host "[deploy_watcher] $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') deploy complete"
    }
    Start-Sleep -Seconds $interval
}
