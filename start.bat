@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
title Scira 一键启动

REM ============================================================
REM  Scira Windows 一键启动脚本
REM  - 检查 Python / Node 环境
REM  - 自动安装后端 / 前端依赖（首次运行）
REM  - 同时启动后端 (:8001) 与前端 (:5173)
REM ============================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   Scira 一键启动
echo ============================================================
echo.

REM ---- 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)

REM ---- 检查 Node ----
where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Node.js，请先安装 Node.js 16+ 并加入 PATH。
    pause
    exit /b 1
)

REM ---- 检查 npm ----
where npm >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 npm，请随 Node.js 一同安装。
    pause
    exit /b 1
)

REM ---- 检查 .env ----
if not exist ".env" (
    if exist ".env.example" (
        echo [提示] 未发现 .env，从 .env.example 复制...
        copy /Y ".env.example" ".env" >nul
        echo [警告] 请编辑 .env 填入 API Key 后重新运行本脚本。
        notepad ".env"
        pause
        exit /b 0
    ) else (
        echo [错误] 未找到 .env 或 .env.example，请先创建 .env。
        pause
        exit /b 1
    )
)

REM ---- 后端依赖 ----
if not exist ".venv" (
    echo [步骤] 创建 Python 虚拟环境 .venv ...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo [步骤] 检查后端依赖...
pip show scira >nul 2>nul
if errorlevel 1 (
    echo [步骤] 安装后端依赖（首次运行较慢）...
    pip install -e .
    if errorlevel 1 (
        echo [错误] 后端依赖安装失败。
        pause
        exit /b 1
    )
)

REM ---- 前端依赖 ----
if not exist "frontend\node_modules" (
    echo [步骤] 安装前端依赖（首次运行较慢）...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [错误] 前端依赖安装失败。
        popd
        pause
        exit /b 1
    )
    popd
)

REM ---- 启动后端（新窗口）----
echo [步骤] 启动后端服务 http://localhost:8001 ...
start "Scira Backend" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && python -m src.mcp.server"

REM ---- 启动前端（新窗口）----
echo [步骤] 启动前端服务 http://localhost:5173 ...
start "Scira Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo.
echo ============================================================
echo   启动完成！
echo   后端: http://localhost:8001
echo   前端: http://localhost:5173
echo   关闭服务: 直接关闭弹出的两个命令行窗口
echo ============================================================
echo.
echo 本窗口可以关闭。如需停止服务请关闭后端/前端窗口。
pause
endlocal
