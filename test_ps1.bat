@echo off
cd /d "%~dp0"
python native_saver.py --windowed --system ps1 --force-system --slots 1
echo.
echo ExitCode=%ERRORLEVEL%
pause
