@echo off
cd /d "%~dp0"
python -u native_saver.py --windowed --system gamecube --force-system --slots 1 --cycle-seconds 15
echo.
echo ExitCode=%ERRORLEVEL%
pause
