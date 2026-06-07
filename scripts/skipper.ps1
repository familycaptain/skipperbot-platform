# =============================================================================
# skipper.ps1 - Windows PowerShell launcher for the Skipperbot platform
# =============================================================================
# After cloning the repo, run this script. Behaviour:
#
#   * Every start/setup first ASKS how to run Skipper - Docker or native -
#     and verifies that runtime's prerequisites before doing anything else.
#       - Docker: bundles Postgres + Python + Node in containers (recommended).
#       - Native: runs on the host; you must already have PostgreSQL 18 +
#         pgvector, Python 3.12, and Node 24+ installed. The launcher then
#         installs the project's own deps for you (venv + pip + npm ci).
#   * First run (no usable .env): asks for your OpenAI key and a Postgres
#     password, writes .env, then starts Skipper.
#   * Later runs: just starts Skipper.
#
# Subcommands: setup | start | stop | restart | update | logs | status | help
#              (no subcommand = setup-if-needed + start)
# =============================================================================

param(
    [string]$Command = ""
)

# --- locate the repo root ---------------------------------------------------
$ScriptPath = $MyInvocation.MyCommand.Path
if ($null -eq $ScriptPath) { $ScriptPath = $MyInvocation.MyCommand.Definition }
$REPO = (Resolve-Path (Join-Path (Split-Path -Parent $ScriptPath) "..")).Path
Set-Location $REPO

$ENV_FILE = "$REPO\.env"
$EXAMPLE_ENV = "$REPO\.env.example"

# --- pretty output ----------------------------------------------------------
function Log {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Blue
}

function Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Warn {
    param([string]$Message)
    Write-Host "! $Message" -ForegroundColor Yellow
}

function Die {
    param([string]$Message)
    Write-Host "[X] $Message" -ForegroundColor Red -ErrorAction Stop
    exit 1
}

function Confirm {
    param([string]$Question)
    $reply = Read-Host "$Question [Y/n]"
    return ($reply -eq "" -or $reply -match "^[Yy]")
}

# --- runtime selection ------------------------------------------------------
# skipper supports two runtimes:
#   docker - bundles Postgres + Python + Node in containers (recommended)
#   native - runs on the host; YOU must have Postgres/Python/Node installed
# We always ASK which one to use, then verify that runtime's prerequisites
# before doing anything else (so we never get half-way and then fail).
function Resolve-Runtime {
    if ($script:Runtime) { return $script:Runtime }
    $dockerAvailable = HasDocker
    Write-Host ""
    Log "How do you want to run Skipper?"
    Write-Host "  [D] Docker - bundles Postgres 18 + pgvector, Python, and Node in containers."
    if ($dockerAvailable) {
        Write-Host "      Recommended. Docker was detected on this machine." -ForegroundColor Green
    }
    else {
        Write-Host "      Recommended, but Docker was NOT detected - you'd install Docker Desktop first." -ForegroundColor Yellow
    }
    Write-Host "  [N] Native - run directly on this machine. You must ALREADY have"
    Write-Host "      PostgreSQL 18 + pgvector, Python 3.12, and Node 24+ installed."
    $reply = Read-Host "Choose D or N (default D)"
    if ([string]::IsNullOrWhiteSpace($reply)) { $reply = "D" }
    switch -Regex ($reply) {
        "^[Dd]" { $script:Runtime = "docker" }
        "^[Nn]" { $script:Runtime = "native" }
        default { Die "Unrecognized choice '$reply'. Run again and enter D (Docker) or N (native)." }
    }
    return $script:Runtime
}

# Prerequisite checks come in two phases:
#   Tooling  - Node + Python; checked BEFORE setup (no .env needed), so we
#              never ask for your OpenAI key on a machine that can't run.
#   Database - Postgres reachability; checked AFTER setup, because setup is
#              what asks you for the DB host and writes it into .env.
# For native, the tooling phase auto-installs the project's own deps (venv, pip,
# npm ci) but never the system runtimes (Node/Python/Postgres - those are yours).
function Ensure-RuntimeTooling {
    $rt = Resolve-Runtime
    if ($rt -eq "docker") { Require-Docker } else { Require-NativeTooling }
    return $rt
}

