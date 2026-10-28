# Windows launcher: starts the bridge in the background and opens the widget in the default browser.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$port = 8730
try { $c = Get-Content server\config.json -Raw | ConvertFrom-Json; if ($c.server.port) { $port = $c.server.port } } catch {}
if (-not (Test-Path "server\config.json")) { Copy-Item server\config.example.json server\config.json }
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Write-Host "No .venv - run setup.bat first."; Read-Host "Press Enter"; exit 1 }
$log = Join-Path $env:TEMP "voice-widget.log"
# bridge.py loads server\.env itself (no 'source' on Windows)
Start-Process -FilePath $vpy -ArgumentList "bridge.py" -WorkingDirectory (Join-Path $PSScriptRoot "server") `
  -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err"
$url = "http://127.0.0.1:$port/"
for ($i=0; $i -lt 60; $i++) {
  try { Invoke-WebRequest "$url`health" -UseBasicParsing -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep -Milliseconds 300 }
}
Start-Process $url
Write-Host "Voice widget running at $url  (log: $log). Stop it with stop.bat or Task Manager (python.exe)."
