param([string]$Time = "22:30")
$ErrorActionPreference = "Stop"
$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot "run_recommendations.ps1")).Path
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $powershellExe)) { throw "Windows PowerShell not found: $powershellExe" }
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Investment-Research-Recommendations" -Description "Refresh full A-share and China fund snapshots, analyze and publish versioned research candidates" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Recommendation task registered for weekdays at $Time."