function Ensure-RuntimeDatabase {
    $rt = Resolve-Runtime
    if ($rt -eq "native") { Require-NativeDatabase }
    # Docker: Postgres runs in the bundled 'db' container, started by
    # 'docker compose up' - nothing to verify on the host.
}

function Require-Docker {
    if (-not (HasDocker)) {
        Write-Host ""
        Warn "You chose Docker, but 'docker compose' isn't available on this machine."
        Write-Host "   Install Docker Desktop (Windows/macOS) from https://docs.docker.com/desktop/,"
        Write-Host "   then re-run this script. Verify with:  docker run --rm hello-world"
        Write-Host ""
        Die "Docker not found. Install it, or re-run and choose Native."
    }
    Ok "Docker detected."
}

# Where will the native agent look for Postgres? Mirrors data_layer/dsn.py:
# an explicit SKIPPERBOT_DB_DSN wins; otherwise host/port default to the
# docker-compose 'db' service - which is wrong for a native run.
function Get-NativeDbTarget {
    $dsn = EnvGet "SKIPPERBOT_DB_DSN"
    if (-not [string]::IsNullOrWhiteSpace($dsn)) {
        $h = "localhost"
        $p = 5432
        if ($dsn -match "host=([^\s]+)") { $h = $Matches[1] }
        if ($dsn -match "port=([0-9]+)") { $p = [int]$Matches[1] }
        if ($dsn -match "://[^/@]+@([^:/]+):([0-9]+)") { $h = $Matches[1]; $p = [int]$Matches[2] }
        return @{ DbHost = $h; Port = $p; FromDsn = $true }
    }
    $h = EnvGet "DB_HOST"
    if ([string]::IsNullOrWhiteSpace($h)) { $h = "db" }
    $p = EnvGet "DB_PORT"
    if ([string]::IsNullOrWhiteSpace($p)) { $p = "5432" }
    return @{ DbHost = $h; Port = [int]$p; FromDsn = $false }
}

function Test-TcpPort {
    param([string]$DbHost, [int]$Port, [int]$TimeoutMs = 3000)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($DbHost, $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($ok -and $client.Connected) {
            $client.EndConnect($iar)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    }
    catch {
        return $false
    }
}

# Run a Python script with the venv interpreter and capture stdout+stderr+exit
# WITHOUT PowerShell 5.1's "NativeCommandError" noise - it wraps a native
# command's stderr as a red error for BOTH 2>&1 and 2>file. Start-Process with
# redirected files captures the raw streams cleanly. Returns { Code; Output }.
function Invoke-CapturedPython {
    param([string]$PythonExe, [string[]]$Arguments)
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $argString = ($Arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $p = Start-Process -FilePath $PythonExe -ArgumentList $argString -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $code = $p.ExitCode
        $stdout = (Get-Content -Raw -Path $outFile -ErrorAction SilentlyContinue)
        $stderr = (Get-Content -Raw -Path $errFile -ErrorAction SilentlyContinue)
    }
    finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
    $text = (@($stderr, $stdout) | Where-Object { $_ } | ForEach-Object { $_.Trim() }) -join "`n"
    return [pscustomobject]@{ Code = $code; Output = $text.Trim() }
}

# Locate a Python 3.12 interpreter to build the venv with. Returns an object
# { Cmd = <exe>; Pre = <leading args> } or $null. Prefers the 'py -3.12' launcher.
function Find-Python312 {
    foreach ($cand in @(
            @{ Cmd = "py";         Pre = @("-3.12") },
            @{ Cmd = "python3.12"; Pre = @() },
            @{ Cmd = "python";     Pre = @() })) {
        try {
            $v = (& $cand.Cmd @($cand.Pre + @("--version"))) 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -match "3\.12") {
                return [pscustomobject]@{ Cmd = $cand.Cmd; Pre = $cand.Pre }
            }
        }
        catch { }
    }
    return $null
}

