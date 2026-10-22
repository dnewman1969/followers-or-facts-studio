<#
  Followers or Facts Studio - one-time setup for Windows 11.

  Run from the repo folder in PowerShell:
      powershell -ExecutionPolicy Bypass -File .\setup.ps1

  Options:
      -DataDir "F:\AI\fof-data"   where episodes, the database and voice models live
      -YouTube                    also install the YouTube upload packages
      -Chatterbox                 also install voice cloning (needs ~6 GB VRAM, CUDA PyTorch)
      -ComfyModels                also download the Wan 2.2 + ACE-Step models into ComfyUI (~45 GB)
#>
param(
    [string]$DataDir = "F:\AI\fof-data",
    [string]$ComfyDir = "F:\AI\ComfyUI",
    [switch]$YouTube,
    [switch]$Chatterbox,
    [switch]$ComfyModels
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($text) { Write-Host "`n== $text" -ForegroundColor Yellow }

Step "Python 3.12"
$py = $null
try { & py -3.12 --version | Out-Null; $py = "py -3.12" } catch {}
if (-not $py) {
    Write-Host "Python 3.12 not found. Installing it with winget..."
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $py = "py -3.12"
}

Step "Virtual environment (.venv) - keeps this app's packages away from ComfyUI's"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Invoke-Expression "$py -m venv .venv"
}
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt
if ($YouTube) { & $venvPy -m pip install -r requirements-youtube.txt }
if ($Chatterbox) {
    & $venvPy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
    & $venvPy -m pip install -r requirements-chatterbox.txt
}

Step "ffmpeg"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ffmpeg not found. Installing it with winget (open a new PowerShell afterwards)..."
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
}

Step "Data folder: $DataDir"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path "config" | Out-Null
Set-Content -Path "config\data-dir.txt" -Value $DataDir -Encoding UTF8
& $venvPy -m fofstudio init

Step "Kokoro narration voice (~340 MB)"
& $venvPy -m fofstudio download-models

if ($ComfyModels) {
    Step "ComfyUI models for animation and music"
    & powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\scripts\get-comfy-models.ps1" -ComfyDir $ComfyDir
}

Step "Desktop icon"
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\scripts\make-shortcut.ps1"

Step "Check everything"
& $venvPy -m fofstudio doctor
Write-Host "`nDone. Double-click 'Followers or Facts Studio' on your desktop. It starts Ollama and ComfyUI for you." -ForegroundColor Green
