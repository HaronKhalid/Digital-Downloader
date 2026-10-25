# PowerShell packaging script for Phase 9 Windows release
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Virtual environment not found at .venv. Run scripts\setup.ps1 first."
}

Write-Host "Running package_app.py to build DigitalDownloader.exe and bundled zip..." -ForegroundColor Cyan
& $py "scripts\package_app.py"

if ($LASTEXITCODE -ne 0) {
    throw "Packaging failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete! Package available in dist\DigitalDownloader\" -ForegroundColor Green