# Checks the system runtimes (Node 24+, Python 3.12) - which the user must
# install themselves - and then AUTO-INSTALLS the project's own dependencies
# (creates the venv, pip install, npm ci) when those runtimes are present.
function Require-NativeTooling {
    Log "Native run selected - checking runtimes; project dependencies are installed for you..."
    $problems = @()

    # --- Node.js >= 24 (system runtime; must match web/package.json "engines") ---
    $node = $null
    try { $node = (& node --version) 2>$null } catch { $node = $null }
    $nodeOk = $false
    if ([string]::IsNullOrWhiteSpace($node)) {
        $problems += "Node.js not found. Install Node.js 24 LTS or newer from https://nodejs.org/ (needed to build the web UI)."
    }
    else {
        $major = 0
        [void][int]::TryParse($node.TrimStart("v").Split(".")[0], [ref]$major)
        if ($major -lt 24) {
            $problems += "Node.js 24+ required (found $node). Update from https://nodejs.org/."
        }
        else {
            Ok "Node.js $node"
            $nodeOk = $true
        }
    }

    # --- Python 3.12 venv (auto-created) ---
    # The platform pins 3.12 (pyproject.toml requires-python ==3.12.*); newer
    # versions (3.13/3.14) are unsupported and break the voice companion's deps.
    $venvPython = Join-Path $REPO ".venv\Scripts\python.exe"
    $pyOk = $false
    if (Test-Path $venvPython) {
        $pyver = (& $venvPython --version) 2>$null
        if ($pyver -notmatch "3\.12") {
            $problems += "Project requires Python 3.12, but .venv is '$pyver' (3.13/3.14 unsupported). Remove it and re-run:  Remove-Item -Recurse -Force .venv"
        }
        else {
            Ok "Python virtual-env present ($pyver)"
            $pyOk = $true
        }
    }
    else {
        $py312 = Find-Python312
        if ($null -eq $py312) {
            $problems += "Python 3.12 not found. Install it from https://www.python.org/downloads/ (the Windows installer registers it as 'py -3.12')."
        }
        else {
            Log "Creating Python 3.12 virtual-env (.venv)..."
            & $py312.Cmd @($py312.Pre + @("-m", "venv", (Join-Path $REPO ".venv")))
            if (Test-Path $venvPython) {
                Ok "Created .venv (Python 3.12)"
                $pyOk = $true
            }
            else {
                $problems += "Failed to create the Python 3.12 virtual-env. Create it by hand:  py -3.12 -m venv .venv"
            }
        }
    }

    # --- Python dependencies (auto-installed into the venv) ---
    if ($pyOk) {
        $hasDeps = $false
        try { & $venvPython -c "import fastapi" 2>$null; $hasDeps = ($LASTEXITCODE -eq 0) } catch { $hasDeps = $false }
        if ($hasDeps) {
            Ok "Python dependencies installed"
        }
        else {
            Log "Installing Python dependencies (pip install -r requirements.txt)..."
            & $venvPython -m pip install -r (Join-Path $REPO "requirements.txt")
            if ($LASTEXITCODE -eq 0) {
                Ok "Python dependencies installed"
            }
            else {
                $problems += "Python dependency install failed. Run it by hand:  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
            }
        }
    }

    # --- Web UI dependencies (auto npm ci; needed by start_agent.ps1's build) ---
    if ($nodeOk) {
        if (Test-Path (Join-Path $REPO "web\node_modules\vite")) {
            Ok "Web UI dependencies installed"
        }
        elseif (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            $problems += "npm not found on PATH (it ships with Node.js). Reinstall Node 24+ from https://nodejs.org/, then re-run."
        }
        else {
            Log "Installing web UI dependencies (npm ci) - first time can take a minute or two..."
            $npmCode = 1
            Push-Location (Join-Path $REPO "web")
            try {
                & npm ci
                $npmCode = $LASTEXITCODE
            }
            finally {
                Pop-Location
            }
            if ($npmCode -eq 0 -and (Test-Path (Join-Path $REPO "web\node_modules\vite"))) {
                Ok "Web UI dependencies installed"
            }
            else {
                $problems += "Web UI dependency install (npm ci) failed. Run it by hand:  Push-Location web ;  npm ci ;  Pop-Location"
            }
        }
    }

    if ($problems.Count -gt 0) {
        Write-Host ""
        Warn "Native prerequisites are not satisfied:"
        foreach ($p in $problems) { Write-Host "   - $p" -ForegroundColor Yellow }
        Write-Host ""
        Die "Install the missing runtimes above, then re-run 'skipper' (it installs the project dependencies for you). Or choose Docker. Full native guide: docs/01-base-platform-setup.md"
    }
    Ok "Node + Python ready (project dependencies installed)."
}

