@echo off
setlocal
cd /d "%~dp0"
echo Updating ROM catalog. Please wait...
echo The screen saver and emulators will not be started.
if exist "RetroNativeSaver.exe" (
  start "" /wait "%~dp0RetroNativeSaver.exe" --update-rom-catalog
) else (
  python native_saver.py --update-rom-catalog
)
if errorlevel 1 (
  echo UPDATE FAILED. Previous catalog was kept. Enable log output in Settings and retry for details.
  pause
  exit /b 1
)
echo COMPLETE: state\rom_catalog.json
echo Run this again after changing ROM files or ROM folder links.
pause
exit /b 0
