$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$folders = @((Join-Path $projectRoot "data"), (Join-Path $projectRoot "backups"))
foreach ($folder in $folders) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $resolved = (Resolve-Path $folder).Path
    if (-not $resolved.StartsWith($projectRoot)) { throw "Target folder is outside the project root" }
    icacls $resolved /inheritance:r /grant:r "$env:USERNAME`:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to restrict ACL: $resolved" }
    Write-Host "Restricted to current user, SYSTEM and local Administrators: $resolved"
}
