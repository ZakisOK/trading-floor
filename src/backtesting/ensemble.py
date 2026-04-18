"""Ensemble backtest — replay historical OHLCV through run_trading_cycle.

Walks through historical bars for a single symbol, calls the real LangGraph
cycle on each bar, and simulates position management with the same stop/target
logic the live system uses. Output: equity curve, trade list, metrics.

Cost note: each bar calls multiple LLM agents. Prefer daily timeframe for quick
sweeps; hourly is overkill for most research questions and much more expensive.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.data.models.market import OHLCV

logger = structlog.get_logger()


DEFAULT_STOP_PCT = 0.03
DEFAULT_TARGET_PCT = 0.06
COMMISSION_PCT = 0.001
SLIPPAGE_PCT = 0.0005


@dataclass
class EnsembleTrade:
    symbol: str
    direction: str
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    entry_confidence: float
    entry_agents: list[str]


@dataclass
class EnsembleDecision:
    ts: datetime
    decision: str
    confidence: float
    price: float
    signals: int


@dataclass
class EnsembleBacktestResult:
    job_id: str
    status: str  # pending | running | complete | failed
    symbol: str
    timeframe: str
    start: datetime | None
    end: datetime | None
    initial_equity: float
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    bars_processed: int = 0
    bars_total: int = 0
    trades: list[EnsembleTrade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[EnsembleDecision] = field(default_factory=list)
    error: str | None = None


async def _load_bars(
    symbol: str, timeframe: str, start: datetime, end: datetime,
) -> list[OHLCV]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(OHLCV)
            .where(
                OHLCV.symbol == symbol,
                OHLCV.exchange == "coinbase",
                OHLCV.timeframe == timeframe,
                OHLCV.ts >= start,
                OHLCV.ts <= end,
            )
            .order_by(OHLCV.ts.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _max_drawdown(curve: list[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
    return max_dd


async def run_ensemble_backtest(
    symbol: str,
    timeframe: str,
    days: int,
    initial_equity: float = 10_000.0,
    on_progress: Any = None,
) -> EnsembleBacktestResult:
    """Replay historical bars through run_trading_cycle and simulate trades."""
    from src.agents.sage import run_trading_cycle  # lazy to avoid module-load cost

    job_id = uuid.uuid4().hex[:12]
    result = EnsembleBacktestResult(
        job_id=job_id,
        status="running",
        symbol=symbol,
        timeframe=timeframe,
        start=None,
        end=None,
        initial_equity=initial_equity,
        final_equity=initial_equity,
    )

    now = datetime.now(UTC)
    end = now
    from datetime import timedelta
    start = now - timedelta(days=days)
    result.start = start
    result.end = end

    bars = await _load_bars(symbol, timeframe, start, end)
    result.bars_total = len(bars)

    if not bars:
        result.status = "failed"
        result.error = f"No OHLCV data for {symbol} {timeframe} in range"
        return result

    cash = initial_equity
    position: dict[str, Any] | None = None
    equity_curve: list[float] = []

    for idx, bar in enumerate(bars):
        price = float(bar.close)
        ts = bar.ts
        result.bars_processed = idx + 1

        # 1. If we hold a position, check stop/target against this bar's high/low
        if position is not None:
            hi = float(bar.high)
            lo = float(bar.low)
            stop = position["stop_loss"]
            target = position["take_profit"]
            exit_price: float | None = None
            exit_reason = ""

            if position["direction"] == "LONG":
                if lo <= stop:
                    exit_price, exit_reason = stop, "stop"
                elif hi >= target:
                    exit_price, exit_reason = target, "target"
            else:  # SHORT
                if hi >= stop:
                    exit_price, exit_reason = stop, "stop"
                elif lo <= target:
                    exit_price, exit_reason = target, "target"

            if exit_price is not None:
                # Close position
                qty = position["quantity"]
                fill = exit_price * (1 - SLIPPAGE_PCT if position["direction"] == "LONG" else 1 + SLIPPAGE_PCT)
                if position["direction"] == "LONG":
                    proceeds = fill * qty * (1 - COMMISSION_PCT)
                    pnl = proceeds - position["entry_price"] * qty
                else:
                    proceeds = (2 * position["entry_price"] - fill) * qty * (1 - COMMISSION_PCT)
                    pnl = proceeds - position["entry_price"] * qty
                cash += proceeds
                pnl_pct = pnl / (position["entry_price"] * qty) if qty else 0.0
                result.trades.append(EnsembleTrade(
                    symbol=symbol,
                    direction=position["direction"],
                    entry_ts=position["entry_ts"],
                    entry_price=position["entry_price"],
                    exit_ts=ts,
                    exit_price=fill,
                    quantity=qty,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason=exit_reason,
                    entry_confidence=position["entry_confidence"],
                    entry_agents=position["entry_agents"],
                ))
                position = None

        # 2. Ask the agent ensemble for a decision
        try:
            state = await run_trading_cycle(
                symbol, {"close": price, "volume": float(bar.volume)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensemble_cycle_failed", symbol=symbol, ts=ts.isoformat(),
                           error=str(exc))
            state = None

        decision = "NEUTRAL"
        confidence = 0.0
        signal_agents: list[str] = []
        if state:
            decision = state.get("final_decision") or "NEUTRAL"
            confidence = float(state.get("confidence") or 0.0)
            signals = state.get("signals", []) or []
            signal_agents = [
                s.get("agent", "?").lower()
                for s in signals
                if s.get("direction") == decision and float(s.get("confidence") or 0) >= 0.55
            ]

        result.decisions.append(EnsembleDecision(
            ts=ts, decision=decision, confidence=confidence,
            price=price, signals=len(signal_agents),
        ))

        # 3. Enter a position if risk-approved + directional
        risk_approved = bool(state and state.get("risk_approved"))
        if position is None and risk_approved and decision in ("LONG", "SHORT"):
            fill_price = price * (1 + SLIPPAGE_PCT if decision == "LONG" else 1 - SLIPPAGE_PCT)
            sizing_pct = 0.10  # 10% of cash per trade for backtest simplicity
            spend = cash * sizing_pct
            qty = spend / fill_price
            cash -= spend * (1 + COMMISSION_PCT)
            position = {
                "direction": decision,
                "entry_price": fill_price,
                "entry_ts": ts,
                "quantity": qty,
                "stop_loss": fill_price * (1 - DEFAULT_STOP_PCT) if decision == "LONG" else fill_price * (1 + DEFAULT_STOP_PCT),
                "take_profit": fill_price * (1 + DEFAULT_TARGET_PCT) if decision == "LONG" else fill_price * (1 - DEFAULT_TARGET_PCT),
                "entry_confidence": confidence,
                "entry_agents": signal_agents,
            }

        # 4. Mark-to-market equity
        position_value = 0.0
        if position is not None:
            position_value = position["quantity"] * price
        total_equity = cash + position_value
        equity_curve.append(total_equity)
        result.equity_curve.append({"ts": ts.isoformat(), "equity": round(total_equity, 2)})

        if on_progress:
            try:
                await on_progress(result)
            except Exception:
                pass

    # Close any open position at final close
    if position is not None:
        final_price = float(bars[-1].close)
        qty = position["quantity"]
        proceeds = final_price * qty * (1 - COMMISSION_PCT)
        pnl = proceeds - position["entry_price"] * qty
        pnl_pct = pnl / (position["entry_price"] * qty) if qty else 0.0
        cash += proceeds
        result.trades.append(EnsembleTrade(
            symbol=symbol,
            direction=position["direction"],
            entry_ts=position["entry_ts"],
            entry_price=position["entry_price"],
            exit_ts=bars[-1].ts,
            exit_price=final_price,
            quantity=qty,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason="end_of_data",
            entry_confidence=position["entry_confidence"],
            entry_agents=position["entry_agents"],
        ))
        equity_curve[-1] = cash
        result.equity_curve[-1]["equity"] = round(cash, 2)

    result.final_equity = cash
    result.total_return_pct = (cash - initial_equity) / initial_equity
    wins = [t for t in result.trades if t.pnl > 0]
    result.win_rate = len(wins) / len(result.trades) if result.trades else 0.0
    result.max_drawdown_pct = _max_drawdown(equity_curve)
    result.status = "complete"
    return result
