# Reports whether the tools Personal Media needs are available. Read-only.
$ErrorActionPreference = "Continue"

function Show-Status([string]$Name, [bool]$Ok, [string]$Detail) {
    $mark = if ($Ok) { "[OK]     " } else { "[MISSING]" }
    Write-Host ("{0} {1,-8} {2}" -f $mark, $Name, $Detail)
}

# Sync User PATH changes and check bin / FFMPEG_PATH / .env
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root "bin"
if (Test-Path $bin) {
    $env:Path = "$bin;$env:Path"
}

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue

if (-not $ffmpeg -and (Test-Path (Join-Path $root ".env"))) {
    Get-Content (Join-Path $root ".env") | ForEach-Object {
        if ($_ -match "^\s*FFMPEG_PATH\s*=\s*(.+)$") {
            $val = $matches[1].Trim().Trim('"').Trim("'")
            if ($val -and (Test-Path $val)) {
                $ffmpeg = $val
                $env:Path = (Split-Path -Parent $val) + ";" + $env:Path
            }
        }
    }
}

if (-not $ffmpeg) {
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath) {
        $userPath = [System.Environment]::ExpandEnvironmentVariables($userPath)
        foreach ($p in ($userPath -split ';')) {
            $trimmed = $p.Trim().TrimEnd('\')
            if ($trimmed -and (Test-Path (Join-Path $trimmed "ffmpeg.exe"))) {
                $ffmpeg = Join-Path $trimmed "ffmpeg.exe"
                $env:Path = "$trimmed;$env:Path"
                break
            }
        }
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $v = (& python --version) 2>&1
    $ok = $v -match "Python 3\.(1[2-9]|[2-9][0-9])"
    Show-Status "Python" $ok "$v (3.12 or newer required)"
} else {
    Show-Status "Python" $false "Not found. Install Python 3.12+ from python.org."
}

if ($ffmpeg) {
    $line = (& $ffmpeg -version 2>&1 | Select-Object -First 1)
    Show-Status "FFmpeg" $true "$line"
} else {
    Show-Status "FFmpeg" $false "FFmpeg was not detected. Install FFmpeg, add it to PATH, and restart the application."
}

$git = Get-Command git -ErrorAction SilentlyContinue
Show-Status "Git" ([bool]$git) $(if ($git) { (& git --version) } else { "Not found (optional, needed for version control)." })
