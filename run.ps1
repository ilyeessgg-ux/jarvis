param(
    [switch]$Window,
    [switch]$Background,
    [switch]$Tray,
    [switch]$NoBrowser,
    [switch]$NoGreeting,
    [switch]$NoHotkeys,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Join-Path $Root "runtime\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "JARVIS runtime not found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "No .env found. Copy .env.example to .env and add your OpenRouter key." -ForegroundColor Red
    exit 1
}

$Arguments = @()
if ($Window) { $Arguments += "--window" }
if ($Background) { $Arguments += "--background" }
if ($Tray) { $Arguments += "--tray" }
if ($NoBrowser) { $Arguments += "--no-browser" }
if ($NoGreeting) { $Arguments += "--no-greeting" }
if ($NoHotkeys) { $Arguments += "--no-hotkeys" }
if ($Port -gt 0) { $Arguments += @("--port", [string]$Port) }

Push-Location $Root
try {
    & $Python "app.py" @Arguments
} finally {
    Pop-Location
}
