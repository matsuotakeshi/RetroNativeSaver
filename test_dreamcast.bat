@echo off
cd /d "%~dp0"
python native_saver.py --windowed --system dreamcast --slots 1
echo.
echo ExitCode=%ERRORLEVEL%
pause
