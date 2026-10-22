@echo off
rem Opens Followers or Facts Studio. Run setup.ps1 once first.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup.ps1 first:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m fofstudio app
