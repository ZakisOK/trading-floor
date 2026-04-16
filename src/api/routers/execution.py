"""Execution API — live positions enriched with current prices."""
from __future__ import annotations

import structlog
from fastapi import APIRouter

from src.execution.broker import paper_broker
from src.core.redis import get_redis

logger = structlog.get_logger()

router = APIRouter(prefix="/api/execution", tags=["execution"])


async def _fetch_price(symbol: str) -> float | None:
    try:
        import ccxt.async_support as ccxt  # type: ignore[import]
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = await exchange.fetch_ticker(symbol)
        await exchange.close()
        price = ticker.get("last") or (
            (ticker.get("bid", 0) + ticker.get("ask", 0)) / 2
        )
        return float(price) if price else None
    except Exception as e:
        logger.warning("execution_price_fetch_failed", symbol=symbol, error=str(e))
        return None


@router.get("/portfolio")
async def get_portfolio() -> dict:
    """Portfolio summary — cash, positions value, total, daily P&L."""
    total = paper_broker.get_portfolio_value()
    cash = paper_broker._cash
    return {
        "cash": cash,
        "positions_value": total - cash,
        "total": total,
        "daily_pnl": paper_broker._daily_pnl,
        "trade_count": paper_broker._trade_count,
        "win_rate": getattr(paper_broker, "_win_rate", 0.0),
    }


@router.get("/positions")
async def get_live_positions() -> list[dict]:
    """
    Return all open positions enriched with:
    - current_price (live from Binance)
    - unrealized_pnl (notional)
    - unrealized_pnl_pct
    - distance_to_stop_pct (how far price is above the stop)
    - distance_to_target_pct (how far price is below the target)
    """
    positions = paper_broker.get_positions()
    if not positions:
        return []

    enriched = []
    for pos in positions:
        symbol = pos["symbol"]
        avg_price = pos["avg_price"]
        quantity = pos["quantity"]

        current_price = await _fetch_price(symbol) or avg_price

        # Resolve effective stop and target (mirrors position_monitor logic)
        DEFAULT_STOP_PCT = 0.03
        DEFAULT_TARGET_PCT = 0.06
        stop_loss = pos.get("stop_loss") or avg_price * (1 - DEFAULT_STOP_PCT)
        take_profit = pos.get("take_profit") or avg_price * (1 + DEFAULT_TARGET_PCT)
        trailing_stop: float | None = pos.get("trailing_stop")
        effective_stop = max(stop_loss, trailing_stop) if trailing_stop else stop_loss

        unrealized_pnl = (current_price - avg_price) * quantity
        unrealized_pnl_pct = (current_price - avg_price) / avg_price

        # Distance as % of price range between stop and entry
        stop_range = avg_price - effective_stop
        distance_to_stop_pct = (
            (current_price - effective_stop) / stop_range if stop_range > 0 else 1.0
        )

        target_range = take_profit - avg_price
        distance_to_target_pct = (
            (take_profit - current_price) / target_range if target_range > 0 else 0.0
        )

        enriched.append({
            **pos,
            "current_price": round(current_price, 6),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 6),
            "stop_loss": round(effective_stop, 6),
            "take_profit": round(take_profit, 6),
            "trailing_stop": round(trailing_stop, 6) if trailing_stop else None,
            "distance_to_stop_pct": round(max(0.0, min(1.0, distance_to_stop_pct)), 4),
            "distance_to_target_pct": round(max(0.0, min(1.0, distance_to_target_pct)), 4),
        })

    return enriched


@router.get("/risk-metrics")
async def get_risk_metrics() -> dict:
    """Return the latest risk metrics written by risk_monitor every 30s."""
    redis = get_redis()
    raw = await redis.hgetall("risk:metrics")
    if not raw:
        portfolio_value = paper_broker.get_portfolio_value()
        return {
            "daily_pnl": paper_broker._daily_pnl,
            "portfolio_value": portfolio_value,
            "total_exposure": 0.0,
            "drawdown_pct": 0.0,
            "open_positions": len(paper_broker.get_positions()),
            "updated_at": None,
        }
    return {k: (float(v) if k != "updated_at" and k != "open_positions" else v)
            for k, v in raw.items()}
