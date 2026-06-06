# =============================================================================
# skipper.ps1 - Windows PowerShell launcher for the Skipperbot platform
# =============================================================================
# After cloning the repo, run this script. Behaviour:
#
#   * First run (no usable .env): asks for your OpenAI key and a Postgres
#     password, writes .env, then starts Skipper.
#   * Later runs: just starts Skipper - via Docker if available, otherwise
#     natively (start_agent.ps1).
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
$REPO = (Resolve-Path "$ScriptPath/../../" -Resolve).Path
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

    Ok ".env written (the secret-encryption key is auto-generated on first boot)."
}

# --- start / stop -----------------------------------------------------------
function Start-Skipper {
    if (HasDocker) {
        Log "Starting Skipper via Docker (docker compose up -d) - first boot builds the UI, can take a few minutes..."
        docker compose up -d
        Ok "Skipper is starting. Open http://localhost:8000   (follow logs: skipper logs)"
    }
    else {
        Warn "Docker not found - starting natively via start_agent.ps1."
        $agentScript = "$REPO/start_agent.ps1"
        if (-not (Test-Path $agentScript)) {
            Die "start_agent.ps1 not found. See README 'Path 2: Native install'."
        }
        Log "Running start_agent.ps1..."
        & $agentScript
    }
}

function Stop-Skipper {
    if (HasDocker) {
        Log "Stopping Docker stack (docker compose down)..."
        docker compose down
        Ok "Stopped."
    }
    else {
        Warn "Native run: stop the start_agent.ps1 process."
    }
}

function Show-Logs {
    if (HasDocker) {
        docker compose logs -f agent
    }
    else {
        Warn "For native run, check the start_agent.ps1 output or system logs."
    }
}

function Show-Status {
    if (HasDocker) {
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
    & "$REPO/scripts/update_server.sh"
}

function Show-Usage {
    $usage = @"
skipper - launch and manage the Skipperbot platform (Windows PowerShell)

Usage: powershell -ExecutionPolicy Bypass -File skipper.ps1 [command]

  (no command)   First-run setup if needed, then start Skipper.
  setup          (Re)configure .env (OpenAI key + Postgres password).
  start          Start Skipper (Docker if available, else native).
  stop           Stop the Docker stack.
  restart        Restart (stop + start).
  update         git pull + recycle.
  logs           Follow the agent logs.
  status         Show container + health status.
  help           Show this help.

Note: To run from anywhere, create a batch file wrapper in your PATH.
"@
    Write-Host $usage
}

# --- dispatch ---------------------------------------------------------------
switch -Wildcard ($Command) {
    "" { 
        if (NeedsSetup) { Setup }
        Start-Skipper
    }
    "setup" { Setup }
    "start" { Start-Skipper }
    "stop" { Stop-Skipper }
    "restart" { Stop-Skipper; Start-Skipper }
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
