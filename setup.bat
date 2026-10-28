@echo off
rem Double-clickable Windows setup. Wraps setup.ps1 (bypasses the default script execution policy for this run only).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
pause
