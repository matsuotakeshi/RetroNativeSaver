@echo off
cd /d "%~dp0"
python -X faulthandler -u native_saver.py --windowed --system gamecube --force-system --slots 1 --no-hw-readback --no-frame-rebind --env-trace-frames 10
echo.
echo ExitCode=%ERRORLEVEL%
pause
