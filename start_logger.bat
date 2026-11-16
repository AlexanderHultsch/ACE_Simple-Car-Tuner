@echo off
title ACE Session Logger
rem Starts the session logger: it waits for the game and writes one file per session into the logs folder. Ctrl+C stops it.
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" (
    echo Python not found at "%PY%".
    echo Install Python 3.12 for the current user, or edit the PY line in this file.
    pause
    exit /b 1
)
cd /d "%~dp0"
"%PY%" -I tools\logger.py
echo.
echo The session logger has stopped.
pause
