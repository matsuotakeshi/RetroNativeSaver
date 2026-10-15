@echo off
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
set LOG=logs\retro_native_saver_%TODAY%.log
if exist "%LOG%" (
  notepad "%LOG%"
) else (
  explorer logs
)
