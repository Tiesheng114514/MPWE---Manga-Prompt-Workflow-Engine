@echo off
setlocal
cd /d "%~dp0.."

echo ============================================
echo   MPWE 一键停止：关闭本项目启动的所有服务
echo   （用户 WebUI + ComfyUI 绘图引擎 + 管理员后台）
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and ($_.CommandLine -match 'app\.main' -or $_.CommandLine -match 'app\.admin' -or ($_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--port 818') -or $_.CommandLine -match 'MPWE---Manga-Prompt-Workflow-Engine') } | ForEach-Object { Write-Host ('Killed PID ' + $_.ProcessId + ' : ' + $_.Name); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo 完成。Cloudflare 隧道进程（cloudflared）不受影响。
pause
