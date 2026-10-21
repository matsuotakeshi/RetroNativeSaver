@echo off
cd /d "%~dp0"
if exist "%~dp0RetroNativeSaver.scr" (
    "%~dp0RetroNativeSaver.scr" /c
) else if exist "%~dp0RetroNativeSaver.exe" (
    "%~dp0RetroNativeSaver.exe" /c
) else (
    python "%~dp0native_saver.py" /c
)
