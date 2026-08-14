@echo off
REM Install/refresh Start Menu shortcut for the last local pack (no rebuild).
REM Shortcut chain: .lnk → run_hermes_desktop.vbs → sets env → Hermes.exe
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 build_desktop.py --shortcut-only --no-pause %*
) else (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    python build_desktop.py --shortcut-only --no-pause %*
  ) else (
    echo ERROR: Python not found. Install Python 3.11+ and ensure py/python is on PATH.
    pause
    exit /b 1
  )
)

set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Start Menu shortcut ready: Hermes
  echo Optional: right-click → 固定到开始屏幕
) else (
  echo Failed with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
