@echo off
cd /d "%~dp0"
python -X faulthandler -u native_saver.py --windowed --system gamecube --force-system --slots 1 --disable-log-interface --disable-perf-interface --no-frame-rebind
echo.
echo ExitCode=%ERRORLEVEL%
pause