# Checked AFTER setup, so the host/port reflect what you were asked for and
# .env now contains (setup writes DB_HOST/DB_PORT for a native run). The DB may
# live on THIS machine or on another server on your network. We do a REAL
# connection test (psycopg2 via the venv) and, if the database/role/pgvector
# aren't set up yet, offer to create them for you with a superuser login.
function Require-NativeDatabase {
    $target = Get-NativeDbTarget
    if (-not $target.FromDsn -and $target.DbHost -eq "db") {
        Write-Host ""
        Die "Postgres host is still 'db' (the Docker service name), which won't work natively. Re-run 'skipper setup' and enter your Postgres host. See docs/01-base-platform-setup.md step 6."
    }

    $venvPython = Join-Path $REPO ".venv\Scripts\python.exe"
    $checkScript = Join-Path $REPO "scripts\check_db_connection.py"

    if (-not ((Test-Path $venvPython) -and (Test-Path $checkScript))) {
        # Fallback: TCP-only reachability (venv not usable for a real check).
        if (Test-TcpPort -DbHost $target.DbHost -Port $target.Port) {
            Ok "PostgreSQL reachable at $($target.DbHost):$($target.Port) (TCP only - credentials unverified)"
            return
        }
        Write-Host ""
        Die "Cannot reach PostgreSQL at $($target.DbHost):$($target.Port). Start it (or fix the host), then re-run 'skipper'. Your .env is already written."
    }

    $res = Invoke-CapturedPython -PythonExe $venvPython -Arguments @($checkScript)
    $err = $res.Output
    $code = $res.Code
    if ($code -eq 0) {
        Ok "PostgreSQL ready at $($target.DbHost):$($target.Port) (connected, pgvector present)."
        return
    }
    if ($code -eq 2) {
        # Env problem (shouldn't happen - tooling check ensures deps). Degrade to TCP.
        if (Test-TcpPort -DbHost $target.DbHost -Port $target.Port) {
            Ok "PostgreSQL reachable at $($target.DbHost):$($target.Port) (could not fully verify)."
            return
        }
        Die "Cannot reach PostgreSQL at $($target.DbHost):$($target.Port). $err"
    }

    # code 1 = can't connect (role/db missing or wrong password);
    # code 4 = connected but pgvector not installed. Either way, offer to fix it.
    Write-Host ""
    Warn "PostgreSQL is reachable but not set up for Skipper yet:"
    Write-Host "   $err" -ForegroundColor Yellow
    Invoke-NativeDbBootstrap -Target $target -VenvPython $venvPython -CheckScript $checkScript
}

