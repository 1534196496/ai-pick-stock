$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
& py -3.12 (Join-Path $PSScriptRoot "backup_database.py") backup
if ($LASTEXITCODE -ne 0) { throw "Database backup failed" }
$backupFolder = Join-Path $projectRoot "backups"
if (Test-Path $backupFolder) {
    icacls $backupFolder /inheritance:r /grant:r "$env:USERNAME`:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to restrict backup folder ACL" }
}
