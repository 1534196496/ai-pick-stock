param([Parameter(Mandatory=$true)][string]$BackupFile)
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = (Resolve-Path $BackupFile).Path
$destination = Join-Path $projectRoot "data\stocks.db"
$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8501 }
if ($listeners) { throw "Stop the website on port 8501 before restoring the database" }
$lock = Join-Path $projectRoot "data\.maintenance.lock"
if (Test-Path $lock) { throw "A maintenance task is already running" }
$writerLock = Join-Path $projectRoot "data\.writer.lock"
if (Test-Path $writerLock) { throw "A database writer task is running; wait before restore" }
New-Item -ItemType File -Path $lock | Out-Null
try {
    $pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) { $pythonExe = "py" }
    if ($pythonExe -eq "py") {
        & py -3.12 (Join-Path $PSScriptRoot "backup_database.py") restore --source $source --destination $destination
    } else {
        & $pythonExe (Join-Path $PSScriptRoot "backup_database.py") restore --source $source --destination $destination
    }
    if ($LASTEXITCODE -ne 0) { throw "Database restore failed" }
} finally {
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}
Write-Host "Restore complete; a before-restore safety backup was retained."
