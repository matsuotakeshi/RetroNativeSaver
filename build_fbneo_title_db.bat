@echo off
cd /d "%~dp0"
python tools\build_arcade_title_db.py ^
  --output metadata\fbneo_titles.json ^
  --playlist "C:\RetroArch-win64\playlists\*.lpl" ^
  --core-filter "FinalBurn Neo" ^
  --core-filter "FBNeo" ^
  --core-filter "fbneo_libretro" ^
  --rom-root "C:\ROMs\arcade" ^
  --verbose
echo.
pause
