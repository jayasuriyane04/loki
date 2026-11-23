# Stops LOKI (used by the "Stop LOKI" desktop shortcut): the backend and app containers, and LOKI's own Ollama on
# port 11435 (which frees the GPU memory). The database and web search keep running; they use little and hold
# your data. Your normal Ollama app (port 11434), if any, is not touched.

$Root = Split-Path -Parent $PSScriptRoot
$Host.UI.RawUI.WindowTitle = "Stopping LOKI"
Write-Host ""
Write-Host "  Stopping LOKI..." -ForegroundColor Cyan

$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if (-not (Test-Path $docker)) { $docker = (Get-Command docker -ErrorAction SilentlyContinue).Source }
if ($docker) {
    & $docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        Push-Location $Root
        & $docker compose stop backend frontend *> $null
        Pop-Location
        Write-Host "  [ok] App stopped" -ForegroundColor Green
    }
}

$conn = Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue
foreach ($procId in ($conn | Select-Object -ExpandProperty OwningProcess -Unique)) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "ollama*") {
        Stop-Process -Id $procId -Force
        Write-Host "  [ok] Model server stopped (GPU memory freed)" -ForegroundColor Green
    }
}
Start-Sleep -Seconds 2
