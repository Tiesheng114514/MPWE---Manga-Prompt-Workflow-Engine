@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   MPWE 首次安装向导 - 漫画 AI 绘画工作流引擎
echo ============================================================
echo.

REM ================= 1. 检查 git =================
echo [1/6] 检查 git ...
git --version >nul 2>&1
if errorlevel 1 (
    echo   未检测到 git。
    where winget >nul 2>&1
    if not errorlevel 1 (
        echo   尝试用 winget 自动安装 git ...
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
        echo   安装完成后请重新运行本脚本。
        pause
        exit /b 1
    )
    echo   请手动安装 git（一路默认下一步即可）:
    echo   官方下载: https://git-scm.com/download/win
    echo   国内镜像: https://registry.npmmirror.com/-/binary/git-for-windows/
    echo   装完后重新运行本脚本。
    pause
    exit /b 1
)
for /f "delims=" %%v in ('git --version') do echo   已安装: %%v
echo.

REM ================= 2. 检查 Python =================
echo [2/6] 检查 Python ...
set "PY_CMD="
py -3.14 --version >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.14"
if not defined PY_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo   未检测到 Python。
    set /p "want_py=   是否自动下载安装 Python 3.14（国内华为云镜像，约 25MB）? (y/n): "
    if /i "!want_py!"=="y" (
        echo   正在下载 Python 3.14.6 ...
        curl.exe -4 -L --retry 3 -o "%TEMP%\python-3.14.6-installer.exe" "https://mirrors.huaweicloud.com/python/3.14.6/python-3.14.6-amd64.exe"
        if exist "%TEMP%\python-3.14.6-installer.exe" (
            echo   下载完成，开始静默安装（请稍候）...
            start /wait "%TEMP%\python-3.14.6-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
            echo   安装结束，请重新运行本脚本。
        ) else (
            echo   [错误] 下载失败，请手动安装: https://www.python.org/downloads/windows/
        )
    ) else (
        echo   请手动安装 Python 3.11 及以上（推荐 3.14）: https://www.python.org/downloads/windows/
        echo   安装时务必勾选 "Add python.exe to PATH"。
    )
    pause
    exit /b 1
)
%PY_CMD% --version
echo.

