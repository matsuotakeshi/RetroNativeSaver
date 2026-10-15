@echo off
cd /d "%~dp0"
python -X faulthandler -u native_saver.py
pause
