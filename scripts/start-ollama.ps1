# Starts LOKI's own Ollama server on the NVIDIA GPU.
#
# Why: this laptop also has an AMD Radeon 880M integrated GPU. It borrows system RAM and reports more
# memory than the RTX 5060, so a default Ollama picks it and runs ~3.6x slower (23 vs 83 tokens/s).
# The variables below hide the AMD GPU from this one process only; system settings and your normal
# Ollama app (port 11434) are untouched. Models on disk are shared, so nothing is downloaded twice.
#
# Usage (keep this window open while using LOKI):
#   powershell -ExecutionPolicy Bypass -File scripts\start-ollama.ps1

$ErrorActionPreference = "Stop"
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollama)) { $ollama = (Get-Command ollama -ErrorAction Stop).Source }

$env:OLLAMA_HOST = "127.0.0.1:11435"   # must match OLLAMA_BASE_URL in backend\.env
$env:HIP_VISIBLE_DEVICES = "-1"         # hide AMD GPU from the ROCm backend
$env:ROCR_VISIBLE_DEVICES = "-1"
$env:OLLAMA_KEEP_ALIVE = "30m"          # keep the model in VRAM between conversations

Write-Host "Starting LOKI's Ollama on http://$($env:OLLAMA_HOST) (NVIDIA GPU only)..."
& $ollama serve
