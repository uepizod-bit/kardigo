@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Avval install_windows.bat ni ishga tushiring.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m kadrgo %*
