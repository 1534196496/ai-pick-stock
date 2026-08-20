param([int]$Port = 8501)
$ErrorActionPreference = "Stop"
$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot "start_website.ps1")).Path
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $powershellExe)) {
    throw "Windows PowerShell not found: $powershellExe"
}

$action = New-ScheduledTaskAction `
    -Execute $powershellExe `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`" -Port $Port" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "Investment-Research-Website" `
    -Description "Start the local ZhiHeng investment research website after user logon" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $env:USERNAME `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "Website autostart registered for $env:USERNAME on port $Port."