REM ================= 3. 虚拟环境 + 项目依赖 =================
echo [3/6] 创建虚拟环境并安装项目依赖 ...
if not exist ".venv\Scripts\python.exe" (
    echo   创建虚拟环境 .venv ...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo   [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo   [提示] 清华镜像安装失败，改用官方源重试 ...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
if errorlevel 1 (
    echo   [错误] 依赖安装失败，请检查网络后重新运行。
    pause
    exit /b 1
)
echo   项目依赖安装完成。
echo.

REM ================= 4. 定位 ComfyUI =================
echo [4/6] 定位 ComfyUI ...
set "COMFY_ROOT="
:ask_comfy
if not defined COMFY_ROOT (
    for %%d in ("E:\AI\Confy UI\ComfyUI\ComfyUI" "D:\ComfyUI\ComfyUI" "%USERPROFILE%\ComfyUI\ComfyUI" "%CD%\ComfyUI") do (
        if exist "%%~d\main.py" set "COMFY_ROOT=%%~d"
    )
)
if defined COMFY_ROOT goto comfy_found
set /p "COMFY_ROOT=   请输入 ComfyUI 安装目录（里面要含 main.py）: "
if not defined COMFY_ROOT goto ask_comfy
:comfy_found
if not exist "%COMFY_ROOT%\main.py" (
    echo.
    echo   [错误] %COMFY_ROOT% 下面没有 main.py，这不是 ComfyUI 根目录。
    echo   正确示例: E:\AI\Confy UI\ComfyUI\ComfyUI
    echo.
    set /p "want_dl=   是否自动下载 ComfyUI 到 %USERPROFILE%\ComfyUI ? (y/n): "
    if /i "!want_dl!"=="y" (
        if not exist "%USERPROFILE%\ComfyUI" mkdir "%USERPROFILE%\ComfyUI"
        git clone https://github.com/comfyanonymous/ComfyUI.git "%USERPROFILE%\ComfyUI\ComfyUI"
        if errorlevel 1 (
            echo   GitHub 直连失败，尝试国内镜像（Gitee）...
            git clone https://gitee.com/mirrors/ComfyUI.git "%USERPROFILE%\ComfyUI\ComfyUI"
        )
        if errorlevel 1 (
            echo   Gitee 也失败，尝试 GitCode 镜像 ...
            git clone https://gitcode.com/gh_mirrors/co/ComfyUI.git "%USERPROFILE%\ComfyUI\ComfyUI"
        )
        set "COMFY_ROOT=%USERPROFILE%\ComfyUI\ComfyUI"
    ) else (
        set "COMFY_ROOT="
        goto ask_comfy
    )
)
if not exist "%COMFY_ROOT%\main.py" (
    echo   [错误] ComfyUI 下载失败，请手动安装后重试。
    pause
    exit /b 1
)
echo   ComfyUI 目录: %COMFY_ROOT%

REM 确定 ComfyUI 使用的 Python
set "COMFY_PY="
if exist "%COMFY_ROOT%\standalone-env\python.exe" set "COMFY_PY=%COMFY_ROOT%\standalone-env\python.exe"
if not defined COMFY_PY if exist "%COMFY_ROOT%\..\standalone-env\python.exe" set "COMFY_PY=%COMFY_ROOT%\..\standalone-env\python.exe"
if not defined COMFY_PY set "COMFY_PY=%CD%\.venv\Scripts\python.exe"

REM 非 standalone 环境时补装 ComfyUI 依赖
if not exist "%COMFY_ROOT%\standalone-env\python.exe" if not exist "%COMFY_ROOT%\..\standalone-env\python.exe" (
    echo   正在安装 ComfyUI 依赖（首次较慢）...
    "%COMFY_PY%" -m pip install -r "%COMFY_ROOT%\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo   [提示] 清华镜像失败，改用官方源重试 ...
        "%COMFY_PY%" -m pip install -r "%COMFY_ROOT%\requirements.txt"
    )
    if errorlevel 1 (
        echo   [错误] ComfyUI 依赖安装失败。
        pause
        exit /b 1
    )
)
echo.

REM ================= 5. 模型目录 + 工作流目录 =================
echo [5/6] 设置共享模型目录 ...
set "MODEL_ROOT="
:ask_model
if not defined MODEL_ROOT (
    if exist "D:\Comfy-Desktop\ComfyUI-Shared\models\checkpoints" set "MODEL_ROOT=D:\Comfy-Desktop\ComfyUI-Shared"
    if not defined MODEL_ROOT if exist "%COMFY_ROOT%\models\checkpoints" set "MODEL_ROOT=%COMFY_ROOT%"
)
if defined MODEL_ROOT goto model_found
set /p "MODEL_ROOT=   请输入共享模型根目录（内含 models\checkpoints、models\loras 等子文件夹）: "
:model_found
if not exist "%MODEL_ROOT%\models\checkpoints" (
    echo.
    echo   [错误] %MODEL_ROOT% 下没有 models\checkpoints 文件夹。
    echo   正确示例: D:\Comfy-Desktop\ComfyUI-Shared（里面要有 models\checkpoints\）
    echo.
    set "MODEL_ROOT="
    goto ask_model
)
echo   模型目录: %MODEL_ROOT%

set "WORKFLOW_ROOT="
:ask_wf
if not defined WORKFLOW_ROOT (
    if exist "%COMFY_ROOT%\user\default\workflows" set "WORKFLOW_ROOT=%COMFY_ROOT%\user\default\workflows"
)
if defined WORKFLOW_ROOT goto wf_found
set /p "WORKFLOW_ROOT=   请输入工作流目录（回车使用默认）: "
if not defined WORKFLOW_ROOT set "WORKFLOW_ROOT=%COMFY_ROOT%\user\default\workflows"
:wf_found
if not exist "%WORKFLOW_ROOT%" (
    echo   工作流目录不存在，自动创建 ...
    mkdir "%WORKFLOW_ROOT%"
)
echo   工作流目录: %WORKFLOW_ROOT%
echo.

REM ================= 6. 写入配置并收尾 =================
echo [6/6] 写入配置并收尾 ...
(
    echo # MPWE ComfyUI extra model paths (auto-generated by install wizard)
    echo # passed to ComfyUI via --extra-model-paths-config
    echo comfy_desktop_shared:
    echo     base_path: !MODEL_ROOT!
    echo     checkpoints: models/checkpoints
    echo     diffusion_models: models/diffusion_models
    echo     text_encoders: models/text_encoders
    echo     vae: models/vae
    echo     loras: models/loras
    echo     controlnet: models/controlnet
    echo     model_patches: models/model_patches
    echo     upscale_models: models/upscale_models
    echo     bbox: models/detection
    echo     detection: models/detection
    echo     input: input
    echo     output: output
) > comfyui_extra_model_paths.yaml

if not exist "data" mkdir "data"
(
    echo @echo off
    echo set "COMFY_ROOT=!COMFY_ROOT!"
    echo set "COMFY_PY=!COMFY_PY!"
    echo set "MODEL_ROOT=!MODEL_ROOT!"
    echo set "WORKFLOW_ROOT=!WORKFLOW_ROOT!"
) > data\local_paths.bat

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo   已生成 .env。
)
set /p "want_key=   是否现在填写 API Key？(y/n，可跳过稍后用记事本改 .env): "
if /i "!want_key!"=="y" (
    set "MPWE_KEY="
    set /p "MPWE_KEY=   请输入 DeepSeek API Key（sk- 开头，屏幕会明文显示）: "
    if defined MPWE_KEY (
        powershell -NoProfile -Command "$k=$env:MPWE_KEY; $p='.env'; $o=@(); $f=$false; Get-Content $p -Encoding UTF8 | ForEach-Object { if ($_ -match '^OPENAI_API_KEY=') { $f=$true; $o+='OPENAI_API_KEY='+$k } else { $o+=$_ } }; if (-not $f) { $o+='OPENAI_API_KEY='+$k }; Set-Content $p -Value $o -Encoding UTF8"
    )
    set "TS_SITE="
    set /p "TS_SITE=   请输入 Cloudflare Turnstile Site Key（免费充值人机验证用，没有就回车跳过）: "
    if defined TS_SITE (
        set "TS_SECRET="
        set /p "TS_SECRET=   请输入 Cloudflare Turnstile Secret Key: "
        if defined TS_SECRET (
            powershell -NoProfile -Command "$s=$env:TS_SITE; $c=$env:TS_SECRET; $p='.env'; $o=@(); Get-Content $p -Encoding UTF8 | ForEach-Object { $o+=$_ }; $o+='TURNSTILE_SITE_KEY='+$s; $o+='TURNSTILE_SECRET_KEY='+$c; Set-Content $p -Value $o -Encoding UTF8"
        )
    )
)


