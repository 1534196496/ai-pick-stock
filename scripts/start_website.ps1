param([int]$Port = 8501)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$healthUrl = "http://127.0.0.1:$Port/_stcore/health"

try {
    $health = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 3
    if ($health.StatusCode -eq 200) {
        Write-Host "ZhiHeng is already running: http://127.0.0.1:$Port"
        exit 0
    }
} catch {
    # No healthy local server is running; continue with startup.
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python runtime not found. Recreate .venv before starting the website."
    }
    $pythonExe = $pythonCommand.Source
}

$sourceRoot = Join-Path $projectRoot "src"
$existingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$env:PYTHONPATH = if ($existingPythonPath) { "$sourceRoot;$existingPythonPath" } else { $sourceRoot }

Write-Host "ZhiHeng listens locally only: http://127.0.0.1:$Port"
& $pythonExe -m streamlit run (Join-Path $projectRoot "dashboard.py") `
    --server.address 127.0.0.1 --server.port $Port --server.headless true
if ($LASTEXITCODE -ne 0) {
    throw "Website process exited with code $LASTEXITCODE"
}
