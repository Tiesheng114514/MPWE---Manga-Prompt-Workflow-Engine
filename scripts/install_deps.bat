@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv。
    echo        请先创建虚拟环境，例如：
    echo        python -m venv .venv
    pause
    exit /b 1
)

echo 正在安装依赖到 .venv ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败。
    pause
    exit /b 1
)

echo.
".venv\Scripts\python.exe" -m app.admin.init_secrets
echo 安装完成。
pause
