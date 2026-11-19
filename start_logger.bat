@echo off
title ACE Session Logger
rem Starts the session logger: it waits for the game and writes one file per session into the logs folder. Ctrl+C stops it.
rem Optional: full path of python.exe (Python 3.9 or newer); empty = find it (py launcher, PATH, the usual install folders).
set "PY="
cd /d "%~dp0"
call "%~dp0tools\find_python.bat"
if not defined PY (
    echo Python 3.9 or newer not found.
    echo Install Python from python.org, or set the PY line in this file to the full path of python.exe.
    pause
    exit /b 1
)
"%PY%" -I tools\logger.py
echo.
echo The session logger has stopped.
pause
