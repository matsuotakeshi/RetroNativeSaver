@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='systems\fbneo.json';" ^
  "$j=Get-Content -Raw -Encoding UTF8 $p | ConvertFrom-Json;" ^
  "if(-not $j.core_options){$j | Add-Member -NotePropertyName core_options -NotePropertyValue ([pscustomobject]@{})};" ^
  "$j.core_options | Add-Member -Force -NotePropertyName 'fbneo-neogeo-mode' -NotePropertyValue 'MVS_JAP';" ^
  "$j | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $p"
echo.
echo FBNeo Neo Geo mode set to Japanese MVS: MVS_JAP
pause
