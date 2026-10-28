@echo off
rem Double-clickable Windows launcher (equivalent of run.command). Starts the bridge and opens the browser.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
rem Fallback if PowerShell is blocked: start "" .venv\Scripts\python.exe server\bridge.py  then  start "" http://127.0.0.1:8730/
