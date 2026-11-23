# One-click start for LOKI (used by the "LOKI" desktop shortcut).
#
#   1. LOKI's Ollama on the NVIDIA GPU (port 11435), hidden in the background
#   2. Docker Desktop, if it isn't running yet
#   3. The LOKI containers: database, web search, backend (8100) and app (3100)
#   4. Waits until everything answers, then opens LOKI in your browser
#
# Safe to run when LOKI is already up: it only starts what isn't running.
# Logs: %LOCALAPPDATA%\LOKI\logs

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $env:LOCALAPPDATA "LOKI\logs"
New-Item -ItemType Directory -Force $Logs | Out-Null
$Host.UI.RawUI.WindowTitle = "Starting LOKI"

function Step($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  [ok] $text" -ForegroundColor Green }

function Test-Port([int]$port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.ConnectAsync("127.0.0.1", $port).Wait(500) -and $c.Connected } catch { $false } finally { $c.Dispose() }
}

function Wait-Url([string]$url, [int]$seconds, [string]$what) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -lt 500) { return }
        } catch { }
        Start-Sleep -Milliseconds 800
    }
    throw "$what did not start within $seconds seconds."
}

function Invoke-Docker {
    # Docker prints progress on stderr; Windows PowerShell 5.1 would treat that as an error under "Stop".
    # Success is decided by the exit code instead.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $script:docker @args 2>&1 | Out-String } finally { $ErrorActionPreference = $saved }
}

function Fail($message) {
    Write-Host ""
    Write-Host "  LOKI could not start: $message" -ForegroundColor Red
    Write-Host "  Logs: $Logs" -ForegroundColor DarkGray
    Write-Host ""
    Read-Host "  Press Enter to close"
    exit 1
}

Write-Host ""
Write-Host "  L O K I" -ForegroundColor White
Write-Host ""

try {
    # 1. Ollama (LOKI's own instance: NVIDIA GPU only, see start-ollama.ps1)
    if (Test-Port 11435) {
        Ok "Model server already running"
    } else {
        Step "Starting the model server (NVIDIA GPU)..."
        $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (-not (Test-Path $ollama)) { $ollama = (Get-Command ollama -ErrorAction Stop).Source }
        $env:OLLAMA_HOST = "127.0.0.1:11435"
        $env:HIP_VISIBLE_DEVICES = "-1"     # hide the AMD iGPU from this process only
        $env:ROCR_VISIBLE_DEVICES = "-1"
        $env:OLLAMA_KEEP_ALIVE = "30m"
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Logs "ollama.out.log") -RedirectStandardError (Join-Path $Logs "ollama.log")
        Wait-Url "http://127.0.0.1:11435/api/tags" 60 "The model server"
        Ok "Model server ready"
    }

    # 2. Docker Desktop
    $script:docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (-not (Test-Path $script:docker)) { $script:docker = (Get-Command docker -ErrorAction Stop).Source }
    Invoke-Docker info | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Step "Starting Docker Desktop (this can take a minute)..."
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        $deadline = (Get-Date).AddMinutes(4)
        do {
            Start-Sleep -Seconds 3
            Invoke-Docker info | Out-Null
        } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
        if ($LASTEXITCODE -ne 0) { throw "Docker Desktop did not start." }
    }
    Ok "Docker ready"

    # 3. Containers (images are built on first run if missing)
    Step "Starting LOKI..."
    Push-Location $Root
    try {
        Invoke-Docker compose --profile app up -d | Set-Content (Join-Path $Logs "compose.log")
        if ($LASTEXITCODE -ne 0) { throw "docker compose failed (see compose.log)." }
    } finally { Pop-Location }

    # 4. Wait until it answers
    Step "Waiting for LOKI to be ready (speech models load in the background)..."
    Wait-Url "http://127.0.0.1:8100/api/health" 240 "The LOKI backend"
    Wait-Url "http://127.0.0.1:3100" 120 "The LOKI app"
    Ok "LOKI is ready"

    Start-Process "http://localhost:3100"
    Start-Sleep -Seconds 2
} catch {
    Fail $_.Exception.Message
}
