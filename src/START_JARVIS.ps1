# UTF-8 Kodlama Desteğini Hem PowerShell Hem de Python için Aktif Eder
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "[JARVIS-PS] Sistem UTF-8 koruma modunda baslatiliyor..." -ForegroundColor Cyan

# .venv kontrolü ve ana backend başlatma tetikleyicisi
$venvPython = "..\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m jarvis
} else {
    Write-Host "[HATA] Sanal ortam (.venv) bulunamadi! Once kurulumu tamamlayin." -ForegroundColor Red
}
