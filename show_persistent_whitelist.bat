@echo off
setlocal
cd /d "%~dp0"
set "STATE_DIR=%~dp0state"
set "WHITELIST=%STATE_DIR%\persistent_rom_whitelist.json"
set "DEFAULT=%~dp0persistent_rom_whitelist.default.json"

if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"

if not exist "%WHITELIST%" (
  if exist "%DEFAULT%" (
    copy /y "%DEFAULT%" "%WHITELIST%" >nul
  ) else (
    echo {
    echo   "version": 1,
    echo   "systems": {}
    echo }
    > "%WHITELIST%"
  )
)

notepad "%WHITELIST%"
