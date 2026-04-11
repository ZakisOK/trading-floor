"""
Continuous risk monitor — enforces daily loss limits and position concentration.
Runs every 30 seconds alongside the position monitor.

Writes daily_pnl, total_exposure, and drawdown_pct to Redis every cycle
so the dashboard always has fresh risk metrics without hitting the DB.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, UTC

import structlog

from src.execution.broker import paper_broker
from src.core.config import settings
from src.core.security import activate_kill_switch, is_kill_switch_active
from src.core.redis import get_redis
from src.streams.producer import produce, produce_audit

logger = structlog.get_logger()

RISK_INTERVAL = 30             # seconds between each risk sweep
CONCENTRATION_MULTIPLIER = 3   # flag if position > 3x max_risk_per_trade

DAILY_PNL_KEY = "risk:daily_pnl"
DAILY_PNL_DATE_KEY = "risk:daily_pnl_date"
RISK_METRICS_KEY = "risk:metrics"
ALERTS_STREAM = "stream:alerts"


async def _fetch_prices_for_positions() -> dict[str, float]:
    """REST-fetch current prices for every open position."""
    positions = paper_broker.get_positions()
    if not positions:
        return {}
    prices: dict[str, float] = {}
    try:
        import ccxt.async_support as ccxt  # type: ignore[import]
        exchange = ccxt.binance({"enableRateLimit": True})
        for pos in positions:
            sym = pos["symbol"]
            try:
                ticker = await exchange.fetch_ticker(sym)
                prices[sym] = float(ticker.get("last") or pos["avg_price"])
            except Exception as e:
                logger.warning("risk_price_fetch_failed", symbol=sym, error=str(e))
                prices[sym] = pos["avg_price"]
        await exchange.close()
    except Exception as e:
        logger.error("risk_exchange_init_failed", error=str(e))
        for pos in positions:
            prices[pos["symbol"]] = pos["avg_price"]
    return prices


async def _reset_daily_pnl_if_new_day(redis) -> None:
    """Reset the daily P&L counter at UTC midnight."""
    today = datetime.now(UTC).date().isoformat()
    stored = await redis.get(DAILY_PNL_DATE_KEY)
    if stored != today:
        await redis.set(DAILY_PNL_KEY, "0")
        await redis.set(DAILY_PNL_DATE_KEY, today)
        paper_broker._daily_pnl = 0.0
        logger.info("daily_pnl_reset", date=today)


async def _check_concentration(
    positions: list[dict], portfolio_value: float, current_prices: dict[str, float]
) -> list[str]:
    """Return symbols whose notional exceeds CONCENTRATION_MULTIPLIER * max_risk_per_trade."""
    limit = settings.max_risk_per_trade * CONCENTRATION_MULTIPLIER
    flagged: list[str] = []
    for pos in positions:
        price = current_prices.get(pos["symbol"], pos["avg_price"])
        notional = pos["quantity"] * price
        concentration = notional / portfolio_value if portfolio_value > 0 else 0.0
        if concentration > limit:
            flagged.append(pos["symbol"])
            logger.warning(
                "position_concentration_breach",
                symbol=pos["symbol"],
                concentration=f"{concentration:.1%}",
                limit=f"{limit:.1%}",
            )
    return flagged


async def run() -> None:
    """
    Main risk loop — runs every 30 seconds.
    Checks daily drawdown limit and fires kill switch automatically if breached.
    Writes fresh metrics to Redis hash so the dashboard reads them without polling the broker.
    """
    logger.info("risk_monitor_started", interval_s=RISK_INTERVAL,
                max_daily_loss=f"{settings.max_daily_loss:.0%}",
                concentration_limit=f"{settings.max_risk_per_trade * CONCENTRATION_MULTIPLIER:.0%}")
    while True:
        try:
            redis = get_redis()
            await _reset_daily_pnl_if_new_day(redis)

            current_prices = await _fetch_prices_for_positions()
            portfolio_value = paper_broker.get_portfolio_value(current_prices)
            daily_pnl = paper_broker._daily_pnl
            positions = paper_broker.get_positions()

            total_exposure = sum(
                pos["quantity"] * current_prices.get(pos["symbol"], pos["avg_price"])
                for pos in positions
            )
            drawdown_pct = daily_pnl / paper_broker._initial_cash if paper_broker._initial_cash > 0 else 0.0

            # Publish metrics to Redis for dashboard consumption
            await redis.hset(RISK_METRICS_KEY, mapping={
                "daily_pnl": str(round(daily_pnl, 4)),
                "portfolio_value": str(round(portfolio_value, 4)),
                "total_exposure": str(round(total_exposure, 4)),
                "drawdown_pct": str(round(drawdown_pct, 6)),
                "open_positions": str(len(positions)),
                "updated_at": datetime.now(UTC).isoformat(),
            })

            logger.info(
                "risk_monitor_cycle",
                portfolio_value=round(portfolio_value, 2),
                daily_pnl=round(daily_pnl, 4),
                drawdown_pct=f"{drawdown_pct:.2%}",
                open_positions=len(positions),
                total_exposure=round(total_exposure, 2),
            )

            # Enforce daily loss limit — auto kill switch
            if daily_pnl < 0 and abs(drawdown_pct) >= settings.max_daily_loss:
                if not await is_kill_switch_active():
                    logger.critical(
                        "daily_loss_limit_breached",
                        drawdown_pct=f"{drawdown_pct:.2%}",
                        limit=f"{settings.max_daily_loss:.2%}",
                    )
                    await activate_kill_switch(
                        reason=f"Auto: daily loss {drawdown_pct:.2%} >= limit {settings.max_daily_loss:.2%}",
                        operator_id="risk_monitor",
                    )

            # Check concentration and emit alert if breached
            if positions and portfolio_value > 0:
                flagged = await _check_concentration(positions, portfolio_value, current_prices)
                if flagged:
                    await produce(ALERTS_STREAM, {
                        "type": "concentration_breach",
                        "symbols": str(flagged),
                        "portfolio_value": str(round(portfolio_value, 2)),
                        "limit_pct": str(settings.max_risk_per_trade * CONCENTRATION_MULTIPLIER),
                    }, redis=redis)
                    await produce_audit("concentration_breach", "risk_monitor", {
                        "flagged_symbols": flagged,
                        "portfolio_value": portfolio_value,
                    }, redis=redis)

        except Exception as e:
            logger.error("risk_monitor_unhandled_error", error=str(e))

        await asyncio.sleep(RISK_INTERVAL)
