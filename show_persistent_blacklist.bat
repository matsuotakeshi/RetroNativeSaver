@echo off
setlocal
cd /d "%~dp0"
set "STATE=%~dp0state\persistent_rom_blacklist.json"

if not exist "%STATE%" (
  echo No persistent ROM blacklist state exists yet.
  echo.
  echo Expected:
  echo   %STATE%
  pause
  exit /b 0
)

notepad "%STATE%"
