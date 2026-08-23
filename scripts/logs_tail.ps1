# MPWE combined log viewer: tails WebUI + ComfyUI logs live.
# Press q to stop (the launcher then quits all services).
$ErrorActionPreference = 'SilentlyContinue'

$logs = @('data\logs\webui.log', 'data\logs\comfyui_8188.log')
$labels = @('[WebUI]  ', '[ComfyUI]')
$positions = @{}
foreach ($f in $logs) { $positions[$f] = 0 }

Write-Host '=== MPWE logs (live). Press q to quit all services ==='

while ($true) {
    try {
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq 'Q') { break }
        }
    } catch {
        # no interactive console; keep tailing until killed
    }
    for ($i = 0; $i -lt $logs.Count; $i++) {
        $f = $logs[$i]
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
                    $text = ''
                    try { $text = [System.Text.Encoding]::UTF8.GetString($buf, 0, $read) } catch { }
                    if ($text -match [char]0xFFFD) { $text = [System.Text.Encoding]::GetEncoding(936).GetString($buf, 0, $read) }
                    foreach ($line in ($text -split "`r?`n")) {
                        if ($line.Trim() -ne '') { Write-Host ($labels[$i] + ' ' + $line) }
                    }
                } catch { }
            }
        }
    }
    Start-Sleep -Milliseconds 300
}

Write-Host ''
Write-Host 'q pressed, stopping...'
