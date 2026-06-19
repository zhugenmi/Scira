@echo off
setlocal
title Scira One-Click Start

REM ============================================================
REM  Scira Windows one-click start script
REM  ASCII + CRLF only. No delayed expansion needed.
REM ============================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   Scira One-Click Start
echo ============================================================
echo.

REM ---- Check Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    goto :end
)

REM ---- Check Node ----
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 16+ and add to PATH.
    goto :end
)

REM ---- Check npm ----
where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found. Install npm together with Node.js.
    goto :end
)

REM ---- Check .env ----
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] .env not found, copying from .env.example ...
        copy /Y ".env.example" ".env" >nul
        echo [WARN] Edit .env to fill in your API Key, then re-run this script.
        notepad ".env"
        goto :end
    ) else (
        echo [ERROR] Neither .env nor .env.example found.
        goto :end
    )
)

REM ---- Create venv if missing ----
if not exist ".venv\Scripts\python.exe" (
    echo [STEP] Creating Python virtual env .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        goto :end
    )
    echo [STEP] Upgrading pip via Tsinghua mirror ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 300
)

REM ---- Backend deps ----
REM Use Tsinghua mirror to avoid PyPI read timeouts in CN.
set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
echo [STEP] Checking backend deps ...
".venv\Scripts\python.exe" -m pip show scira >nul 2>nul
if errorlevel 1 (
    echo [STEP] Installing backend deps via Tsinghua mirror ...
    echo [STEP] This may take several minutes on first run, please wait ...
    ".venv\Scripts\python.exe" -m pip install -e . -i %PIP_MIRROR% --timeout 300 --retries 10
    if errorlevel 1 (
        echo [ERROR] Backend deps install failed.
        echo [HINT] Check network, or edit PIP_MIRROR in start.bat to use another mirror.
        goto :end
    )
) else (
    echo [INFO] Backend deps already installed.
)

REM ---- Frontend deps ----
if not exist "frontend\node_modules" (
    echo [STEP] Installing frontend deps, first run may be slow ...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [ERROR] Frontend deps install failed.
        popd
        goto :end
    )
    popd
) else (
    echo [INFO] Frontend deps already installed.
)

REM ---- Start backend (new window) ----
echo [STEP] Starting backend at http://localhost:8001 ...
start "Scira Backend" cmd /k "cd /d "%~dp0" && set "PYTHONPATH=%~dp0" && .venv\Scripts\python.exe -m src.mcp.server"

REM ---- Start frontend (new window) ----
echo [STEP] Starting frontend at http://localhost:5173 ...
start "Scira Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ============================================================
echo   Started successfully.
echo   Backend:  http://localhost:8001
echo   Frontend: http://localhost:5173
echo   To stop: close the two popped-up windows.
echo ============================================================

:end
echo.
echo Press any key to close this window ...
pause >nul
endlocal
