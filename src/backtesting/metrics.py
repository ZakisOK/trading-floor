"""Backtest performance metrics stub."""
import numpy as np


def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio from a 1-D array of daily returns."""
    excess = returns - risk_free_rate / 252
    if excess.std() == 0:
        return 0.0
    return float((excess.mean() / excess.std()) * np.sqrt(252))


def max_drawdown(equity_curve: np.ndarray) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction."""
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - peak) / peak
    return float(abs(drawdown.min()))


def win_rate(pnl_series: np.ndarray) -> float:
    """Fraction of trades with positive P&L."""
    if len(pnl_series) == 0:
        return 0.0
    return float((pnl_series > 0).sum() / len(pnl_series))
