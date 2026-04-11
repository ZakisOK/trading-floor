@echo off
echo Starting The Trading Floor...
echo.
echo Step 1: Starting Docker services...
docker compose up -d
echo.
echo Step 2: Starting API server...
start "Trading Floor API" cmd /k "cd /d %~dp0 && .venv\Scripts\activate && uvicorn src.api.main:app --reload --port 8000"
echo.
echo Step 3: Starting frontend...
start "Trading Floor UI" cmd /k "cd /d %~dp0\frontend && npm run dev"
echo.
echo Open http://localhost:3000 in your browser.
echo API docs at http://localhost:8000/docs
pause
