@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv。
    echo        请先运行 install_deps.bat。
    pause
    exit /b 1
)

echo 正在启动 MPWE WebUI 服务：http://localhost:8642 ...
start "MPWE WebUI" cmd /k ".venv\Scripts\python.exe -m app.main"

echo 正在打开浏览器 ...
timeout /t 5 /nobreak >nul
start "" "http://localhost:8642"
exit /b 0