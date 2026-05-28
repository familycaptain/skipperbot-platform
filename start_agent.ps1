# =============================================================================
# Skipperbot Agent - native start script (Windows native)
# =============================================================================
# Does the same "rebuild web bundle if apps/ changed" check that the Docker
# entrypoint and the Linux/macOS start_agent.sh do, so installing an app
# is the same flow on every platform.
#
# Usage: .\start_agent.ps1
#
# Includes a restart loop so a clean Ctrl+C stops; exit 42 = graceful restart
# (POST /api/admin/restart triggers this); any other exit = crash + restart.
#
# To run as a Windows service, use NSSM or a Task Scheduler entry that calls
# this script.

$ErrorActionPreference = "Stop"

$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppsDir = Join-Path $AppRoot "apps"
$WebDir = Join-Path $AppRoot "web"
$DistDir = Join-Path $WebDir "dist"
$Stamp = Join-Path $DistDir ".last-build-stamp"

# Pick the Python interpreter. Prefer the project's venv if present.
$VenvPython = Join-Path $AppRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

if (-not (Test-Path (Join-Path $AppRoot ".env"))) {
    Write-Error "ERROR: $AppRoot\.env not found. Copy .env.example to .env and fill in SKIPPERBOT_DB_DSN and OPENAI_API_KEY. See docs/01-base-platform-setup.md step 8."
    exit 1
}

function Log($msg) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
}

function Test-NeedsRebuild {
    if (-not (Test-Path $DistDir) -or (Get-ChildItem $DistDir -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
        Log "web/dist is empty or missing; rebuild required"
        return $true
    }
    if (-not (Test-Path $Stamp)) {
        Log "build stamp missing; rebuild required"
        return $true
    }
    if (Test-Path $AppsDir) {
        $stampTime = (Get-Item $Stamp).LastWriteTime
        $newer = Get-ChildItem -Path $AppsDir -Recurse -File -ErrorAction SilentlyContinue |
                 Where-Object { $_.FullName -match '\\ui\\' -and $_.LastWriteTime -gt $stampTime } |
                 Select-Object -First 1
        if ($newer) {
            Log "detected app UI changes since last build; rebuild required"
            return $true
        }
    }
    return $false
}

function Invoke-Rebuild {
    if (-not (Test-Path (Join-Path $WebDir "package.json"))) {
        Log "WARNING: no $WebDir\package.json; cannot rebuild UI. Starting agent anyway."
        return
    }
    Log "building web bundle (npm run build) ..."
    Push-Location $WebDir
    try {
        & npm run build
        if ($LASTEXITCODE -eq 0) {
            New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
            $null = New-Item -ItemType File -Force -Path $Stamp
            Log "web build OK"
        } else {
            Log "ERROR: web build failed (exit $LASTEXITCODE). Starting agent with stale dist/."
        }
    } finally {
        Pop-Location
    }
}

$env:PYTHONUTF8 = "1"

while ($true) {
    if (Test-NeedsRebuild) {
        Invoke-Rebuild
    }

    Log "starting agent on :8000"
    $startTime = Get-Date
    & $Python (Join-Path $AppRoot "agent.py")
    $exitCode = $LASTEXITCODE
    $elapsed = [math]::Round(((Get-Date) - $startTime).TotalSeconds)

    Log "agent exited with code $exitCode (ran for ${elapsed}s)"

    if ($exitCode -eq 42) {
        Log "graceful restart requested; restarting in 2s ..."
        Start-Sleep -Seconds 2
        continue
    } elseif ($exitCode -eq 0) {
        Log "clean shutdown; not restarting."
        break
    } else {
        Log "unexpected exit; restarting in 10s (Ctrl+C now to abort) ..."
        Start-Sleep -Seconds 10
        continue
    }
}
