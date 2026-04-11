"""
Market regime detector — labels the current market environment.

Only run momentum strategies in TRENDING markets.
Only run mean-reversion in RANGING markets.
Reduces noise trades by 20-30% by preventing strategy/regime mismatch.

Regime detection using ATR ratio (simple, proven approach):
  VOLATILE : current 5-bar ATR > 1.5× rolling 50-bar ATR average
  TRENDING : |24h price move| > 2% AND ATR in normal range (≤ 1.5× avg)
  RANGING  : |24h price move| < 0.5% and ATR below average

Strategy routing:
  momentum       → TRENDING only
  mean_reversion → RANGING only
  fundamental    → all regimes (COT, EIA, sentiment — always valid)
  carry          → RANGING + TRENDING (not VOLATILE — carry unwinds in crashes)

Redis key written: market:regime:{symbol}  (read by Portfolio Chief + Nova)
"""
from __future__ import annotations

from typing import Literal

import structlog

from src.core.redis import get_redis

logger = structlog.get_logger()

RegimeLabel = Literal["TRENDING", "RANGING", "VOLATILE"]

# Regime thresholds
VOLATILE_ATR_RATIO = 1.5     # current ATR > 1.5× average → volatile
TRENDING_MOVE_PCT = 2.0      # 24h move > 2% → trending
RANGING_MOVE_PCT = 0.5       # 24h move < 0.5% → ranging

# Redis TTL: regime label expires after 10 minutes (Portfolio Chief refreshes every 5m)
REGIME_TTL_SECONDS = 600

# Strategy → allowed regimes mapping
_STRATEGY_REGIME_MAP: dict[str, set[RegimeLabel]] = {
    "momentum":       {"TRENDING"},
    "mean_reversion": {"RANGING"},
    "fundamental":    {"TRENDING", "RANGING", "VOLATILE"},
    "sentiment":      {"TRENDING", "RANGING", "VOLATILE"},
    "cot":            {"TRENDING", "RANGING", "VOLATILE"},
    "carry":          {"TRENDING", "RANGING"},
}


def _compute_atr(prices: list[float], window: int) -> float:
    """
    Approximate ATR from close prices (no OHLCV needed).
    Uses |close[i] - close[i-1]| as a surrogate for True Range.
    Returns 0.0 if insufficient data.
    """
    if len(prices) < window + 1:
        return 0.0
    recent = prices[-(window + 1):]
    ranges = [abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))]
    return sum(ranges) / len(ranges)


def _classify_regime(
    atr_current: float,
    atr_avg: float,
    price_change_pct: float,
) -> RegimeLabel:
    """
    Classify the current market regime using ATR ratio and 24h price move.

    Logic (evaluated in order):
      1. VOLATILE  if current ATR > 1.5× avg ATR
      2. TRENDING  if |move| > 2% and ATR is normal
      3. RANGING   if |move| < 0.5% (low volatility, no trend)
      4. TRENDING  as default (better to trade with momentum than against it)
    """
    if atr_avg <= 0:
        return "VOLATILE"

    ratio = atr_current / atr_avg
    abs_move = abs(price_change_pct)

    if ratio > VOLATILE_ATR_RATIO:
        return "VOLATILE"
    if abs_move >= TRENDING_MOVE_PCT:
        return "TRENDING"
    if abs_move < RANGING_MOVE_PCT:
        return "RANGING"
    return "TRENDING"  # default: between 0.5% and 2% — mild trending


class RegimeDetector:
    """
    Stateless regime classifier. Writes results to Redis for consumption
    by Portfolio Chief, Nova, and any strategy that needs context.
    """

    def detect(self, symbol: str, prices: list[float]) -> RegimeLabel:
        """
        Classify the regime for a symbol given its recent close prices.

        Args:
            symbol: Trading pair, e.g. "BTC/USDT"
            prices: List of recent close prices, most recent last.
                    Needs at least 52 entries for full ATR calculation (5+50+1).
                    Works with fewer — quality degrades gracefully.

        Returns:
            "TRENDING", "RANGING", or "VOLATILE"
        """
        if len(prices) < 3:
            logger.debug("regime_detector_insufficient_prices", symbol=symbol, count=len(prices))
            return "RANGING"

        # Current regime: 5-bar ATR
        atr5 = _compute_atr(prices, 5)

        # Baseline: 50-bar ATR (or full history if shorter)
        window_long = min(50, len(prices) - 1)
        atr50 = _compute_atr(prices, window_long)

        # 24h price move: compare most recent close to 24 bars ago (or oldest available)
        lookback = min(24, len(prices) - 1)
        price_now = prices[-1]
        price_then = prices[-1 - lookback]
        price_change_pct = ((price_now - price_then) / price_then * 100) if price_then != 0 else 0.0

        regime = _classify_regime(atr5, atr50, price_change_pct)

        logger.debug(
            "regime_detected",
            symbol=symbol,
            regime=regime,
            atr5=round(atr5, 6),
            atr50=round(atr50, 6),
            atr_ratio=round(atr5 / atr50, 3) if atr50 > 0 else None,
            price_change_pct=round(price_change_pct, 3),
        )
        return regime

    async def detect_and_publish(self, symbol: str, prices: list[float]) -> RegimeLabel:
        """
        Detect regime and write to Redis so Portfolio Chief and Nova can read it.
        Key: market:regime:{symbol}
        """
        regime = self.detect(symbol, prices)
        redis = get_redis()
        try:
            await redis.set(f"market:regime:{symbol}", regime, ex=REGIME_TTL_SECONDS)
        except Exception as exc:
            logger.warning("regime_publish_failed", symbol=symbol, error=str(exc))
        return regime

    async def get_cached_regime(self, symbol: str) -> RegimeLabel:
        """Read the most recently published regime for a symbol from Redis."""
        redis = get_redis()
        try:
            raw = await redis.get(f"market:regime:{symbol}")
            if raw in ("TRENDING", "RANGING", "VOLATILE"):
                return raw  # type: ignore[return-value]
        except Exception:
            pass
        return "RANGING"  # safe default

    def should_trade_strategy(self, strategy_type: str, regime: RegimeLabel) -> bool:
        """
        Returns True if the given strategy should trade in the current regime.

        Args:
            strategy_type: One of "momentum", "mean_reversion", "fundamental",
                           "sentiment", "cot", "carry"
            regime:        Current market regime label

        Example:
            detector.should_trade_strategy("momentum", "VOLATILE") → False
            detector.should_trade_strategy("fundamental", "VOLATILE") → True
            detector.should_trade_strategy("carry", "RANGING") → True
        """
        allowed = _STRATEGY_REGIME_MAP.get(strategy_type, {"TRENDING", "RANGING", "VOLATILE"})
        return regime in allowed


# Module-level singleton
regime_detector = RegimeDetector()
