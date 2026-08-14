@echo off
setlocal EnableExtensions

rem Double-click / shortcut launcher for `npm run dev` (Hermes Desktop).
rem Keeps a console so build/start errors stay visible.

cd /d "%~dp0.."
if errorlevel 1 (
  echo Failed to enter apps\desktop: %~dp0..
  pause
  exit /b 1
)

for %%I in ("%~dp0..\..") do set "HERMES_DESKTOP_HERMES_ROOT=%%~fI"
set "HERMES_HOME=%LOCALAPPDATA%\hermes"

title Hermes ^(Dev^)
echo.
echo  Hermes Desktop ^(Dev^)
echo  cwd:    %CD%
echo  source: %HERMES_DESKTOP_HERMES_ROOT%
echo  home:   %HERMES_HOME%
echo.

set "NPM_CMD="
if exist "%ProgramFiles%\nodejs\npm.cmd" set "NPM_CMD=%ProgramFiles%\nodejs\npm.cmd"
if not defined NPM_CMD if exist "%LocalAppData%\Programs\nodejs\npm.cmd" set "NPM_CMD=%LocalAppData%\Programs\nodejs\npm.cmd"
if not defined NPM_CMD (
  where npm.cmd >nul 2>&1
  if not errorlevel 1 for /f "delims=" %%P in ('where npm.cmd') do (
    set "NPM_CMD=%%P"
    goto :npm_found
  )
)

:npm_found
if not defined NPM_CMD (
  echo npm.cmd not found. Install Node.js ^>= 22 and reopen.
  pause
  exit /b 1
)

echo  Using: %NPM_CMD%
echo  Running: npm run dev
echo  Close this window to stop the dev server + Electron.
echo.

call "%NPM_CMD%" run dev
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo npm run dev exited with code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
