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
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logFolder "$stamp-recommendations.log"
$errorLogPath = Join-Path $logFolder "$stamp-recommendations.stderr.log"
$commandArguments = @($pythonPrefix) + @(
    "-m", "stock_picker.cli", "--config", (Join-Path $projectRoot "config.toml"),
    "recommend", "--asset", "all"
)
$process = Start-Process -FilePath $pythonExe -ArgumentList $commandArguments -WorkingDirectory $projectRoot `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $logPath -RedirectStandardError $errorLogPath
$exitCode = $process.ExitCode
if (Test-Path $errorLogPath) {
    Get-Content -LiteralPath $errorLogPath | Add-Content -LiteralPath $logPath
    Remove-Item -LiteralPath $errorLogPath -Force
}
Get-Content -LiteralPath $logPath
if ($exitCode -ne 0) { throw "Recommendation task failed with exit code $exitCode" }
