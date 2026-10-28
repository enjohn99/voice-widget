# Headless/advanced start on Windows (equivalent of server/run.sh). Foreground; Ctrl+C to stop.
Set-Location $PSScriptRoot
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json }
& (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe") bridge.py
