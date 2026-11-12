@echo off
setlocal
cd /d "%~dp0..\.."
if errorlevel 1 exit /b 1
set "UV_CACHE_DIR=%CD%\.cache\uv"
if defined NO_PROXY (
    set "NO_PROXY=%NO_PROXY%,127.0.0.1,localhost,::1"
) else (
    set "NO_PROXY=127.0.0.1,localhost,::1"
)
set "no_proxy=%NO_PROXY%"
set "OCR_DEVICE=cuda"
uv run --locked --extra ocr-gpu uvicorn app.main:app --host 127.0.0.1 --port 8309 %*
exit /b %ERRORLEVEL%
