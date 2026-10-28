@echo off
rem Stops the voice-widget bridge started by run.bat (matches python running bridge.py only).
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name=python.exe\" | Where-Object { $_.CommandLine -like *bridge.py* } | ForEach-Object { Stop-Process -Id $_.ProcessId }"
