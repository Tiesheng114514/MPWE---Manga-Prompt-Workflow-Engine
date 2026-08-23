@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"

echo ============================================================
echo   MPWE 一键启动
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo   [错误] 还没安装依赖。
    echo   请先双击运行 安装向导.bat 完成首次安装。
    pause
    exit /b 1
)
if not exist "data\logs" mkdir "data\logs"
if not exist "data\local_paths.bat" (
    echo   [提示] 未找到 data\local_paths.bat，将使用默认路径启动。
    echo   建议先运行 安装向导.bat 配置 ComfyUI 路径。
    echo.
)

REM ---------- 启动 ComfyUI ----------
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8188 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo   启动 ComfyUI（8188）...
    start "MPWE-ComfyUI" /min cmd /c "call scripts\start_comfyui.bat < nul"
) else (
    echo   ComfyUI 已在运行（8188）
)

REM ---------- 启动 WebUI（带日志） ----------
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8642 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo   启动 WebUI（8642，日志: data\logs\webui.log）...
    start "MPWE-WebUI" /min cmd /k ""%CD%\.venv\Scripts\python.exe" -m app.main >> "%CD%\data\logs\webui.log" 2>&1"
) else (
    echo   WebUI 已在运行（8642）
)

REM ---------- 启动管理员后台 ----------
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8643 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo   启动管理员后台（8643）...
    start "MPWE-Admin" cmd /c "call scripts\启动管理员后台WebUI.bat"
) else (
    echo   管理员后台已在运行（8643）
)

echo.
echo   访问地址:
echo     WebUI   : http://localhost:8642
echo     管理后台: http://localhost:8643
echo.
echo   下面实时显示 WebUI + ComfyUI 合并日志（写盘: data\logs\webui.log 与 comfyui_*.log）
echo   按 q 退出全部服务。
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\logs_tail.ps1"
goto quit_all

:quit_all
echo.
echo   正在退出全部服务 ...
taskkill /F /T /FI "WINDOWTITLE eq MPWE-*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq ComfyUI-*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq MPWE WebUI" >nul 2>&1
echo   已退出。
pause
exit /b 0
