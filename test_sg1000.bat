@echo off
cd /d "%~dp0"
python -u native_saver.py --windowed --system sg1000 --force-system --slots 1
echo.
echo ExitCode=%ERRORLEVEL%
pause
