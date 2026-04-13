"""
Risk parity position sizer — sizes positions by inverse volatility.
This is the most important structural improvement to any multi-asset portfolio.

Elite firms (Bridgewater, AQR) use this because:
- A 3% move in gold is equivalent risk to a 3% move in XRP
- Fixed dollar sizing treats them identically — wrong
- Volatility-scaled sizing treats equal RISK identically — right

Gap 1 (Fink recommendation): Liquidity filter ensures no position exceeds
1% of the symbol's 24-hour traded volume. At scale, ignoring liquidity
destroys the ability to exit cleanly — the #1 failure mode of retail algos.
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

# Liquidity filter: max participation as fraction of 24h volume
MAX_VOLUME_PARTICIPATION = 0.01   # 1%

# Hardcoded ADV estimates for commodities (contracts * typical notional, USD)
COMMODITY_ADV_USD: dict[str, float] = {
    "CL=F": 25_000_000_000,
    "GC=F":  8_000_000_000,
    "SI=F":  2_000_000_000,
    "NG=F":  5_000_000_000,
    "ZC=F":  3_000_000_000,
    "ZW=F":  1_500_000_000,
    "ZS=F":  2_000_000_000,
}
COMMODITY_SYMBOLS = set(COMMODITY_ADV_USD.keys())


class VolatilityPositionSizer:
    """
    Risk-parity position sizer using realized volatility + liquidity filter.

    Formula: size = (account_value × target_risk_pct) / (price × annualized_vol)
    Then capped by liquidity: size_usd <= MAX_VOLUME_PARTICIPATION * adv_24h
    """

    async def get_volatility(self, symbol: str, window: int = 20) -> float:
        """Fetch realized volatility from the Redis MARKET_DATA stream."""
        try:
            redis = get_redis()
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
            return max(annualized_vol, 0.01)

        except Exception as exc:
            logger.warning("volatility_fetch_error", symbol=symbol, error=str(exc))
            return DEFAULT_ANNUALIZED_VOL

    async def _get_volume_24h_usd(self, symbol: str, price: float) -> float | None:
        """
        Fetch 24-hour traded volume in USD.

        For crypto: reads from Redis MARKET_DATA stream (volume_24h field).
        Falls back to ccxt fetch_ticker if not in Redis.
        For commodities: uses hardcoded ADV estimates.
        """
        if symbol in COMMODITY_SYMBOLS:
            return COMMODITY_ADV_USD[symbol]

        try:
            redis = get_redis()
            entries = await redis.xrevrange(topology.MARKET_DATA, count=50)
            for _msg_id, fields in entries:
                if fields.get("symbol") == symbol:
                    raw = fields.get("volume_24h") or fields.get("quoteVolume")
                    if raw:
                        return float(raw)

            # Fallback: try ccxt
            try:
                import ccxt.async_support as ccxt  # type: ignore[import]
                exchange = ccxt.binance({"enableRateLimit": True})
                ticker = await exchange.fetch_ticker(symbol.replace("-USD", "/USDT"))
                await exchange.close()
                quote_vol = ticker.get("quoteVolume")
                if quote_vol:
                    return float(quote_vol)
            except Exception:
                pass

        except Exception as exc:
            logger.warning("volume_fetch_error", symbol=symbol, error=str(exc))

        return None

    async def _apply_liquidity_cap(
        self, symbol: str, quantity: float, price: float
    ) -> float:
        """
        Cap position quantity so that size_usd <= 1% of 24h volume.
        Writes participation rate to Redis for monitoring.
        """
        adv_usd = await self._get_volume_24h_usd(symbol, price)
        if not adv_usd or adv_usd <= 0:
            return quantity  # no data, skip cap

        max_usd = adv_usd * MAX_VOLUME_PARTICIPATION
        size_usd = quantity * price
        participation = size_usd / adv_usd

        capped = False
        if size_usd > max_usd:
            quantity = max_usd / price
            capped = True
            logger.warning(
                "liquidity_cap_triggered",
                symbol=symbol,
                original_usd=round(size_usd, 2),
                capped_usd=round(max_usd, 2),
                adv_usd=round(adv_usd, 0),
                participation_pct=f"{participation:.3%}",
            )

        # Write to Redis for dashboard monitoring
        try:
            redis = get_redis()
            await redis.set(
                f"risk:liquidity_cap:{symbol}",
                f'{{"cap_usd":{round(max_usd,2)},"participation":{round(participation,6)},"capped":{str(capped).lower()},"adv_usd":{round(adv_usd,0)}}}',
                ex=600,  # 10-minute TTL
            )
        except Exception:
            pass

        return quantity

    async def calculate_size(
        self,
        symbol: str,
        account_value: float,
        current_prices: dict[str, float],
        volatility_window: int = 20,
    ) -> float:
        """
        Calculate volatility-scaled position size (risk parity) with liquidity cap.

        Formula: size = (account_value × target_risk_pct) / (price × annualized_vol)
        Then:    size_usd capped at MAX_VOLUME_PARTICIPATION * adv_24h
        """
        price = current_prices.get(symbol)
        if not price or price <= 0:
            logger.warning("invalid_price_for_sizing", symbol=symbol, price=price)
            return 0.0

        target_risk_pct: float = settings.max_risk_per_trade
        annualized_vol = await self.get_volatility(symbol, window=volatility_window)

        dollar_risk   = account_value * target_risk_pct
        raw_quantity  = dollar_risk / (price * annualized_vol)
        min_quantity  = (account_value * 0.001) / price
        max_quantity  = (account_value * target_risk_pct * 3) / price
        quantity      = max(min_quantity, min(raw_quantity, max_quantity))

        # Apply liquidity filter (Gap 1)
        quantity = await self._apply_liquidity_cap(symbol, quantity, price)

        logger.info(
            "position_sized",
            symbol=symbol,
            account_value=round(account_value, 2),
            price=round(price, 6),
            annualized_vol=f"{annualized_vol:.1%}",
            target_risk_pct=f"{target_risk_pct:.1%}",
            raw_quantity=round(raw_quantity, 6),
            final_quantity=round(quantity, 6),
        )
        return quantity