echo   初始化隐私数据（管理员密码文件）...
".venv\Scripts\python.exe" -m app.admin.init_secrets

if not exist "%COMFY_ROOT%\custom_nodes\ComfyUI-Impact-Pack" (
    set /p "want_impact=   是否安装画质增强所需的自定义节点 ComfyUI-Impact-Pack? (y/n): "
    if /i "!want_impact!"=="y" (
        if not exist "%COMFY_ROOT%\custom_nodes" mkdir "%COMFY_ROOT%\custom_nodes"
        git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git "%COMFY_ROOT%\custom_nodes\ComfyUI-Impact-Pack"
        if errorlevel 1 (
            echo   GitHub 直连失败，尝试 GitCode 镜像 ...
            git clone https://gitcode.com/gh_mirrors/co/ComfyUI-Impact-Pack.git "%COMFY_ROOT%\custom_nodes\ComfyUI-Impact-Pack"
        )
        "%COMFY_PY%" -m pip install -r "%COMFY_ROOT%\custom_nodes\ComfyUI-Impact-Pack\requirements.txt"
    )
)

echo.
echo ============================================================
echo   安装完成！
echo   1. 如果刚才没填 API Key，用记事本打开 .env 补上 OPENAI_API_KEY
echo   2. 双击 一键启动.bat 启动全部服务
echo   3. 管理后台首次运行会提示设置管理员密码
echo ============================================================
pause
