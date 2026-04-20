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

Week 1 / A4: ``PositionSizer`` is a thin wrapper around
``VolatilityPositionSizer`` exposing a signal-oriented API
``size(signal, market_data, portfolio) -> SizedOrder`` that callers
(currently Atlas, in Week 2 PortfolioConstructor) invoke BEFORE broker
dispatch. The broker no longer sizes positions — it executes whatever it's
told. This closes the bug where Atlas passed quantity=0 to Alpaca and the
sizer never ran.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

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

            # Fallback: try Coinbase via ccxt
            try:
                import ccxt.async_support as ccxt  # type: ignore[import]
                from src.data.feeds.price_source import to_coinbase_symbol
                cb_sym = to_coinbase_symbol(symbol.replace("-USD", "/USDT"))
                if cb_sym:
                    exchange = ccxt.coinbase({"enableRateLimit": True})
                    try:
                        ticker = await exchange.fetch_ticker(cb_sym)
                    finally:
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


# ---------------------------------------------------------------------------
# Week 1 / A4 — signal-oriented sizer API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SizedOrder:
    """Result of sizing — the broker executes this verbatim.

    ``confidence_adjusted_risk_pct`` documents the per-trade risk percentage
    the sizer used (after confidence weighting). Stored with the order so
    Week 2's PortfolioConstructor can audit sizing decisions over time.
    """

    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    notional: float
    price: float
    confidence_adjusted_risk_pct: float
    annualized_vol: float


class PositionSizer:
    """Signal-oriented sizing facade.

    Atlas (Week 1) and PortfolioConstructor (Week 2) call ``size()`` BEFORE
    broker dispatch. Returning ``quantity == 0`` means "do not trade" —
    typically because portfolio_value is zero or the symbol is illiquid.
    A zero quantity reaching the broker is a bug, not a pattern.
    """

    def __init__(self, vol_sizer: VolatilityPositionSizer | None = None) -> None:
        self._vol_sizer = vol_sizer or VolatilityPositionSizer()

    async def size(
        self,
        signal: dict[str, Any],
        market_data: dict[str, Any],
        portfolio: dict[str, Any],
    ) -> SizedOrder:
        """Size a directional signal against current portfolio + market state.

        Args:
            signal: ``{"symbol", "direction", "confidence", ...}``.
                ``direction`` is "LONG", "SHORT", or "NEUTRAL". NEUTRAL or
                missing direction returns quantity=0.
            market_data: ``{"symbol", "price"|"close", ...}``.
            portfolio: ``{"portfolio_value", ...}`` — typically the venue's
                portfolio_value snapshot.
        """
        symbol = signal.get("symbol") or market_data.get("symbol", "UNKNOWN")
        direction = (signal.get("direction") or "NEUTRAL").upper()
        confidence = float(signal.get("confidence") or 0.0)
        price = float(
            market_data.get("price")
            or market_data.get("close")
            or market_data.get("last")
            or 0.0
        )
        portfolio_value = float(portfolio.get("portfolio_value") or 0.0)

        side = "BUY" if direction == "LONG" else "SELL" if direction == "SHORT" else ""

        if not side or price <= 0 or portfolio_value <= 0:
            logger.info(
                "sized_zero",
                symbol=symbol, direction=direction,
                price=price, portfolio_value=portfolio_value,
            )
            return SizedOrder(
                symbol=symbol, side=side or "BUY", quantity=0.0, notional=0.0,
                price=price, confidence_adjusted_risk_pct=0.0, annualized_vol=0.0,
            )

        # Confidence weighting: the configured max risk is the cap; lower
        # confidence reduces it linearly. A 50%-confidence signal sizes at
        # half the max risk, a 90%-confidence signal at 90% of max.
        target_risk_pct = settings.max_risk_per_trade * max(0.0, min(confidence, 1.0))

        annualized_vol = await self._vol_sizer.get_volatility(symbol)
        # raw quantity using risk-parity formula
        dollar_risk = portfolio_value * target_risk_pct
        raw_quantity = dollar_risk / (price * max(annualized_vol, 0.01))
        # Bracket: minimum trade is 0.1% of portfolio, maximum is 3x target risk
        min_qty = (portfolio_value * 0.001) / price
        max_qty = (portfolio_value * target_risk_pct * 3) / price
        quantity = max(min_qty, min(raw_quantity, max_qty))
        # Liquidity cap (1% of 24h volume)
        quantity = await self._vol_sizer._apply_liquidity_cap(symbol, quantity, price)

        notional = quantity * price
        logger.info(
            "sized",
            symbol=symbol, side=side,
            quantity=round(quantity, 6), notional=round(notional, 2),
            confidence=confidence,
            confidence_adjusted_risk_pct=round(target_risk_pct, 6),
            annualized_vol=round(annualized_vol, 6),
        )
        return SizedOrder(
            symbol=symbol, side=side, quantity=quantity, notional=notional,
            price=price, confidence_adjusted_risk_pct=target_risk_pct,
            annualized_vol=annualized_vol,
        )


# Singleton — cheap, no state.
position_sizer = PositionSizer()


__all__ = [
    "MAX_VOLUME_PARTICIPATION",
    "PositionSizer",
    "SizedOrder",
    "VolatilityPositionSizer",
    "position_sizer",
]
