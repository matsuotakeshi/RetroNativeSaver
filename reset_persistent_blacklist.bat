@echo off
setlocal
cd /d "%~dp0"
set "STATE=%~dp0state\persistent_rom_blacklist.json"

if not exist "%STATE%" (
  echo Persistent ROM blacklist is already empty.
  pause
  exit /b 0
)

echo This removes ALL persistent ROM failure evidence and blacklisted ROMs.
echo Session-only quarantine is not affected until the current screen saver exits.
echo.
set /p "ANSWER=Type YES to reset: "
if /i not "%ANSWER%"=="YES" (
  echo Cancelled.
  pause
  exit /b 0
)

del /q "%STATE%"
if exist "%STATE%" (
  echo Failed to delete:
  echo   %STATE%
  pause
  exit /b 1
)

echo Persistent ROM blacklist reset.
pause
