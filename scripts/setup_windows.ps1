# MuratJARVIS - Windows kurulumu
# Kullanim:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python Launcher (py) bulunamadi. python.org'dan Python 3.12 kurun." }

# pyproject.toml: requires-python = ">=3.11,<3.14".
# (v25'teki betik 3.14'u de kabul ediyordu; PyQt6/numpy tekerlekleri orada yok.)
$installed = (& py -0p 2>$null | Out-String)
$pythonVersion = $null
foreach ($candidate in @("3.12", "3.11")) {
    if ($installed -match [regex]::Escape($candidate)) { $pythonVersion = $candidate; break }
}
if (-not $pythonVersion) { throw "Python 3.11 veya 3.12 bulunamadi (3.13+ henuz desteklenmiyor)." }

if (Test-Path ".venv\Scripts\python.exe") {
    $venvVersion = (& .\.venv\Scripts\python.exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($venvVersion -ne $pythonVersion) { Remove-Item -Recurse -Force ".venv" }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) { & py -$pythonVersion -m venv .venv }

$python = Join-Path $Root ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip --no-cache-dir
if ($LASTEXITCODE -ne 0) { throw "pip guncellenemedi." }

# Kaynak duzeni (src/jarvis) + bagimliliklar tek komutta:
& $python -m pip install --no-cache-dir -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Bagimlilik kurulumu basarisiz oldu." }

& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Host "Uyari: Playwright tarayicisi kurulamadi; web otomasyonu calismayacak." -ForegroundColor Yellow }

& $python -c "import jarvis, PyQt6, numpy, sounddevice, fastapi; print('import kontrolu OK', jarvis.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Kurulum dogrulamasi basarisiz oldu." }

Write-Host "Kurulum tamamlandi." -ForegroundColor Green
Write-Host 'API anahtari: [Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "YENI_ANAHTAR", "User")'
Write-Host "Calistirma:   .\.venv\Scripts\python.exe -m jarvis   (veya .venv\Scripts\jarvis.exe)"
Write-Host "Kullanici verisi: %LOCALAPPDATA%\MuratJARVIS  (memory/, logs/, tasks/, config/)"
