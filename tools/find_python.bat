@echo off
rem Sets PY to the full path of a python.exe that is Python 3.9 or newer, or to empty when there is none. The caller may set PY first (its override); no output.
set "PY_OVERRIDE=%PY%"
set "PY="
if defined PY_OVERRIDE call :probe "%PY_OVERRIDE%"
if not defined PY for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do call :probe "%%P"
if not defined PY for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do call :probe "%%P"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :probe "%%D\python.exe"
if not defined PY for /d %%D in ("%ProgramFiles%\Python3*") do call :probe "%%D\python.exe"
set "PY_OVERRIDE="
exit /b 0

:probe
if defined PY exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
exit /b 0
