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


# ---------------------------------------------------------------------------
# Commodity strategies
# ---------------------------------------------------------------------------

def gold_safe_haven(vix_threshold: float = 20.0, dollar_correlation: float = -0.7) -> Callable:
    """
    Gold safe-haven strategy.

    Gold tends to rally when:
      1. VIX spikes (risk-off flight to safety)
      2. USD weakens (inverse DXY relationship)
      3. Real yields fall (gold's primary macro driver)

    This strategy uses a proxy: rapid price acceleration in gold combined
    with the bar's volume surge (institutional safe-haven buying).

    dollar_correlation: expected negative correlation with USD proxy.
    vix_threshold: VIX level above which gold gets a safe-haven bid.
    """
    def strategy(bar: OHLCVBar, history: list[OHLCVBar]) -> dict | None:
        if len(history) < 20:
            return None

        closes = [float(b.close) for b in history[-20:]] + [float(bar.close)]
        volumes = [float(b.volume) for b in history[-20:]] + [float(bar.volume)]
        current = closes[-1]

        # 20-day average as baseline
        avg_price = np.mean(closes[:-1])
        avg_volume = np.mean(volumes[:-1])

        # Price deviation from average
        price_deviation = (current - avg_price) / avg_price

        # Volume surge (institutional buying signal)
        vol_ratio = float(bar.volume) / avg_volume if avg_volume > 0 else 1.0

        # Safe-haven signal: price pulling away from average + volume surge
        # Gold in safe-haven mode: fast move up on high volume
        if price_deviation > 0.012 and vol_ratio > 1.5:
            stop = current * 0.985   # 1.5% stop (gold is less volatile than crypto)
            target = current * 1.04  # 4% target (gold moves are slower)
            return {"action": "BUY", "stop_loss": stop, "take_profit": target}

        # Reversal: gold extended too far above average, fading
        if price_deviation > 0.04 and vol_ratio < 0.8:
            # Low volume at highs = distribution = fade
            return {"action": "SELL"}

        return None

    strategy.__name__ = f"Gold_SafeHaven_VIX{vix_threshold}"
    return strategy


def commodity_momentum(lookback: int = 10, threshold: float = 0.015) -> Callable:
    """
    Generic commodity momentum strategy.

    Commodities trend strongly once moving — COT data confirms when
    commercial hedgers are positioned for the move. This strategy
    captures the technical momentum component.

    Tighter than XRP momentum: commodities trend more steadily but
    can also mean-revert sharply on fundamental news (USDA, EIA).

    lookback: bars to measure momentum over
    threshold: minimum price change to qualify as momentum (1.5% default)
    """
    def strategy(bar: OHLCVBar, history: list[OHLCVBar]) -> dict | None:
        if len(history) < lookback + 5:
            return None

        closes = [float(b.close) for b in history[-(lookback + 1):]] + [float(bar.close)]
        current = closes[-1]

        # Momentum: current price vs lookback periods ago
        past_price = closes[0]
        momentum_pct = (current - past_price) / past_price if past_price > 0 else 0.0

        # Short-term acceleration (last 3 bars vs prior bars)
        recent_avg = np.mean(closes[-4:-1])
        prior_avg = np.mean(closes[:-4])
        acceleration = (recent_avg - prior_avg) / prior_avg if prior_avg > 0 else 0.0

        # Volume confirmation
        volumes = [float(b.volume) for b in history[-lookback:]]
        avg_vol = np.mean(volumes) if volumes else 1.0
        vol_ratio = float(bar.volume) / avg_vol if avg_vol > 0 else 1.0

        # Long: strong momentum + acceleration + volume
        if momentum_pct > threshold and acceleration > 0.005 and vol_ratio > 1.2:
            stop = current * (1 - threshold * 1.5)
            target = current * (1 + threshold * 3)
            return {"action": "BUY", "stop_loss": stop, "take_profit": target}

        # Short: strong negative momentum + acceleration + volume
        if momentum_pct < -threshold and acceleration < -0.005 and vol_ratio > 1.2:
            return {"action": "SELL"}

        return None

    strategy.__name__ = f"Commodity_Momentum_{lookback}bar_{threshold:.3f}"
    return strategy


def seasonal_commodity(commodity: str, month_weights: dict[int, float] | None = None) -> Callable:
    """
    Seasonal commodity strategy.

    Position size and direction are biased by the historical seasonal tendency
    for this commodity and the current calendar month.

    month_weights: dict mapping month (1-12) to expected return %.
    If not provided, uses the built-in SEASONAL_BIAS table.

    A positive month_weight increases position size for LONG signals.
    A negative month_weight increases position size for SHORT signals.

    This strategy does not generate standalone signals — it returns a
    size multiplier for use by the portfolio sizer. For standalone backtesting,
    it combines seasonal bias with a simple momentum trigger.
    """
    # Lazy import to avoid circular dependency at module load
    def _get_bias_table() -> dict[int, float]:
        try:
            from src.data.feeds.commodities_feed import SEASONAL_BIAS
            return month_weights or SEASONAL_BIAS.get(commodity, {})
        except ImportError:
            return month_weights or {}

    def strategy(bar: OHLCVBar, history: list[OHLCVBar]) -> dict | None:
        import datetime
        if len(history) < 5:
            return None

        bias_table = _get_bias_table()
        current_month = datetime.date.today().month
        seasonal_return = bias_table.get(current_month, 0.0)

        closes = [float(b.close) for b in history[-5:]] + [float(bar.close)]
        current = closes[-1]
        prior = closes[0]
        short_momentum = (current - prior) / prior if prior > 0 else 0.0

        # Only trade when seasonal bias and short momentum agree
        if seasonal_return > 1.0 and short_momentum > 0.005:
            # Strong seasonal + momentum confirmation = high conviction long
            size_mult = min(1.5, 1.0 + seasonal_return / 10)
            stop = current * 0.982
            target = current * (1 + abs(seasonal_return) / 100 * 3)
            return {
                "action": "BUY",
                "stop_loss": stop,
                "take_profit": target,
                "size_multiplier": size_mult,
                "seasonal_return_pct": seasonal_return,
                "month": current_month,
            }

        if seasonal_return < -1.0 and short_momentum < -0.005:
            # Strong seasonal headwind + momentum = high conviction short
            return {
                "action": "SELL",
                "seasonal_return_pct": seasonal_return,
                "month": current_month,
            }

        return None

    strategy.__name__ = f"Seasonal_{commodity}_M{{}}"
    return strategy


AVAILABLE_STRATEGIES: dict[str, Callable] = {
    "sma_crossover": sma_crossover,
    "rsi_mean_reversion": rsi_mean_reversion,
    "xrp_momentum": xrp_momentum,
    "gold_safe_haven": gold_safe_haven,
    "commodity_momentum": commodity_momentum,
    "seasonal_commodity": seasonal_commodity,
}
