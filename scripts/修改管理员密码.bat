@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [Error] venv not found. Run install_deps.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m app.admin.changepwd
if errorlevel 1 pause
