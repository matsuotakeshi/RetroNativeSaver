@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage:
  echo   build_mame_title_db_from_exe.bat "C:\path\to\mame.exe"
  echo.
  pause
  exit /b 1
)
python tools\build_arcade_title_db.py ^
  --output metadata\mame_titles.json ^
  --mame-exe "%~1" ^
  --verbose
echo.
pause
