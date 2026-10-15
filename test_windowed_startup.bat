@echo off
cd /d "%~dp0"
python -c "import sys,runpy; sys.stdout=None; sys.stderr=None; runpy.run_path('native_saver.py', run_name='__smoke__')"
if errorlevel 1 (
  echo WINDOWED STARTUP SMOKE TEST FAILED
  pause
  exit /b 1
)
echo WINDOWED STARTUP SMOKE TEST PASSED
pause
