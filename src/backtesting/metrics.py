"""Backtest performance metrics — full implementation."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Sequence


@dataclass
class BacktestMetrics:
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    cagr: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    avg_rrr: float  # risk:reward ratio
    total_pnl: float
    total_return_pct: float
    volatility_annualized: float
    calmar_ratio: float


def calculate_sharpe(
    returns: Sequence[float],
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> float:
    r = np.array(returns)
    if len(r) < 2 or r.std() == 0:
        return 0.0
    excess = r - (risk_free_rate / periods_per_year)
    return float(np.sqrt(periods_per_year) * excess.mean() / r.std())

def calculate_sortino(
    returns: Sequence[float],
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> float:
    r = np.array(returns)
    downside = r[r < 0]
    if len(downside) == 0 or downside.std() == 0:
        return float("inf") if r.mean() > 0 else 0.0
    excess = r.mean() - (risk_free_rate / periods_per_year)
    return float(np.sqrt(periods_per_year) * excess / downside.std())


def calculate_max_drawdown(equity_curve: Sequence[float]) -> tuple[float, float]:
    eq = np.array(equity_curve)
    if len(eq) == 0:
        return 0.0, 0.0
    peaks = np.maximum.accumulate(eq)
    drawdowns = eq - peaks
    max_dd_abs = float(drawdowns.min())
    peak_at_max = float(peaks[np.argmin(drawdowns)])
    max_dd_pct = (max_dd_abs / peak_at_max * 100) if peak_at_max != 0 else 0.0
    return max_dd_abs, max_dd_pct


def calculate_cagr(
    initial_equity: float, final_equity: float, years: float
) -> float:
    if years <= 0 or initial_equity <= 0:
        return 0.0
    return float((final_equity / initial_equity) ** (1 / years) - 1) * 100

def calculate_metrics(
    trades: list[dict],
    equity_curve: list[float],
    initial_equity: float = 10000.0,
    years: float = 1.0,
) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    pnls = [t.get("pnl", 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    returns = (
        np.diff(equity_curve) / np.array(equity_curve[:-1])
        if len(equity_curve) > 1
        else np.array([0.0])
    )
    max_dd_abs, max_dd_pct = calculate_max_drawdown(equity_curve)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    final_equity = equity_curve[-1] if equity_curve else initial_equity

    return BacktestMetrics(
        sharpe_ratio=calculate_sharpe(returns),
        sortino_ratio=calculate_sortino(returns),
        max_drawdown=max_dd_abs,
        max_drawdown_pct=max_dd_pct,
        cagr=calculate_cagr(initial_equity, final_equity, years),
        win_rate=len(wins) / len(trades) * 100 if trades else 0,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_win=float(np.mean(wins)) if wins else 0.0,
        avg_loss=float(np.mean(losses)) if losses else 0.0,
        avg_rrr=float(np.mean(wins)) / abs(float(np.mean(losses))) if wins and losses else 0.0,
        total_pnl=sum(pnls),
        total_return_pct=(final_equity - initial_equity) / initial_equity * 100 if equity_curve else 0,
        volatility_annualized=float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0.0,
        calmar_ratio=calculate_cagr(initial_equity, final_equity, years) / abs(max_dd_pct)
        if max_dd_pct != 0
        else 0.0,
    )
