@echo off
title The Trading Floor — Launcher
color 0A
cls

echo.
echo  ████████╗██████╗  █████╗ ██████╗ ██╗███╗   ██╗ ██████╗     ███████╗██╗      ██████╗  ██████╗ ██████╗ 
echo     ██╔══╝██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║██╔════╝     ██╔════╝██║     ██╔═══██╗██╔═══██╗██╔══██╗
echo     ██║   ██████╔╝███████║██║  ██║██║██╔██╗ ██║██║  ███╗    █████╗  ██║     ██║   ██║██║   ██║██████╔╝
echo     ██║   ██╔══██╗██╔══██║██║  ██║██║██║╚██╗██║██║   ██║    ██╔══╝  ██║     ██║   ██║██║   ██║██╔══██╗
echo     ██║   ██║  ██║██║  ██║██████╔╝██║██║ ╚████║╚██████╔╝    ██║     ███████╗╚██████╔╝╚██████╔╝██║  ██║
echo     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝    ╚═╝     ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝
echo.
echo  Starting your AI trading firm...
echo  ════════════════════════════════════════════════════════════════
echo.

set PROJECT_DIR=C:\Users\zakob\projects\trading-floor
set FRONTEND_DIR=%PROJECT_DIR%\frontend
set VENV=%PROJECT_DIR%\.venv\Scripts

:: ── Step 1: Start Docker Desktop if not running ──────────────────────────
echo  [1/5] Checking Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo  [1/5] Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo  [1/5] Waiting for Docker to start (this may take 30-60 seconds)...
    :wait_docker
    timeout /t 5 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto wait_docker
)
echo  [1/5] Docker is running ✓

:: ── Step 2: Start infrastructure services ────────────────────────────────
echo  [2/5] Starting Postgres, QuestDB, Redis...
cd /d %PROJECT_DIR%
docker compose up -d >nul 2>&1
echo  [2/5] Infrastructure started ✓

:: ── Step 3: Set up venv if needed ────────────────────────────────────────
echo  [3/5] Checking Python environment...
if not exist "%VENV%\activate.bat" (
    echo  [3/5] Creating virtual environment...
    python -m venv .venv
    call %VENV%\activate.bat
    pip install -e ".[dev]" --quiet
    echo  [3/5] Running migrations...
    alembic upgrade head
) else (
    call %VENV%\activate.bat
)
echo  [3/5] Python environment ready ✓

:: ── Step 4: Start API server ──────────────────────────────────────────────
echo  [4/5] Starting API server...
start "Trading Floor API" cmd /k "cd /d %PROJECT_DIR% && call %VENV%\activate.bat && uvicorn src.api.main:app --reload --port 8000"
timeout /t 3 /nobreak >nul
echo  [4/5] API server started at http://localhost:8000 ✓

:: ── Step 5: Start frontend ────────────────────────────────────────────────
echo  [5/5] Starting dashboard...
start "Trading Floor UI" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"
timeout /t 5 /nobreak >nul
echo  [5/5] Dashboard starting at http://localhost:3000 ✓

:: ── Open browser ─────────────────────────────────────────────────────────
echo.
echo  ════════════════════════════════════════════════════════════════
echo  Opening dashboard in browser...
timeout /t 3 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo  ✓ The Trading Floor is live at http://localhost:3000
echo  ✓ API docs at http://localhost:8000/docs
echo  ✓ Kill switch available on every page
echo.
echo  To start paper trading: open a new terminal and run:
echo    cd %PROJECT_DIR% ^&^& .venv\Scripts\activate ^&^& python scripts\run_paper_trading.py
echo.
pause
