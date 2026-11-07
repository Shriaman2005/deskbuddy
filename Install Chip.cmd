@echo off
rem Install Chip.cmd - double-click to set Chip up on this Windows PC. Run it again to update or repair Chip.
rem Finds Python 3.12+ from python.org (never the Microsoft Store one), installs Python 3.14 with winget if there is
rem none (just for this Windows user, no admin needed), then runs laptop\install.py: a private Python environment,
rem Chip's own ssh key, start at login, start Chip now, open the dashboard.
rem Arguments go to install.py:  "Install Chip.cmd" --uninstall   (or --repair, --ci)
rem CHIP_NO_PAUSE=1: don't wait for a key at the end (tests).
setlocal EnableExtensions DisableDelayedExpansion
title Chip setup
cd /d "%~dp0"
echo Chip setup
echo ==========
if exist "laptop\install.py" goto :folder_ok
echo.
echo Problem: this file has to stay in the Chip folder, next to the "laptop" folder.
echo If you downloaded the ZIP: right-click it, choose "Extract All...", open the extracted folder
echo and double-click "Install Chip.cmd" there.
goto :done_fail

:folder_ok
call :find_python
if defined PY goto :have_python
if not defined STORE goto :no_store
echo.
echo You have Python from the Microsoft Store. Chip can't use that one: Windows keeps the files it
echo writes in a hidden private folder, so Chip's settings and keys would go missing. Your Store Python
echo stays as it is; Chip gets its own Python from python.org next to it.
:no_store
where winget >nul 2>&1
if errorlevel 1 goto :no_winget
echo.
echo Python 3.12 or newer isn't installed. Installing Python 3.14 from python.org with winget,
echo just for this Windows user. This takes a few minutes; please wait.
echo.
winget install --id Python.Python.3.14 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --custom "InstallLauncherAllUsers=0 PrependPath=1 Include_test=0"
set "WG=%errorlevel%"
call :find_python
if defined PY goto :have_python
echo.
echo Problem: winget couldn't install Python (code %WG%).
goto :manual_python

:no_winget
echo.
echo Python 3.12 or newer isn't installed, and this PC has no winget to install it.
:manual_python
echo Install Python by hand, then double-click "Install Chip.cmd" again:
echo   1. On the page that opens now, download "Windows installer (64-bit)" of Python 3.14.
echo   2. Run it, tick "Add python.exe to PATH" at the bottom, untick "Use admin privileges"
echo      if you aren't an administrator, and click "Install Now".
start "" "https://www.python.org/downloads/windows/"
goto :done_fail

:have_python
echo Python: "%PY%"
echo.
set "CHIP_LAUNCHER=Install Chip.cmd"
"%PY%" -I -X utf8 laptop\install.py %*
if errorlevel 1 goto :failed
echo.
echo All done. You can close this window.
call :pause
exit /b 0

:failed
echo.
echo Chip setup stopped (the problem is described above). Fix it, then double-click "Install Chip.cmd" again.
:done_fail
call :pause
exit /b 1

:pause
if not "%CHIP_NO_PAUSE%"=="1" pause
goto :eof

rem ---- find_python: PY = the last working python.exe 3.12+ found; STORE = 1 if the Store's Python is installed
:find_python
set "PY="
set "STORE="
for /f "delims=" %%P in ('where python 2^>nul') do call :try "%%P"
for /d %%D in ("%ProgramFiles%\Python3*" "%LOCALAPPDATA%\Programs\Python\Python3*") do call :try "%%D\python.exe"
for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-3*") do call :try "%%D\python.exe"
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3*") do set "STORE=1"
goto :eof

:try
rem WindowsApps holds the Store's Python and the "get Python from the Store" stub: never use those
set "C=%~1"
if not "%C:WindowsApps=%"=="%C%" goto :eof
if not exist "%C%" goto :eof
"%C%" -I -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 2)" <nul >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%C%"
goto :eof
