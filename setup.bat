@echo off
rem Double-click me: installs Recycle Bin support for File Sorter, then starts it.
setlocal
rem Some installers (e.g. PostgreSQL) leave certificate settings pointing at files that do not exist,
rem which stops pip from downloading anything. Ignore those, for this window only.
for %%V in (REQUESTS_CA_BUNDLE CURL_CA_BUNDLE SSL_CERT_FILE PIP_CERT) do call :fixcert %%V

echo Installing Recycle Bin support (send2trash)...
py -m pip install --user --upgrade send2trash
if errorlevel 1 python -m pip install --user --upgrade send2trash
if errorlevel 1 (
  echo.
  echo Recycle Bin support could not be installed (see the message above^).
  echo File Sorter still works, but Delete will remove files permanently.
  pause
)
echo Starting File Sorter...
start "" "%~dp0run.pyw"
exit /b 0

:fixcert
setlocal enabledelayedexpansion
set "val=!%1!"
if defined val if not exist "!val!" (
  endlocal
  echo Ignoring %1: it points to a file that does not exist.
  set "%1="
  exit /b 0
)
endlocal
exit /b 0
