# One-command install for Windows (PowerShell). Mirrors setup.sh. Idempotent: safe to re-run.
# Run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1     (or double-click setup.bat)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "==> voice-widget setup (Windows)"

# 1. Python 3.10-3.12 via the py launcher (kokoro requires <3.13)
$py = $null
foreach ($v in "3.12","3.11","3.10") {
  & py "-$v" -c "import sys" 2>$null
  if ($LASTEXITCODE -eq 0) { $py = $v; break }
}
if (-not $py) {
  Write-Host "Need Python 3.10-3.12 (kokoro supports <3.13). Install from python.org (tick 'py launcher'),"
  Write-Host "or: winget install Python.Python.3.12   then re-run."; exit 1
}
Write-Host "==> using Python $py (py -$py)"

# 2. espeak-ng: GPL-3.0, installed SEPARATELY by you, never bundled. We only check for it.
$dll = Join-Path $env:ProgramFiles "eSpeak NG\libespeak-ng.dll"
if (Test-Path $dll) { Write-Host "==> espeak-ng found: $dll" }
else {
  Write-Host "!! espeak-ng not found. Install ONE of:"
  Write-Host "     choco install espeak-ng            (community package, admin shell)"
  Write-Host "     MSI: https://github.com/espeak-ng/espeak-ng/releases  (espeak-ng.msi, X64)"
  Write-Host "   Then re-run. (The bridge auto-sets PHONEMIZER_ESPEAK_LIBRARY to the default path.)"
}

# 3. venv + deps
if (-not (Test-Path ".venv")) { & py "-$py" -m venv .venv }
$vpy = ".\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip | Out-Null
# CPU torch wheel first (small, no CUDA). For an NVIDIA GPU instead:
#   .\.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu124
& $vpy -m pip install torch --index-url https://download.pytorch.org/whl/cpu
& $vpy -m pip install -r server\requirements.txt
& $vpy -m pip install huggingface_hub   # setup-time only; runtime stays offline

# 4. config
if (-not (Test-Path "server\config.json")) { Copy-Item server\config.example.json server\config.json }
if (-not (Test-Path "server\.env"))        { Copy-Item server\.env.example server\.env }

Write-Host ""
Write-Host "==> setup complete. Next, fetch models (weights are downloaded, not bundled):"
Write-Host "     .\.venv\Scripts\python server\fetch_models.py --kokoro --voice af_heart"
Write-Host "     .\.venv\Scripts\python server\fetch_models.py --stt-browser whisper-base-onnx"
Write-Host "   Then start: double-click run.bat"
