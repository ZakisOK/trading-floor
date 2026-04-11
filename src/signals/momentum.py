"""
Cross-sectional momentum factor.
The most replicated factor in academic finance — 50+ years of data across all markets.

Standard implementation: 12-1 momentum
- Calculate 12-month return for each symbol in the universe
- Subtract 1-month return (avoids short-term reversal)
- Rank symbols: top third = LONG, bottom third = SHORT
- Rebalance monthly

Adapted for our use: rolling 20-bar momentum (shorter timeframe for crypto/commodities)
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


class MomentumSignal:
    """
    Cross-sectional momentum factor — ranks assets by recent performance.

    The 12-1 momentum factor (12-month return minus 1-month reversal) is the
    most replicated factor in academic finance. This implementation adapts it
    to shorter timeframes for crypto and commodities.
    """

    def calculate_momentum(
        self,
        symbol: str,
        prices: list[float],
        lookback: int = 20,
        skip_recent: int = 1,
    ) -> float:
        """
        Calculate raw momentum score.

        score = (price[-skip_recent] / price[-lookback]) - 1.0

        skip_recent=1 avoids short-term reversal (the -1 in 12-1 momentum).
        A score of +0.15 means the asset gained 15% over the lookback window.
        """
        if len(prices) < lookback + skip_recent:
            logger.warning(
                "insufficient_prices_for_momentum",
                symbol=symbol,
                required=lookback + skip_recent,
                got=len(prices),
            )
            return 0.0

        start_price = prices[-lookback]
        end_price = prices[-skip_recent] if skip_recent > 0 else prices[-1]

        if start_price <= 0:
            return 0.0

        score = (end_price / start_price) - 1.0
        logger.debug("momentum_calculated", symbol=symbol, score=round(score, 4))
        return score

    def get_cross_sectional_rank(
        self,
        symbol: str,
        all_symbols_momentum: dict[str, float],
    ) -> str:
        """
        Rank a symbol within its universe by momentum score.

        Returns:
            "TOP_TERTILE"    — top third  → LONG signal
            "MIDDLE"         — middle third → no signal
            "BOTTOM_TERTILE" — bottom third → SHORT signal
        """
        if symbol not in all_symbols_momentum:
            return "MIDDLE"

        scores = sorted(all_symbols_momentum.values())
        n = len(scores)
        if n < 3:
            # Universe too small for tertile ranking
            return "MIDDLE"

        lower_cut = scores[n // 3]
        upper_cut = scores[-(n // 3) - 1]
        score = all_symbols_momentum[symbol]

        if score >= upper_cut:
            return "TOP_TERTILE"
        if score <= lower_cut:
            return "BOTTOM_TERTILE"
        return "MIDDLE"

    def momentum_signal(
        self,
        symbol: str,
        prices: list[float],
        universe_momentum: dict[str, float],
    ) -> dict:
        """
        Generate a full momentum signal with direction, score, and percentile.

        Args:
            symbol:           The asset being evaluated.
            prices:           Price history for this symbol (oldest first).
            universe_momentum: Pre-computed momentum scores for ALL symbols.

        Returns:
            {
                "direction":  "LONG" | "SHORT" | "NEUTRAL",
                "score":      float,   # raw momentum value (e.g. +0.12 = up 12%)
                "percentile": float,   # 0.0–1.0 rank within the universe
            }
        """
        score = universe_momentum.get(symbol, 0.0)
        rank = self.get_cross_sectional_rank(symbol, universe_momentum)

        if rank == "TOP_TERTILE":
            direction = "LONG"
        elif rank == "BOTTOM_TERTILE":
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        # Percentile: fraction of universe with lower momentum score
        all_scores = sorted(universe_momentum.values())
        n = len(all_scores)
        below = sum(1 for s in all_scores if s < score)
        percentile = below / n if n > 0 else 0.5

        logger.debug(
            "momentum_signal",
            symbol=symbol,
            direction=direction,
            score=round(score, 4),
            percentile=round(percentile, 4),
            universe_size=n,
        )

        return {
            "direction": direction,
            "score": score,
            "percentile": percentile,
        }
