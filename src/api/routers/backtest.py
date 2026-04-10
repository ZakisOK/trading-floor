"""Backtesting API router."""
from __future__ import annotations

import uuid
from datetime import datetime, UTC, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.data.repositories.ohlcv_repo import OHLCVRepository
from src.backtesting.engine import BacktestEngine, BacktestConfig
from src.backtesting.strategies import AVAILABLE_STRATEGIES

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# In-memory job store (replaced with Redis in Phase 3+)
_jobs: dict[str, dict] = {}


class BacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    exchange: str = "binance"
    timeframe: str = "1m"
    strategy: str = "sma_crossover"
    params: dict[str, Any] = Field(default_factory=dict)
    initial_equity: float = 10000.0
    hours: int = Field(default=168, le=8760)  # max 1 year


class BacktestResponse(BaseModel):
    job_id: str
    status: str


class BacktestResultResponse(BaseModel):
    job_id: str
    status: str
    symbol: str | None = None
    strategy: str | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    total_trades: int | None = None
    total_return_pct: float | None = None
    cagr: float | None = None
    equity_curve: list[float] | None = None
    trades: list[dict] | None = None
    error: str | None = None


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(
    req: BacktestRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> BacktestResponse:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "request": req.model_dump()}
    background_tasks.add_task(_run_backtest_job, job_id, req, session)
    return BacktestResponse(job_id=job_id, status="running")


async def _run_backtest_job(
    job_id: str, req: BacktestRequest, session: AsyncSession
) -> None:
    try:
        repo = OHLCVRepository(session)
        end = datetime.now(UTC)
        start = end - timedelta(hours=req.hours)
        bars = await repo.get_bars(
            req.symbol, req.exchange, req.timeframe, start, end, limit=10_000
        )
        if not bars:
            _jobs[job_id] = {"status": "error", "error": "No data found for the given parameters"}
            return
        strategy_factory = AVAILABLE_STRATEGIES.get(req.strategy)
        if not strategy_factory:
            _jobs[job_id] = {"status": "error", "error": f"Unknown strategy: {req.strategy}"}
            return
        strategy_fn = strategy_factory(**req.params)
        config = BacktestConfig(
            symbol=req.symbol,
            exchange=req.exchange,
            timeframe=req.timeframe,
            initial_equity=req.initial_equity,
            strategy_params={"name": req.strategy, **req.params},
        )
        engine = BacktestEngine(config)
        result = await engine.run(bars, strategy_fn)
        _jobs[job_id] = {
            "status": "done",
            "symbol": req.symbol,
            "strategy": req.strategy,
            "sharpe_ratio": result.metrics.sharpe_ratio,
            "sortino_ratio": result.metrics.sortino_ratio,
            "max_drawdown_pct": result.metrics.max_drawdown_pct,
            "win_rate": result.metrics.win_rate,
            "profit_factor": result.metrics.profit_factor,
            "total_trades": result.metrics.total_trades,
            "total_return_pct": result.metrics.total_return_pct,
            "cagr": result.metrics.cagr,
            "equity_curve": result.equity_curve[-500:],
            "trades": [
                {
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "entry": t.entry_time.isoformat(),
                    "exit": t.exit_time.isoformat(),
                    "reason": t.exit_reason,
                }
                for t in result.trades[-100:]
            ],
        }
    except Exception as e:
        _jobs[job_id] = {"status": "error", "error": str(e)}


@router.get("/result/{job_id}", response_model=BacktestResultResponse)
async def get_result(job_id: str) -> BacktestResultResponse:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return BacktestResultResponse(job_id=job_id, **job)


@router.get("/strategies")
async def list_strategies() -> list[str]:
    return list(AVAILABLE_STRATEGIES.keys())
