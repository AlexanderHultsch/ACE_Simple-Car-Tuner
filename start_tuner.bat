@echo off
rem Starts the tuner server (all cars) and opens the tuner page in the default browser.
rem Optional: full path of python.exe (Python 3.9 or newer); empty = find it (py launcher, PATH, the usual install folders).
set "PY="
set "PORT=8090"
rem Optional: full path of the game package content.kspkg when the game is not in the default Steam folder.
set "GAME="
cd /d "%~dp0"
call "%~dp0tools\find_python.bat"
if not defined PY (
    echo Python 3.9 or newer not found.
    echo Install Python from python.org, or set the PY line in this file to the full path of python.exe.
    pause
    exit /b 1
)
start "" /min cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:%PORT%/ACESCT/"
echo After the first start Windows asks whether Python may use the private network: choose Allow. Other devices then open the address the server prints.
if defined GAME (
    "%PY%" -I tools\tuner_server.py --port %PORT% --game "%GAME%"
) else (
    "%PY%" -I tools\tuner_server.py --port %PORT%
)
echo.
echo The tuner server has stopped.
pause