# Offer to create the role + database + pgvector with a superuser login. The
# superuser password is passed to the helper via an environment variable (never
# stored, never on a command line) and cleared immediately after.
function Invoke-NativeDbBootstrap {
    param($Target, $VenvPython, $CheckScript)

    Write-Host ""
    Write-Host "Skipper can set this up for you: it will create the 'skipperbot' role + database"
    Write-Host "+ the pgvector extension on $($Target.DbHost), using your PostgreSQL superuser login."
    if (-not (Confirm "Set up the database now?")) {
        Write-Host ""
        Write-Host "To do it by hand, connect as the postgres superuser and run:" -ForegroundColor Yellow
        Write-Host "  CREATE USER skipperbot_user WITH PASSWORD '<the password you entered>';" -ForegroundColor Yellow
        Write-Host "  CREATE DATABASE skipperbot OWNER skipperbot_user;" -ForegroundColor Yellow
        Write-Host "  \c skipperbot" -ForegroundColor Yellow
        Write-Host "  CREATE EXTENSION IF NOT EXISTS vector;" -ForegroundColor Yellow
        Write-Host "Then re-run 'skipper'. Full guide: docs/01-base-platform-setup.md steps 1-3." -ForegroundColor Yellow
        Write-Host ""
        Die "Database not set up yet."
    }

    $suUser = Read-Host "PostgreSQL superuser name [postgres]"
    if ([string]::IsNullOrWhiteSpace($suUser)) { $suUser = "postgres" }
    $suSecure = Read-Host "Password for '$suUser'" -AsSecureString
    $suPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($suSecure))

    $env:SKIPPER_SUPERUSER = $suUser
    $env:SKIPPER_SUPERPASS = $suPass
    try {
        $res = Invoke-CapturedPython -PythonExe $VenvPython -Arguments @((Join-Path $REPO "scripts\bootstrap_db.py"))
        $out = $res.Output
        $code = $res.Code
    }
    finally {
        Remove-Item Env:SKIPPER_SUPERPASS -ErrorAction SilentlyContinue
        Remove-Item Env:SKIPPER_SUPERUSER -ErrorAction SilentlyContinue
        $suPass = $null
    }
    if ($out) { Write-Host $out }

    switch ($code) {
        0 {
            $verify = Invoke-CapturedPython -PythonExe $VenvPython -Arguments @($CheckScript)
            if ($verify.Code -eq 0) {
                Ok "Database is ready (role + database + pgvector created)."
                return
            }
            Die "Database was created but the app user still can't connect. Check .env, then re-run 'skipper'."
        }
        3 {
            Write-Host ""
            Warn "pgvector isn't installed on this PostgreSQL server, so a native install can't finish here."
            Write-Host "   pgvector has no prebuilt Windows package. Easiest options:" -ForegroundColor Yellow
            Write-Host "   - Re-run 'skipper' and choose Docker (it bundles Postgres 18 + pgvector)." -ForegroundColor Yellow
            Write-Host "   - Or point at a Postgres on your network that already has pgvector:" -ForegroundColor Yellow
            Write-Host "     run 'skipper setup' and enter that host." -ForegroundColor Yellow
            Write-Host "   - Or build pgvector from source for Windows (advanced): https://github.com/pgvector/pgvector" -ForegroundColor Yellow
            Write-Host ""
            Die "pgvector required but not available on this server."
        }
        1 {
            Die "Could not log in as superuser '$suUser'. Re-run 'skipper' and try again, or set the database up by hand (docs/01-base-platform-setup.md steps 1-3)."
        }
        default {
            Die "Database setup didn't complete (see the message above). You can set it up by hand per docs/01-base-platform-setup.md steps 1-3, then re-run 'skipper'."
        }
    }
}

# --- helpers ----------------------------------------------------------------
function HasDocker {
    $docker = $null
    try {
        $docker = docker compose version 2>$null
    }
    catch {
        return $false
    }
    return ($null -ne $docker)
}

