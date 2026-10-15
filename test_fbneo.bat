@echo off
cd /d "%~dp0"
python -u native_saver.py --windowed --system fbneo --force-system --slots 1
echo.
echo ExitCode=%ERRORLEVEL%
pause
