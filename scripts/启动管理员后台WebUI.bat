@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo [Error] venv not found. Run install_deps.bat first.
    pause
    exit /b 1
)
echo Starting MPWE Admin WebUI (first run will ask for admin password)...
".venv\Scripts\python.exe" -m app.admin.launcher
if errorlevel 1 (
    echo [Error] Admin WebUI exited with error.
    pause
)
