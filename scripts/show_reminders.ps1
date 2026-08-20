$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command py -ErrorAction Stop).Source
    $pythonArgs = @("-3.12")
} else {
    $pythonArgs = @()
}
$output = & $pythonExe @pythonArgs -m stock_picker.reminders --config (Join-Path $projectRoot "config.toml") --json
$events = $output | ConvertFrom-Json
if (-not $events -or $events.Count -eq 0) { exit 0 }
$body = ($events | Select-Object -First 4 | ForEach-Object { "$($_.days_left)天后 · $($_.title)" }) -join "`n"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notice = New-Object System.Windows.Forms.NotifyIcon
$notice.Icon = [System.Drawing.SystemIcons]::Information
$notice.BalloonTipTitle = "知衡 · 重要事件提醒"
$notice.BalloonTipText = $body
$notice.Visible = $true
$notice.ShowBalloonTip(10000)
Start-Sleep -Seconds 12
$notice.Dispose()

