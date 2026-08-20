param([string]$Time = "09:00")
$ErrorActionPreference = "Stop"
$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot "show_reminders.ps1")).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "AI-Pick-Stock-Reminders" -Description "知衡个人投资研究台重要事件提醒" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "已注册 AI-Pick-Stock-Reminders，每天 $Time 检查提醒。"
