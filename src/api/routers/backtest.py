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


# ── Ensemble backtest (agent replay) ────────────────────────────────────────
from dataclasses import asdict
from src.backtesting.ensemble import run_ensemble_backtest, EnsembleBacktestResult

_ensemble_jobs: dict[str, EnsembleBacktestResult] = {}


class EnsembleBacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1d"
    days: int = Field(default=30, ge=1, le=365)
    initial_equity: float = 10000.0


@router.post("/ensemble/run")
async def run_ensemble(
    req: EnsembleBacktestRequest, background_tasks: BackgroundTasks,
) -> dict:
    """Start an ensemble backtest — replays the full agent cycle over OHLCV history."""
    job_id = uuid.uuid4().hex[:12]
    _ensemble_jobs[job_id] = EnsembleBacktestResult(
        job_id=job_id, status="pending", symbol=req.symbol, timeframe=req.timeframe,
        start=None, end=None, initial_equity=req.initial_equity,
        final_equity=req.initial_equity,
    )
    background_tasks.add_task(_run_ensemble_job, job_id, req)
    return {"job_id": job_id, "status": "pending"}


async def _run_ensemble_job(job_id: str, req: EnsembleBacktestRequest) -> None:
    async def progress(partial: EnsembleBacktestResult) -> None:
        _ensemble_jobs[job_id] = partial

    try:
        result = await run_ensemble_backtest(
            symbol=req.symbol, timeframe=req.timeframe,
            days=req.days, initial_equity=req.initial_equity,
            on_progress=progress,
        )
        result.job_id = job_id
        _ensemble_jobs[job_id] = result
    except Exception as exc:  # noqa: BLE001
        r = _ensemble_jobs.get(job_id)
        if r:
            r.status = "failed"
            r.error = str(exc)


def _serialize_ensemble(r: EnsembleBacktestResult) -> dict:
    d = asdict(r)
    if r.start:
        d["start"] = r.start.isoformat()
    if r.end:
        d["end"] = r.end.isoformat()
    for t in d["trades"]:
        t["entry_ts"] = t["entry_ts"].isoformat() if hasattr(t["entry_ts"], "isoformat") else t["entry_ts"]
        t["exit_ts"] = t["exit_ts"].isoformat() if hasattr(t["exit_ts"], "isoformat") else t["exit_ts"]
    for dec in d["decisions"]:
        dec["ts"] = dec["ts"].isoformat() if hasattr(dec["ts"], "isoformat") else dec["ts"]
    return d


@router.get("/ensemble/result/{job_id}")
async def get_ensemble_result(job_id: str) -> dict:
    r = _ensemble_jobs.get(job_id)
    if r is None:
        raise HTTPException(404, "Ensemble job not found")
    return _serialize_ensemble(r)
