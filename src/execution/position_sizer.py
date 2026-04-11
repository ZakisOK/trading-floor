"""
Risk parity position sizer — sizes positions by inverse volatility.
This is the most important structural improvement to any multi-asset portfolio.

Elite firms (Bridgewater, AQR) use this because:
- A 3% move in gold is equivalent risk to a 3% move in XRP
- Fixed dollar sizing treats them identically — wrong
- Volatility-scaled sizing treats equal RISK identically — right
"""
from __future__ import annotations

import math

import structlog

from src.core.config import settings
from src.core.redis import get_redis
from src.streams import topology

logger = structlog.get_logger()

DEFAULT_ANNUALIZED_VOL = 0.30   # 30% conservative default for unknown symbols
TRADING_DAYS_PER_YEAR = 252


class VolatilityPositionSizer:
    """
    Risk-parity position sizer using realized volatility.

    Sizes each position so it contributes equal risk to the portfolio.
    Formula: size = (account_value × target_risk_pct) / (price × annualized_vol)
    """

    async def get_volatility(self, symbol: str, window: int = 20) -> float:
        """
        Fetch realized volatility from the Redis MARKET_DATA stream.
        Falls back to DEFAULT_ANNUALIZED_VOL for new or illiquid symbols.
        """
        try:
            redis = get_redis()
            # Scan the stream for recent entries belonging to this symbol
            entries = await redis.xrevrange(topology.MARKET_DATA, count=window * 5)
            prices: list[float] = []
            for _msg_id, fields in entries:
                if fields.get("symbol") == symbol:
                    raw = fields.get("price") or fields.get("close") or fields.get("last")
                    if raw:
                        prices.append(float(raw))
                    if len(prices) >= window + 1:
                        break

            if len(prices) < 5:
                logger.warning(
                    "insufficient_price_history",
                    symbol=symbol,
                    got=len(prices),
                    fallback_vol=DEFAULT_ANNUALIZED_VOL,
                )
                return DEFAULT_ANNUALIZED_VOL

            # xrevrange returns newest first — reverse for chronological order
            prices_ordered = list(reversed(prices))
            log_returns = [
                math.log(prices_ordered[i] / prices_ordered[i - 1])
                for i in range(1, len(prices_ordered))
            ]

            n = len(log_returns)
            mean_r = sum(log_returns) / n
            variance = sum((r - mean_r) ** 2 for r in log_returns) / (n - 1)
            daily_vol = math.sqrt(variance)
            annualized_vol = daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)

            logger.debug(
                "volatility_calculated",
                symbol=symbol,
                daily_vol=round(daily_vol, 4),
                annualized_vol=round(annualized_vol, 4),
                n_bars=n,
            )
            return max(annualized_vol, 0.01)   # floor at 1% to avoid division by near-zero

        except Exception as exc:
            logger.warning("volatility_fetch_error", symbol=symbol, error=str(exc))
            return DEFAULT_ANNUALIZED_VOL

    async def calculate_size(
        self,
        symbol: str,
        account_value: float,
        current_prices: dict[str, float],
        volatility_window: int = 20,
    ) -> float:
        """
        Calculate volatility-scaled position size (risk parity).

        Formula: size = (account_value × target_risk_pct) / (price × annualized_vol)

        Floor:   0.1% of portfolio  — always take at least a small position
        Ceiling: target_risk_pct × 3 — never let one position dominate
        """
        price = current_prices.get(symbol)
        if not price or price <= 0:
            logger.warning("invalid_price_for_sizing", symbol=symbol, price=price)
            return 0.0

        target_risk_pct: float = settings.max_risk_per_trade   # default 0.02 (2%)
        annualized_vol = await self.get_volatility(symbol, window=volatility_window)

        # Core risk-parity formula
        dollar_risk = account_value * target_risk_pct
        raw_quantity = dollar_risk / (price * annualized_vol)

        # Floor: 0.1% of portfolio. Ceiling: 3× the risk limit.
        min_quantity = (account_value * 0.001) / price
        max_quantity = (account_value * target_risk_pct * 3) / price
        quantity = max(min_quantity, min(raw_quantity, max_quantity))

        logger.info(
            "position_sized",
            symbol=symbol,
            account_value=round(account_value, 2),
            price=round(price, 6),
            annualized_vol=f"{annualized_vol:.1%}",
            target_risk_pct=f"{target_risk_pct:.1%}",
            raw_quantity=round(raw_quantity, 6),
            final_quantity=round(quantity, 6),
            floor_applied=quantity == min_quantity,
            ceiling_applied=quantity == max_quantity,
        )
        return quantity