function EnvGet {
    param([string]$Key)
    if (-not (Test-Path $ENV_FILE)) { return "" }
    $line = Get-Content $ENV_FILE | Where-Object { $_ -match "^$Key=" } | Select-Object -First 1
    if ($line) {
        return $line.Split("=", 2)[1]
    }
    return ""
}

function SetEnv {
    param([string]$Key, [string]$Value)
    
    $lines = @()
    $found = $false
    
    if (Test-Path $ENV_FILE) {
        $lines = @(Get-Content $ENV_FILE)
    }
    
    $newLines = @()
    foreach ($line in $lines) {
        if ($line -match "^$Key=") {
            $newLines += "$Key=$Value"
            $found = $true
        }
        else {
            $newLines += $line
        }
    }
    
    if (-not $found) {
        $newLines += "$Key=$Value"
    }
    
    $newLines | Out-File -FilePath $ENV_FILE -Encoding UTF8
}

function NeedsSetup {
    if (-not (Test-Path $ENV_FILE)) { return $true }
    $key = EnvGet "OPENAI_API_KEY"
    if ($key -eq "") { return $true }
    $pw = EnvGet "POSTGRES_PASSWORD"
    if ($pw -eq "" -or $pw -eq "CHANGE_ME") { return $true }
    return $false
}

# --- first-run setup --------------------------------------------------------
function Setup {
    Log "First-time setup - creating $ENV_FILE"
    if (-not (Test-Path $ENV_FILE)) {
        Copy-Item $EXAMPLE_ENV $ENV_FILE
    }

    $key = ""
    while ([string]::IsNullOrWhiteSpace($key)) {
        $key = Read-Host "OpenAI API key (from https://platform.openai.com/api-keys)"
        if ([string]::IsNullOrWhiteSpace($key)) {
            Warn "An OpenAI key is required."
        }
    }

    $pw = ""
    $pw2 = ""
    while ($true) {
        $pw = Read-Host "Choose a Postgres password" -AsSecureString | ForEach-Object { [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($_)) }
        $pw2 = Read-Host "Confirm password" -AsSecureString | ForEach-Object { [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($_)) }
        
        if (-not [string]::IsNullOrWhiteSpace($pw) -and $pw -eq $pw2) {
            break
        }
        Warn "Passwords were empty or didn't match - try again."
    }

    SetEnv "OPENAI_API_KEY" $key
    SetEnv "POSTGRES_PASSWORD" $pw

    # For a native run, ask where Postgres lives and write it into .env so the
    # agent connects to your host DB (not the docker-compose 'db' service).
    # Docker uses the bundled 'db' service automatically, so we don't ask.
    if ((Resolve-Runtime) -eq "native") {
        Write-Host "Where is your PostgreSQL server? Use 'localhost' for this machine, or a"
        Write-Host "hostname/IP for an existing Postgres server on your network."
        $dbHost = Read-Host "Postgres host [localhost]"
        if ([string]::IsNullOrWhiteSpace($dbHost)) { $dbHost = "localhost" }
        $dbPort = Read-Host "Postgres port [5432]"
        if ([string]::IsNullOrWhiteSpace($dbPort)) { $dbPort = "5432" }
        SetEnv "DB_HOST" $dbHost
        SetEnv "DB_PORT" $dbPort
    }

    Ok ".env written (the secret-encryption key is auto-generated on first boot)."
}

# --- start / stop -----------------------------------------------------------
function Start-Skipper {
    $rt = Resolve-Runtime
    if ($rt -eq "docker") {
        Log "Starting Skipper via Docker (docker compose up -d) - first boot builds the UI, can take a few minutes..."
        docker compose up -d
        Ok "Skipper is starting. Open http://localhost:8000   (follow logs: skipper logs)"
    }
    else {
        $agentScript = "$REPO/start_agent.ps1"
        if (-not (Test-Path $agentScript)) {
            Die "start_agent.ps1 not found. See README 'Path 2: Native install'."
        }
        Log "Starting Skipper natively via start_agent.ps1..."
        & $agentScript
    }
}

