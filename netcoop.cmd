@echo off
setlocal
set "ROOT=%~dp0"

if /I "%~1"=="serve" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start_netcoop.ps1"
  exit /b %ERRORLEVEL%
)

set "PYTHON=%LOCALAPPDATA%\Python\bin\python.exe"
if exist "%PYTHON%" goto :run
if exist "%ROOT%.venv\Scripts\python.exe" set "PYTHON=%ROOT%.venv\Scripts\python.exe" & goto :run

echo Python was not found in the project virtual environment or LocalAppData.
echo Install Python 3.11 or 3.12, then run: .\netcoop.cmd serve
exit /b 1

:run
"%PYTHON%" "%ROOT%netcoop.py" %*
