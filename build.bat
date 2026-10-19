@echo off
setlocal
cd /d "%~dp0"

python initialize_config.py
if errorlevel 1 exit /b 1

echo ========================================
echo Retro Native Saver v0.21.24 build
echo ========================================

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RetroNativeSaver.spec del /q RetroNativeSaver.spec

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --windowed ^
  --icon "retro_native_saver.ico" ^
  --name RetroNativeSaver ^
  native_saver.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED
    pause
    exit /b 1
)

echo.
echo Copy license documents and third-party sources...
copy /y "LICENSE" "dist\RetroNativeSaver\LICENSE" >nul
if errorlevel 1 exit /b 1
copy /y "COPYRIGHT" "dist\RetroNativeSaver\COPYRIGHT" >nul
if errorlevel 1 exit /b 1
copy /y "THIRD_PARTY_NOTICES.md" "dist\RetroNativeSaver\THIRD_PARTY_NOTICES.md" >nul
if errorlevel 1 exit /b 1
xcopy /e /i /y "third_party" "dist\RetroNativeSaver\third_party" >nul
if errorlevel 1 exit /b 1

echo.
echo Copy configuration...
copy /y "update_rom_catalog.bat" "dist\RetroNativeSaver\update_rom_catalog.bat" >nul
copy /y "test_single_system.bat" "dist\RetroNativeSaver\test_single_system.bat" >nul
copy /y "measure_startup.ps1" "dist\RetroNativeSaver\measure_startup.ps1" >nul
copy /y "measure_startup.bat" "dist\RetroNativeSaver\measure_startup.bat" >nul

xcopy /e /i /y "cores" "dist\RetroNativeSaver\cores" >nul
copy /y "configure_rom_lists.bat" "dist\RetroNativeSaver\configure_rom_lists.bat" >nul
if not exist "dist\RetroNativeSaver\state" mkdir "dist\RetroNativeSaver\state"
if exist "state\rom_catalog.json" copy /y "state\rom_catalog.json" "dist\RetroNativeSaver\state\rom_catalog.json" >nul
copy /y "state\persistent_rom_whitelist.json" "dist\RetroNativeSaver\state\persistent_rom_whitelist.json" >nul
copy /y "favorites.json" "dist\RetroNativeSaver\favorites.json" >nul
copy /y "configure_favorites.bat" "dist\RetroNativeSaver\configure_favorites.bat" >nul
copy /y config.json "dist\RetroNativeSaver\config.json" >nul
xcopy /e /i /y "systems" "dist\RetroNativeSaver\systems" >nul
xcopy /e /i /y "metadata" "dist\RetroNativeSaver\metadata" >nul
xcopy /e /i /y "tools" "dist\RetroNativeSaver\tools" >nul
copy /y "build_fbneo_title_db.bat" "dist\RetroNativeSaver\build_fbneo_title_db.bat" >nul
copy /y "build_mame_title_db.bat" "dist\RetroNativeSaver\build_mame_title_db.bat" >nul
copy /y "build_mame_title_db_from_exe.bat" "dist\RetroNativeSaver\build_mame_title_db_from_exe.bat" >nul
copy /y "retro_native_saver.ico" "dist\RetroNativeSaver\retro_native_saver.ico" >nul
copy /y "show_latest_log.bat" "dist\RetroNativeSaver\show_latest_log.bat" >nul
copy /y "show_persistent_blacklist.bat" "dist\RetroNativeSaver\show_persistent_blacklist.bat" >nul
copy /y "reset_persistent_blacklist.bat" "dist\RetroNativeSaver\reset_persistent_blacklist.bat" >nul
copy /y "persistent_rom_whitelist.default.json" "dist\RetroNativeSaver\persistent_rom_whitelist.default.json" >nul
copy /y "show_persistent_whitelist.bat" "dist\RetroNativeSaver\show_persistent_whitelist.bat" >nul
copy /y "reset_persistent_whitelist.bat" "dist\RetroNativeSaver\reset_persistent_whitelist.bat" >nul

echo.
echo Create Windows screen saver...
copy /y "dist\RetroNativeSaver\RetroNativeSaver.exe" "dist\RetroNativeSaver\RetroNativeSaver.scr" >nul

echo.
echo Create helper scripts...

(
echo @echo off
echo cd /d "%%~dp0"
echo "%%~dp0RetroNativeSaver.scr" /s
) > "dist\RetroNativeSaver\test_saver.bat"

(
echo @echo off
echo cd /d "%%~dp0"
echo "%%~dp0RetroNativeSaver.scr" /c
) > "dist\RetroNativeSaver\configure_saver.bat"


(
echo @echo off
echo cd /d "%%~dp0"
echo "%%~dp0RetroNativeSaver.exe" --windowed --system dreamcast --slots 1
echo pause
) > "dist\RetroNativeSaver\test_dreamcast.bat"


(
echo @echo off
echo cd /d "%%~dp0"
echo "%%~dp0RetroNativeSaver.exe" --windowed --system mame --force-system --slots 1
echo pause
) > "dist\RetroNativeSaver\test_mame.bat"

(
echo @echo off
echo setlocal
echo cd /d "%%~dp0"
echo reg add "HKCU\Control Panel\Desktop" /v SCRNSAVE.EXE /t REG_SZ /d "%%~dp0RetroNativeSaver.scr" /f
echo reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d "1" /f
echo echo.
echo echo Retro Native Saver registered:
echo echo %%~dp0RetroNativeSaver.scr
echo echo.
echo echo Windows settings may need to be reopened before the change is shown.
echo pause
) > "dist\RetroNativeSaver\install_saver.bat"

echo.
echo ========================================
echo BUILD COMPLETE
echo ========================================
echo.
echo Output:
echo   dist\RetroNativeSaver\RetroNativeSaver.exe
echo   dist\RetroNativeSaver\RetroNativeSaver.scr
echo   dist\RetroNativeSaver\config.json
echo   dist\RetroNativeSaver\systems\
echo.
echo Test:
echo   dist\RetroNativeSaver\test_saver.bat
echo.
echo Register:
echo   dist\RetroNativeSaver\install_saver.bat
echo.
pause
