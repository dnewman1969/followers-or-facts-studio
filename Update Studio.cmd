@echo off
rem Gets the newest version of the Studio, updates its packages, and (re)makes the desktop icon.
rem Double-click this whenever Claude has pushed changes.
cd /d "%~dp0"
echo Getting the newest version...
git pull
if errorlevel 1 (
  echo.
  echo Couldn't download the update. Check your internet connection and try again.
  pause
  exit /b 1
)
echo Updating packages...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
echo Checking the data folder and database...
".venv\Scripts\python.exe" -m fofstudio init
echo Checking the narration voice...
".venv\Scripts\python.exe" -m fofstudio download-models
echo Making the desktop icon...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\make-shortcut.ps1"
echo.
echo Done. Double-click "Followers or Facts Studio" on your desktop.
pause
