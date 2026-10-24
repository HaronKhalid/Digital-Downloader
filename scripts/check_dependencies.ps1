# Reports whether the tools Personal Media needs are available. Read-only.
$ErrorActionPreference = "Continue"

function Show-Status([string]$Name, [bool]$Ok, [string]$Detail) {
    $mark = if ($Ok) { "[OK]     " } else { "[MISSING]" }
    Write-Host ("{0} {1,-8} {2}" -f $mark, $Name, $Detail)
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $v = (& python --version) 2>&1
    $ok = $v -match "Python 3\.(1[2-9]|[2-9][0-9])"
    Show-Status "Python" $ok "$v (3.12 or newer required)"
} else {
    Show-Status "Python" $false "Not found. Install Python 3.12+ from python.org."
}

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    $line = (& ffmpeg -version 2>&1 | Select-Object -First 1)
    Show-Status "FFmpeg" $true "$line"
} else {
    Show-Status "FFmpeg" $false "FFmpeg was not detected. Install FFmpeg, add it to PATH, and restart the application."
}

$git = Get-Command git -ErrorAction SilentlyContinue
Show-Status "Git" ([bool]$git) $(if ($git) { (& git --version) } else { "Not found (optional, needed for version control)." })
