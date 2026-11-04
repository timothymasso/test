@echo off
rem Double-click me: installs Recycle Bin support for File Sorter, then starts it.
echo Installing Recycle Bin support (send2trash)...
py -m pip install --user --upgrade send2trash
if errorlevel 1 python -m pip install --user --upgrade send2trash
if errorlevel 1 (
  echo.
  echo Could not install it. Is Python installed with "Add python.exe to PATH" ticked?
  echo Get it from https://www.python.org/downloads/
  pause
  exit /b 1
)
echo Starting File Sorter...
start "" "%~dp0run.pyw"
