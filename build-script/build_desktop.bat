@echo off
REM Double-click entry for local Hermes Desktop pack (path A).
REM Keeps the console open so build errors stay visible.
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 build_desktop.py --no-pause %*
) else (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    python build_desktop.py --no-pause %*
  ) else (
    echo ERROR: Python not found. Install Python 3.11+ and ensure py/python is on PATH.
    pause
    exit /b 1
  )
)

set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Done.
  echo   Start Menu: search "Hermes"  ^(or right-click → 固定到开始屏幕^)
  echo   Or double-click: build-script\run_hermes_desktop.vbs
) else (
  echo Build failed with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
