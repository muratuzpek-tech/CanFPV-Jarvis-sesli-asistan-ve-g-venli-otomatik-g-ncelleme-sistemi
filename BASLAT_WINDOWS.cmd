@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Yerel .venv bulunamadi. Once KUR_WINDOWS.cmd calistirin.
    exit /b 1
)
"%VENV_PY%" -m jarvis %*
exit /b %errorlevel%
