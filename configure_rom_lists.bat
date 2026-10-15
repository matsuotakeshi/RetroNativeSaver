@echo off
cd /d "%~dp0"
if exist "RetroNativeSaver.exe" (
  start "" "%~dp0RetroNativeSaver.exe" --rom-lists
) else (
  python native_saver.py --rom-lists
)
