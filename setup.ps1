# J.A.R.V.I.S. setup — installs an isolated 64-bit Python runtime.
# Nothing is installed into the system Python.
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Runtime = Join-Path $Root "runtime"
$Python = Join-Path $Runtime "python.exe"

Write-Host ""
Write-Host "  J.A.R.V.I.S. setup" -ForegroundColor Cyan
Write-Host "  ------------------" -ForegroundColor DarkCyan

if (-not (Test-Path $Python)) {
    Write-Host "  Creating isolated Python 3.12.10 runtime..." -ForegroundColor Yellow
    $Zip = Join-Path $env:TEMP "python-3.12.10-embed-amd64.zip"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" -OutFile $Zip -UseBasicParsing
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    Expand-Archive -Path $Zip -DestinationPath $Runtime -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "Lib\site-packages") | Out-Null
    @(
        "python312.zip",
        ".",
        "Lib\site-packages",
        "import site"
    ) | Set-Content -Path (Join-Path $Runtime "python312._pth") -Encoding ASCII

    $GetPip = Join-Path $env:TEMP "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing
    & $Python $GetPip --no-warn-script-location
}

Write-Host "  Installing dependencies..." -ForegroundColor Yellow
& $Python -m pip install --upgrade pip --no-warn-script-location
& $Python -m pip install -r (Join-Path $Root "requirements.txt") --no-warn-script-location

Write-Host "  Downloading local models..." -ForegroundColor Yellow
& $Python (Join-Path $Root "download_models.py")

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host ""
    Write-Warning "Created .env from .env.example. Add your OPENROUTER_API_KEY before starting."
}

Write-Host ""
Write-Host "  Setup complete." -ForegroundColor Green
Write-Host "  Start with:  .\run.ps1" -ForegroundColor Cyan
Write-Host "  Native window: .\run.ps1 -Window" -ForegroundColor Cyan
Write-Host ""
