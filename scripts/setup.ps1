# One-time setup: creates .venv, installs pinned dependencies, creates .env.
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.12 or newer and run this script again."
}
$version = [version](& python -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))")
if ($version -lt [version]"3.12") {
    throw "Python 3.12 or newer is required (found $version)."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    & python -m venv .venv
}
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"

Write-Host "Installing dependencies..."
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r backend\requirements-dev.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

Write-Host ""
& "$PSScriptRoot\check_dependencies.ps1"
Write-Host ""
Write-Host "Setup complete. Start the app with: scripts\start.ps1"
