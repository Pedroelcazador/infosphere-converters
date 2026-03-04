@echo off
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw web_ui.py
    exit /b 0
)

where python >nul 2>&1
if %errorlevel% == 0 (
    start "" /b python web_ui.py >nul 2>&1
    exit /b 0
)

echo Python niet gevonden. Installeer Python via https://www.python.org/
pause
