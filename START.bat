@echo off
REM ===================================================================
REM  BASSIGNANA EPC CONTROL - start the site control system
REM
REM  Double-click this file to start the server. Leave the window open
REM  while the system is in use; closing it stops the server.
REM  Your data is in data\bassignana.db and survives every restart.
REM ===================================================================
title BASSIGNANA EPC CONTROL

cd /d "%~dp0"

REM --- find Python -------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo   Python was not found on this computer.
  echo   Install Python 3.10 or newer from https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" during the install.
  echo.
  pause
  exit /b 1
)

REM --- install or update the requirements on first run -------------
%PY% -c "import flask, flask_sqlalchemy, waitress, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Installing the required packages. This happens once and needs
  echo   an internet connection. After this the system runs offline.
  echo.
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   The install did not complete. Check the messages above.
    echo.
    pause
    exit /b 1
  )
)

REM --- back up the database before starting -------------------------
if exist "data\bassignana.db" (
  %PY% -c "from app import create_app; from app.services import backup; app=create_app(); ctx=app.app_context(); ctx.push(); print('  Startup backup:', backup.create_backup().name); ctx.pop()" 2>nul
)

REM --- start --------------------------------------------------------
echo.
%PY% run.py %*

echo.
echo   The server has stopped. Your data is saved in data\bassignana.db
echo.
pause
