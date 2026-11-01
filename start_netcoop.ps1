<#!
.SYNOPSIS
  Starts NetCoop from its own folder and proves the local dashboard is healthy
  before opening a browser. This script contains no machine-specific path.
#>
[CmdletBinding()]
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-NetCoopPython {
    # NETCOOP_PYTHON is the explicit, portable override documented in
    # START_HERE.md.  The remaining paths cover the normal venv location and
    # current official Windows Python installs (including pythoncore-3.14-*).
    $localPythonRoots = @()
    if ($env:LOCALAPPDATA) {
        $localPythonRoots = Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Python') -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'python.exe' }
    }
    $candidates = @(
        $env:NETCOOP_PYTHON,
        (Join-Path $Root '.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Python\bin\python.exe'),
        $localPythonRoots,
        'C:\Python312\python.exe',
        'C:\Python311\python.exe'
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($candidate in $candidates) {
        try {
            $version = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $version -match '^Python 3\.(1[1-4]|9)') { return $candidate }
        } catch { }
    }
    throw "Python 3.11+ was not found. Install Python 3.11 through 3.14, or set NETCOOP_PYTHON to its python.exe path."
}

function Get-NetCoopHealth {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 -ErrorAction Stop
        $capabilities = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/capabilities' -TimeoutSec 2 -ErrorAction Stop
        if ($health.ok -and $capabilities.build_capabilities -contains 'auto_refreshed_database_status') { return $health }
    } catch { }
    $null
}

function Test-OldNetCoopListener {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 -ErrorAction Stop
        return $health.mode -eq 'evidence-only'
    } catch { return $false }
}

function Stop-StaleNetCoop {
    # Stop only a listener whose command line is this project's server.py.
    # This prevents a prior build from being reused after an update.
    $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) { return }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $confirmedOldNetCoop = Test-OldNetCoopListener
    if (($processInfo -and $processInfo.CommandLine -match [regex]::Escape($Root) -and $processInfo.CommandLine -match 'server\.py') -or $confirmedOldNetCoop) {
        Write-Host "Stopping previous NetCoop server (PID $($listener.OwningProcess)) to apply this update." -ForegroundColor Yellow
        Stop-Process -Id $listener.OwningProcess -Force
        Start-Sleep -Milliseconds 500
    } else {
        throw 'Port 8000 is in use by a process that is not this NetCoop project. Close that process or free port 8000, then retry.'
    }
}

$existing = Get-NetCoopHealth
if ($existing) {
    Write-Host 'NetCoop is already running on http://127.0.0.1:8000' -ForegroundColor Green
} else {
    Stop-StaleNetCoop
    $python = Find-NetCoopPython
    Write-Host "Starting NetCoop with $python" -ForegroundColor Cyan
    $logDirectory = Join-Path $Root 'work'
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $stdoutLog = Join-Path $logDirectory 'netcoop-server.stdout.log'
    $stderrLog = Join-Path $logDirectory 'netcoop-server.stderr.log'
    Remove-Item -LiteralPath $stdoutLog,$stderrLog -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $python -ArgumentList @('-u', 'server.py') -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
    $healthy = $null
    foreach ($attempt in 1..20) { Start-Sleep -Milliseconds 500; $healthy = Get-NetCoopHealth; if ($healthy) { break } }
    if (-not $healthy) {
        $errorDetail = if (Test-Path $stderrLog) { (Get-Content -Raw $stderrLog).Trim() } else { '' }
        if ($null -ne $process -and $process.HasExited) { throw "NetCoop exited with code $($process.ExitCode). Details: $errorDetail" }
        throw "NetCoop did not pass its health check within 10 seconds. Port 8000 may be occupied or blocked. Startup log: $stderrLog"
    }
    Write-Host "NetCoop is healthy (PID $($process.Id)): http://127.0.0.1:8000" -ForegroundColor Green
}

if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8000' }
