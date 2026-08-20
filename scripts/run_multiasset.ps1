$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonPrefix = @()
$logFolder = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
if (-not (Test-Path $pythonExe)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $pythonExe = $launcher.Source
        $pythonPrefix = @("-3.12")
    } else {
        $launcher = Get-Command python -ErrorAction Stop
        $pythonExe = $launcher.Source
    }
}
$stamp = Get-Date -Format "yyyyMMdd"
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pythonExe @pythonPrefix -m stock_picker.cli --config (Join-Path $projectRoot "config.toml") multiasset *>&1 | Tee-Object -FilePath (Join-Path $logFolder "$stamp-multiasset.log")
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($exitCode -ne 0) { throw "多资产每日任务执行失败，退出码 $exitCode" }
