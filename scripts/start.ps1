# Starts Digital Downloader on http://127.0.0.1:8000 (loopback only) and opens the browser.
param(
    [switch]$Reload,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Sync User PATH changes (e.g. newly installed tools from winget) if not yet in current session
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    foreach ($p in ($userPath -split ';')) {
        if ($p -and (Test-Path $p) -and ($env:Path -split ';' -notcontains $p)) {
            $env:Path = "$p;$env:Path"
        }
    }
}

$bin = Join-Path $root "bin"
if (Test-Path $bin) {
    $env:Path = "$bin;$env:Path"
}

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Virtual environment not found. Run scripts\setup.ps1 first." }

$port = if ($env:PORT) { $env:PORT } else { "8000" }
$url = "http://127.0.0.1:$port/"

if (-not $NoBrowser) {
    Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 2; Start-Process $u } -ArgumentList $url | Out-Null
}

# The host is deliberately hard-coded to loopback. Do not change it to 0.0.0.0.
$args = @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", $port)
if ($Reload) { $args += "--reload" }

Write-Host "Digital Downloader running at $url (press Ctrl+C to stop)"
& $py @args
