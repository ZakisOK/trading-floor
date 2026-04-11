"""Built-in trading strategies for the backtester."""
from __future__ import annotations

from typing import Callable

import numpy as np

from src.data.models.market import OHLCVBar


def sma_crossover(fast: int = 10, slow: int = 20) -> Callable:
    """Simple moving average crossover strategy."""

    def strategy(bar: OHLCVBar, history: list[OHLCVBar]) -> dict | None:
        if len(history) < slow:
            return None
        closes = [float(b.close) for b in history[-slow:]] + [float(bar.close)]
        fast_ma = np.mean(closes[-fast:])
        slow_ma = np.mean(closes[-slow:])
        prev_closes = [float(b.close) for b in history[-(slow + 1):-1]]
        if len(prev_closes) < slow:
            return None
        prev_fast = np.mean(prev_closes[-fast:])
        prev_slow = np.mean(prev_closes[-slow:])
        if prev_fast <= prev_slow and fast_ma > slow_ma:
            stop = float(bar.close) * 0.98
            target = float(bar.close) * 1.04
            return {"action": "BUY", "stop_loss": stop, "take_profit": target}
        if prev_fast >= prev_slow and fast_ma < slow_ma:
            return {"action": "SELL"}
        return None

    strategy.__name__ = f"SMA_{fast}_{slow}"
    return strategy


def rsi_mean_reversion(
    period: int = 14, oversold: float = 30, overbought: float = 70
) -> Callable:
    """RSI mean reversion strategy."""

    def _rsi(closes: list[float], p: int) -> float:
        if len(closes) < p + 1:
            return 50.0
        deltas = np.diff(closes[-(p + 1):])
        gains = deltas[deltas > 0].mean() if any(d > 0 for d in deltas) else 0.0
        losses = abs(deltas[deltas < 0].mean()) if any(d < 0 for d in deltas) else 0.0
        if losses == 0:
            return 100.0
        rs = gains / losses
        return float(100 - 100 / (1 + rs))

    def strategy(bar: OHLCVBar, history: list[OHLCVBar]) -> dict | None:
        if len(history) < period + 1:
            return None
        closes = [float(b.close) for b in history[-(period + 1):]] + [float(bar.close)]
        r = _rsi(closes, period)
        if r < oversold:
            stop = float(bar.close) * 0.97
            target = float(bar.close) * 1.06
            return {"action": "BUY", "stop_loss": stop, "take_profit": target}
        if r > overbought:
            return {"action": "SELL"}
        return None

    strategy.__name__ = f"RSI_{period}"
    return strategy


def xrp_momentum(lookback: int = 20, momentum_threshold: float = 0.02) -> Callable:
    """
    XRP momentum strategy based on price action.
    XRP tends to make sharp moves — capture breakouts above recent range.
    """
    def strategy(bar: OHLCVBar, history: list[OHLCVBar]) -> dict | None:
        if len(history) < lookback:
            return None
        closes = [float(b.close) for b in history[-lookback:]]
        current = float(bar.close)
        high = max(closes)
        low = min(closes)
        range_pct = (high - low) / low if low > 0 else 0

        # Breakout above range with momentum
        if current > high * (1 + momentum_threshold / 2) and range_pct > 0.03:
            stop = current * 0.96    # 4% stop (XRP is volatile)
            target = current * 1.12  # 12% target
            return {"action": "BUY", "stop_loss": stop, "take_profit": target}
        # Break below range
        if current < low * (1 - momentum_threshold / 2):
            return {"action": "SELL"}
        return None

    strategy.__name__ = f"XRP_Momentum_{lookback}"
    return strategy


AVAILABLE_STRATEGIES: dict[str, Callable] = {
    "sma_crossover": sma_crossover,
    "rsi_mean_reversion": rsi_mean_reversion,
    "xrp_momentum": xrp_momentum,
}
