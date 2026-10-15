@echo off
cd /d "%~dp0"
python tools\build_arcade_title_db.py ^
  --output metadata\mame_titles.json ^
  --playlist "C:\RetroArch-win64\playlists\*.lpl" ^
  --core-filter "MAME" ^
  --core-filter "MAME Current" ^
  --core-filter "Arcade (MAME)" ^
  --core-filter "mame_libretro" ^
  --rom-root "C:\ROMs\mame" ^
  --verbose
echo.
pause
