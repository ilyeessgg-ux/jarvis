# Build the portable Windows release: dist\JARVIS\JARVIS.exe
param(
    [switch]$Clean,
    # Python interpreter to build with. Defaults to the isolated runtime.
    [string]$Python
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $Python) {
    $Python = Join-Path $Root "runtime\python.exe"
}
$Dist = Join-Path $Root "dist\JARVIS"
$Version = "1.0.0"
$Zip = Join-Path $Root "dist\JARVIS-$Version-win64.zip"

if (-not (Test-Path $Python)) {
    Write-Host "JARVIS runtime not found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  J.A.R.V.I.S. Windows build" -ForegroundColor Cyan
Write-Host "  -------------------------" -ForegroundColor DarkCyan

if (-not (Test-Path (Join-Path $Root "assets\jarvis.ico"))) {
    & $Python (Join-Path $Root "scripts\make_icon.py")
}

$WakeModel = Join-Path $Root "models\openwakeword\hey_jarvis_v0.1.onnx"
$WhisperModel = Join-Path $Root "models\whisper\base.en\model.bin"
if ((-not (Test-Path $WakeModel)) -or (-not (Test-Path $WhisperModel))) {
    Write-Host "  Downloading local models..." -ForegroundColor Yellow
    & $Python (Join-Path $Root "download_models.py")
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Installing build tools..." -ForegroundColor Yellow
    & $Python -m pip install -r (Join-Path $Root "requirements-dev.txt") --no-warn-script-location
}

$Arguments = @("-m", "PyInstaller", (Join-Path $Root "jarvis.spec"), "--noconfirm")
if ($Clean) { $Arguments += "--clean" }

Write-Host "  Packaging..." -ForegroundColor Yellow
Push-Location $Root
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

# Ship a placeholder config next to the exe so the path is easy to find.
Copy-Item (Join-Path $Root ".env.example") (Join-Path $Dist ".env") -Force
foreach ($Doc in @("README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md")) {
    $Source = Join-Path $Root $Doc
    if (Test-Path $Source) { Copy-Item $Source $Dist -Force }
}

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Write-Host "  Compressing..." -ForegroundColor Yellow
Compress-Archive -Path (Join-Path $Dist "*") -DestinationPath $Zip -CompressionLevel Optimal

$Size = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Write-Host ""
Write-Host "  Build complete." -ForegroundColor Green
Write-Host "  App      $Dist\JARVIS.exe" -ForegroundColor Cyan
Write-Host "  Archive  $Zip ($Size MB)" -ForegroundColor Cyan
Write-Host ""
