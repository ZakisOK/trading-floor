# run.ps1 — Windows equivalent of Makefile
# Usage: .\run.ps1 <target>
# Example: .\run.ps1 migrate

param([string]$Target = "help")

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Activate-Venv {
    $venvPath = "$ProjectRoot\.venv\Scripts\Activate.ps1"
    if (Test-Path $venvPath) {
        & $venvPath
    } else {
        Write-Host "Creating virtual environment..." -ForegroundColor Yellow
        python -m venv .venv
        & $venvPath
        pip install -e ".[dev]" --quiet
    }
}

switch ($Target) {
    "setup" {
        Write-Host "Setting up environment..." -ForegroundColor Cyan
        python -m venv .venv
        .\.venv\Scripts\Activate.ps1
        pip install -e ".[dev]"
        Write-Host "Setup complete." -ForegroundColor Green
    }
    "dev" {
        Write-Host "Starting Docker services..." -ForegroundColor Cyan
        docker compose up -d
        Activate-Venv
        Write-Host "Starting API server at http://localhost:8000" -ForegroundColor Green
        uvicorn src.api.main:app --reload --port 8000
    }
    "run" {
        Activate-Venv
        Write-Host "Starting API server (production) at http://localhost:8000" -ForegroundColor Green
        uvicorn src.api.main:app --port 8000
    }
    "migrate" {
        Write-Host "Running database migrations..." -ForegroundColor Cyan
        Activate-Venv
        alembic upgrade head
        Write-Host "Migrations complete." -ForegroundColor Green
    }
    "seed" {
        Activate-Venv
        python scripts\seed_db.py
    }
    "test" {
        Activate-Venv
        pytest tests\ -v --asyncio-mode=auto
    }
    "lint" {
        Activate-Venv
        ruff check src\ tests\
        mypy src\
    }
    "format" {
        Activate-Venv
        ruff format src\ tests\
    }
    "paper-trade" {
        Write-Host "Starting paper trading loop..." -ForegroundColor Cyan
        Write-Host "Symbols: BTC/USDT, ETH/USDT, SOL/USDT | Cycle: 5 min" -ForegroundColor Yellow
        Activate-Venv
        python scripts\run_paper_trading.py
    }
    "monitors" {
        Write-Host "Starting real-time monitors..." -ForegroundColor Cyan
        Write-Host "Position monitor: 5s | Risk monitor: 30s" -ForegroundColor Yellow
        Activate-Venv
        python scripts\run_monitors.py
    }
    "backtest" {
        Activate-Venv
        python scripts\run_backtest.py
    }
    "bootstrap" {
        Activate-Venv
        python scripts\bootstrap_streams.py
    }
    "briefing" {
        Activate-Venv
        Write-Host "Fetching trading briefing..." -ForegroundColor Cyan
        $response = Invoke-RestMethod -Uri "http://localhost:8000/api/briefing"
        $response | ConvertTo-Json -Depth 10
    }
    "docker-up" {
        docker compose up -d
        Write-Host "Services started: postgres (5432), questdb (9000), redis (6379)" -ForegroundColor Green
    }
    "docker-down" {
        docker compose down
    }
    "docker-logs" {
        docker compose logs -f
    }
    "frontend" {
        Set-Location frontend
        if (-not (Test-Path "node_modules")) {
            Write-Host "Installing npm packages..." -ForegroundColor Yellow
            npm install
        }
        Write-Host "Starting frontend at http://localhost:3000" -ForegroundColor Green
        npm run dev
    }
    "kill-switch" {
        Write-Host "ACTIVATING KILL SWITCH" -ForegroundColor Red
        Activate-Venv
        python -c "import asyncio; from src.core.security import activate_kill_switch; asyncio.run(activate_kill_switch('manual', 'operator'))"
    }
    "help" {
        Write-Host ""
        Write-Host "The Trading Floor — Available Commands" -ForegroundColor Cyan
        Write-Host "======================================" -ForegroundColor Cyan
        Write-Host "  .\run.ps1 setup        — Create venv and install dependencies"
        Write-Host "  .\run.ps1 docker-up    — Start Postgres, QuestDB, Redis"
        Write-Host "  .\run.ps1 migrate      — Run Alembic DB migrations"
        Write-Host "  .\run.ps1 bootstrap    — Create Redis consumer groups"
        Write-Host "  .\run.ps1 dev          — Start API server (dev mode, hot reload)"
        Write-Host "  .\run.ps1 run          — Start API server (production mode)"
        Write-Host "  .\run.ps1 frontend     — Start Next.js frontend"
        Write-Host "  .\run.ps1 paper-trade  — Start paper trading loop (5 min cycles)"
        Write-Host "  .\run.ps1 monitors     — Start position + risk monitors (5s/30s)"
        Write-Host "  .\run.ps1 briefing     — Fetch trading briefing from API"
        Write-Host "  .\run.ps1 test         — Run test suite"
        Write-Host "  .\run.ps1 lint         — Run ruff + mypy"
        Write-Host "  .\run.ps1 format       — Auto-format with ruff"
        Write-Host "  .\run.ps1 seed         — Seed the database"
        Write-Host "  .\run.ps1 backtest     — Run backtest script"
        Write-Host "  .\run.ps1 kill-switch  — Emergency stop all trading"
        Write-Host "  .\run.ps1 docker-down  — Stop all Docker services"
        Write-Host "  .\run.ps1 docker-logs  — Tail Docker service logs"
        Write-Host ""
        Write-Host "Quick start:" -ForegroundColor Yellow
        Write-Host "  .\run.ps1 setup"
        Write-Host "  .\run.ps1 docker-up"
        Write-Host "  .\run.ps1 migrate"
        Write-Host "  .\run.ps1 paper-trade   # Terminal 1"
        Write-Host "  .\run.ps1 monitors      # Terminal 2 — exits fire here"
        Write-Host "  .\run.ps1 frontend      # Terminal 3"
        Write-Host ""
    }
    default {
        Write-Host "Unknown target: $Target" -ForegroundColor Red
        Write-Host "Run .\run.ps1 help for available commands"
    }
}
