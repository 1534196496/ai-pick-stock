param([string]$Time = "18:30", [string]$GlobalTime = "08:30")
$ErrorActionPreference = "Stop"
$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot "run_daily.ps1")).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "AI-Pick-Stock-Daily" -Description "工作日收盘后采集A股行情并生成候选报告" -Action $action -Trigger $trigger -Settings $settings -Force
$globalScript = (Resolve-Path (Join-Path $PSScriptRoot "run_multiasset.ps1")).Path
$globalAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$globalScript`""
$globalTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $GlobalTime
Register-ScheduledTask -TaskName "AI-Pick-Stock-Global-Daily" -Description "美股收盘后刷新全球行情、基金、美债与事件缓存" -Action $globalAction -Trigger $globalTrigger -Settings $settings -Force
Write-Host "已注册 A股任务（工作日 $Time）和全球多资产任务（工作日 $GlobalTime）。"
