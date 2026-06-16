# =============================================================================
# Skipperbot Agent - native start script (Windows native)
# =============================================================================
# Rebuilds the web bundle on every start (cheap - ~5-15s with cached
# node_modules) so the install-an-app or git-pull-the-platform flow never
# leaves stale UI behind. Mirrors deploy/entrypoint.sh and start_agent.sh.
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
$WebDir = Join-Path $AppRoot "web"

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

function Invoke-WebBuild {
    if (-not (Test-Path (Join-Path $WebDir "package.json"))) {
        Log "WARNING: no $WebDir\package.json; skipping web build."
        return
    }
    Log "building web bundle (npm run build) ..."
    Push-Location $WebDir
    try {
        # Install packaged-app frontend deps (mirrors deploy/entrypoint.sh) so
        # apps that declare extra npm deps in apps/<id>/ui/package.json build
        # natively too — not just under Docker.
        if (Test-Path (Join-Path $WebDir "packaged-app-deps.mjs")) {
            & node packaged-app-deps.mjs --install
            if ($LASTEXITCODE -ne 0) {
                Log "WARNING: packaged-app dep install failed; build may fail for apps needing extra deps."
            }
        }
        & npm run build
        if ($LASTEXITCODE -eq 0) {
            Log "web build OK"
        } else {
            Log "ERROR: web build failed (exit $LASTEXITCODE). Starting agent with stale dist/."
        }
    } finally {
        Pop-Location
    }
}

function Invoke-AppPyDeps {
    # Install packaged-app Python deps (mirrors deploy/entrypoint.sh §0c).
    # Optional/community apps cloned into apps\<id>\ may import Python packages
    # the platform's requirements.txt doesn't bundle (e.g. newsletter ->
    # yfinance). Each declares them in apps\<id>\requirements.txt; install the
    # union so a cloned app's imports resolve at runtime - no manual pip step.
    # Fast no-op when unchanged via a checksum stamp beside site-packages.
    $reqs = @(Get-ChildItem -Path (Join-Path $AppRoot "apps\*\requirements.txt") -ErrorAction SilentlyContinue)
    if ($reqs.Count -eq 0) { return }
    $site = (& $Python -c "import sysconfig; print(sysconfig.get_path('purelib'))" 2>$null)
    if (-not $site) { $site = $env:TEMP }
    $stamp = Join-Path $site ".skipper-app-pydeps-stamp"
    $sig = (Get-FileHash -Algorithm SHA1 -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes(($reqs | Get-Content -Raw) -join "")))).Hash
    if ((Test-Path $stamp) -and ((Get-Content $stamp -ErrorAction SilentlyContinue) -eq $sig)) { return }
    Log "installing packaged-app Python dependencies ($($reqs.Count) file(s)) ..."
    $args = @(); foreach ($r in $reqs) { $args += @("-r", $r.FullName) }
    & $Python -m pip install @args
    if ($LASTEXITCODE -eq 0) {
        Set-Content -Path $stamp -Value $sig
    } else {
        Log "WARNING: packaged-app Python dep install failed; apps needing extra packages may error."
    }
}

$env:PYTHONUTF8 = "1"

while ($true) {
    Invoke-WebBuild
    Invoke-AppPyDeps

    # The agent mounts /assets from web/dist/assets and exits non-zero if it's
    # missing. Without this guard a failed build would crash-loop here forever.
    if (-not (Test-Path (Join-Path $WebDir "dist\assets"))) {
        Log "FATAL: web/dist/assets is missing - the web UI build produced no output."
        Log "Fix the build error shown above, then re-run. Common causes: web deps not"
        Log "installed (run 'npm ci' in web/), or a packaged-app dependency failed to install."
        exit 1
    }

    # Initialise the database (idempotent - fast no-op after first run).
    # Set $env:SKIPPERBOT_SKIP_INIT_DB = "1" to skip.
    if (-not ($env:SKIPPERBOT_SKIP_INIT_DB -eq "1")) {
        Log "running scripts\init_db.py ..."
        & $Python (Join-Path $AppRoot "scripts\init_db.py")
        if ($LASTEXITCODE -ne 0) {
            Log "ERROR: init_db.py failed; not starting the agent."
            exit 1
        }
    }

    $portLine = (Get-Content (Join-Path $AppRoot ".env") | Where-Object { $_ -match '^\s*SKIPPERBOT_PORT\s*=' } | Select-Object -First 1)
    $port = if ($portLine) { ($portLine -split '=', 2)[1].Trim() } else { "8000" }
    Log "starting agent on :$port"
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