function Stop-Skipper {
    $rt = Resolve-Runtime
    if ($rt -eq "docker") {
        Log "Stopping Docker stack (docker compose down)..."
        docker compose down
        Ok "Stopped."
    }
    else {
        Warn "Native run: stop the start_agent.ps1 process (Ctrl+C in its window)."
    }
}

function Show-Logs {
    $rt = Resolve-Runtime
    if ($rt -eq "docker") {
        docker compose logs -f agent
    }
    else {
        Warn "For a native run, check the start_agent.ps1 console output."
    }
}

function Show-Status {
    $rt = Resolve-Runtime
    if ($rt -eq "docker") {
        docker compose ps
    }
    Write-Host "Health: " -NoNewline
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/onboarding/status" -TimeoutSec 5 -UseBasicParsing
        Write-Host "HTTP 200"
    }
    catch {
        Write-Host "not responding yet"
    }
}

function Show-Update {
    & "$REPO/scripts/update_server.ps1"
}

function Show-Usage {
    $usage = @"
skipper - launch and manage the Skipperbot platform (Windows PowerShell)

Usage: powershell -ExecutionPolicy Bypass -File skipper.ps1 [command]

  (no command)   Ask Docker-vs-native, verify that runtime's prerequisites,
                 run first-time setup if needed, then start Skipper.
  setup          (Re)configure .env (OpenAI key + Postgres password).
  start          Start Skipper (asks Docker or native first).
  stop           Stop Skipper (Docker stack, or reminds you for native).
  restart        Restart (stop + start).
  update         git pull + recycle.
  logs           Follow the agent logs (Docker).
  status         Show container + health status.
  help           Show this help.

On start/setup you'll be asked how to run Skipper:
  Docker - bundles Postgres + Python + Node in containers (recommended).
  Native - runs on the host; you must have PostgreSQL 18 + pgvector,
           Python 3.12, and Node 24+ installed (see docs/01-base-platform-setup.md).

Note: To run from anywhere, create a batch file wrapper in your PATH.
"@
    Write-Host $usage
}

# --- banner ------------------------------------------------------------------
function Show-Banner {
    $banner = @"
##### #   # ##### ##### ##### ##### ##### ####  ##### #####
#     #  #    #   #   # #   # #     #   # #   # #   #   #
##### ###     #   ##### ##### ####  ##### ####  #   #   #
    # #  #    #   #     #     #     #  #  #   # #   #   #
##### #   # ##### #     #     ##### #   # ####  #####   #
"@
    Write-Host $banner -ForegroundColor Cyan
    Write-Host "An agentic app platform for your family." -ForegroundColor DarkGray
    Write-Host ""
}

# --- dispatch ---------------------------------------------------------------
Show-Banner
switch -Wildcard ($Command) {
    "" {
        Ensure-RuntimeTooling | Out-Null
        if (NeedsSetup) { Setup }
        Ensure-RuntimeDatabase
        Start-Skipper
    }
    "setup" { Ensure-RuntimeTooling | Out-Null; Setup; Ensure-RuntimeDatabase }
    "start" { Ensure-RuntimeTooling | Out-Null; if (NeedsSetup) { Setup }; Ensure-RuntimeDatabase; Start-Skipper }
    "stop" { Stop-Skipper }
    "restart" { Ensure-RuntimeTooling | Out-Null; if (NeedsSetup) { Setup }; Ensure-RuntimeDatabase; Stop-Skipper; Start-Skipper }
    "update" { Show-Update }
    "logs" { Show-Logs }
    "status" { Show-Status }
    "help" { Show-Usage }
    default { 
        Warn "Unknown command: $Command"
        Show-Usage
        exit 1
    }
}
