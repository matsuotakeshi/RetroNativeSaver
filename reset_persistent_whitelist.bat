@echo off
setlocal
cd /d "%~dp0"
set "STATE_DIR=%~dp0state"
set "WHITELIST=%STATE_DIR%\persistent_rom_whitelist.json"
set "DEFAULT=%~dp0persistent_rom_whitelist.default.json"

echo This resets the persistent ROM whitelist to the shipped default.
echo Current custom whitelist entries will be lost.
echo.
set /p "ANSWER=Type YES to reset: "
if /i not "%ANSWER%"=="YES" (
  echo Cancelled.
  pause
  exit /b 0
)

if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"

if exist "%DEFAULT%" (
  copy /y "%DEFAULT%" "%WHITELIST%" >nul
  echo Persistent ROM whitelist reset to default.
) else (
  echo Default whitelist file is missing:
  echo   %DEFAULT%
  pause
  exit /b 1
)

pause
