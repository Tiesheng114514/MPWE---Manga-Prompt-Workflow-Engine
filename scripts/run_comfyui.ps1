# MPWE ComfyUI launcher helper.
# Starts ComfyUI, writes its output to log files, and shows those logs live in this window.
# Closing this window (or Ctrl+C) stops ComfyUI.
# Configuration comes from environment variables set by start_comfyui.bat:
#   MPWE_COMFY_PY / MPWE_COMFY_ROOT / MPWE_COMFY_PORT / MPWE_COMFY_EXTRA / MPWE_COMFY_DB / MPWE_COMFY_LOG

$ErrorActionPreference = 'Continue'

$python = $env:MPWE_COMFY_PY
$root   = $env:MPWE_COMFY_ROOT
$port   = $env:MPWE_COMFY_PORT
$extra  = $env:MPWE_COMFY_EXTRA
$db     = $env:MPWE_COMFY_DB
$log    = $env:MPWE_COMFY_LOG
$logErr = "$log.err"

function Stop-WithMessage([string]$message) {
    Write-Host $message
    Read-Host '按回车关闭窗口'
    exit 1
}

if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    Stop-WithMessage "[错误] 未找到 ComfyUI 的 Python: $python（请先运行 安装向导.bat 配置路径）"
}
if (-not $root -or -not (Test-Path -LiteralPath (Join-Path $root 'main.py'))) {
    Stop-WithMessage "[错误] 未找到 ComfyUI 主程序 main.py: $root（请先运行 安装向导.bat 配置路径）"
}

$logDir = Split-Path -Parent $log
if ($logDir) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

$cliArgs = @('main.py', '--listen', '127.0.0.1', '--port', $port)
if ($extra) { $cliArgs += @('--extra-model-paths-config', $extra) }
if ($db)    { $cliArgs += @('--database-url', $db) }

Write-Host "ComfyUI 启动中（端口 $port）..."
Write-Host "日志文件: $log （错误输出在 $logErr）"
Write-Host "首次启动加载模型需要 30-60 秒，出现 'To see the GUI go to' 就说明已经起来了。"
Write-Host "按 Ctrl+C 或关闭本窗口即可停止 ComfyUI。"
Write-Host ''

$env:PYTHONUNBUFFERED = '1'
$proc = Start-Process -FilePath $python -ArgumentList $cliArgs -WorkingDirectory $root `
    -RedirectStandardOutput $log -RedirectStandardError $logErr -PassThru -NoNewWindow

$positions = @{}
foreach ($f in @($log, $logErr)) { $positions[$f] = 0 }

try {
    while (-not $proc.HasExited) {
        foreach ($f in @($log, $logErr)) {
            if (Test-Path -LiteralPath $f) {
                $len = (Get-Item -LiteralPath $f).Length
                if ($len -gt $positions[$f]) {
                    try {
                        $fs = [System.IO.File]::Open($f, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $fs.Seek($positions[$f], [System.IO.SeekOrigin]::Begin) | Out-Null
                        $buf = New-Object byte[] ($len - $positions[$f])
                        $read = $fs.Read($buf, 0, $buf.Length)
                        $positions[$f] = $fs.Position
                        $fs.Close()
                        $text = [System.Text.Encoding]::UTF8.GetString($buf, 0, $read)
                        if ($text -match [char]0xFFFD) {
                            $text = [System.Text.Encoding]::GetEncoding(936).GetString($buf, 0, $read)
                        }
                        foreach ($line in ($text -split "`r?`n")) {
                            if ($line.Trim() -ne '') { Write-Host $line }
                        }
                    } catch { }
                }
            }
        }
        Start-Sleep -Milliseconds 400
    }
    Write-Host ''
    Write-Host "ComfyUI 已退出（端口 $port）。"
} finally {
    if (-not $proc.HasExited) {
        Write-Host ''
        Write-Host "正在停止 ComfyUI（端口 $port）..."
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

Read-Host '按回车关闭窗口'
