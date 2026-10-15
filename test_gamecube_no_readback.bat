@echo off
cd /d "%~dp0"
python -X faulthandler -u native_saver.py --windowed --system gamecube --force-system --slots 1 --no-hw-readback --env-trace-frames 5
echo.
echo ExitCode=%ERRORLEVEL%
pause
