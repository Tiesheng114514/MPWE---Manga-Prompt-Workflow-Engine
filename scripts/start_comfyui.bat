@echo off
setlocal EnableDelayedExpansion
rem MPWE ComfyUI 启动（支持多实例；路径优先取 安装向导.bat 生成的 data\local_paths.bat）
cd /d "%~dp0.."

if exist "data\local_paths.bat" call "data\local_paths.bat"

if not defined COMFY_ROOT set "COMFY_ROOT=E:\AI\Confy UI\ComfyUI\ComfyUI"
if not defined COMFY_PY (
    if exist "%COMFY_ROOT%\standalone-env\python.exe" (
        set "COMFY_PY=%COMFY_ROOT%\standalone-env\python.exe"
    ) else if exist "%COMFY_ROOT%\..\standalone-env\python.exe" (
        set "COMFY_PY=%COMFY_ROOT%\..\standalone-env\python.exe"
    ) else (
        set "COMFY_PY=%COMFY_ROOT%\standalone-env\python.exe"
    )
)
set "BASE_PY=%COMFY_PY%"

if not defined SITE_PACKAGES (
    for %%I in ("%COMFY_PY%") do set "PY_DIR=%%~dpI"
    if exist "%COMFY_ROOT%\.venv\Lib\site-packages" (
        set "SITE_PACKAGES=%COMFY_ROOT%\.venv\Lib\site-packages"
    ) else if exist "!PY_DIR!Lib\site-packages" (
        set "SITE_PACKAGES=!PY_DIR!Lib\site-packages"
    ) else if exist "!PY_DIR!..\Lib\site-packages" (
        set "SITE_PACKAGES=!PY_DIR!..\Lib\site-packages"
    ) else (
        set "SITE_PACKAGES=!PY_DIR!Lib\site-packages"
    )
)

if not exist "%BASE_PY%" (
    echo [错误] 未找到 ComfyUI 的 Python: %BASE_PY%
    echo 请先运行 安装向导.bat 配置正确的 ComfyUI 路径。
    pause
    exit /b 1
)

set "WORKERS=%MPWE_COMFYUI_WORKERS%"
if "%WORKERS%"=="" set "WORKERS=1"
set /a WORKERS=%WORKERS% 2>nul
if %WORKERS% LSS 1 set "WORKERS=1"
if %WORKERS% GTR 4 set "WORKERS=4"

if not exist "%~dp0..\data\logs" mkdir "%~dp0..\data\logs"
echo 启动 %WORKERS% 个 ComfyUI 实例（127.0.0.1:8188 起，日志: data\logs\comfyui_*.log）...
cd /d "%COMFY_ROOT%"
set PYTHONUNBUFFERED=1
set "PYTHONPATH=%SITE_PACKAGES%"

for /l %%i in (1,1,%WORKERS%) do (
    set /a "P=8187+%%i"
    start "ComfyUI-%%i" cmd /k ""%BASE_PY%" main.py --listen 127.0.0.1 --port !P! --extra-model-paths-config "%~dp0..\comfyui_extra_model_paths.yaml" --database-url "sqlite:///%~dp0..\data\comfyui_!P!.db" >> "%~dp0..\data\logs\comfyui_!P!.log" 2>&1"
)

echo.
echo 已启动实例，默认使用 http://127.0.0.1:8188
echo 关闭对应的 ComfyUI-xx 窗口即可停止该实例。
pause