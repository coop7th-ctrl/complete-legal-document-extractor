@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "API_PORT=8010"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] Python environment not found at %PY%
    echo Create it with:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo Complete Legal Document Extractor
echo API:  http://127.0.0.1:%API_PORT%
echo Docs: http://127.0.0.1:%API_PORT%/docs
echo Press Ctrl+C to stop.
echo.

"%PY%" -m uvicorn server.app:app --host 127.0.0.1 --port %API_PORT%
endlocal
