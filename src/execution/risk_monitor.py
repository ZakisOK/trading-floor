"""
Continuous risk monitor — enforces daily loss limits and position concentration.
Runs every 30 seconds alongside the position monitor.

Writes daily_pnl, total_exposure, and drawdown_pct to Redis every cycle
so the dashboard always has fresh risk metrics without hitting the DB.

Week 1 / A1: positions / portfolio value / day P&L are read from
``VenueAwarePositionProvider`` so the metrics reflect the venue that actually
holds the positions. In ``alpaca_paper`` mode this means we read from the
Alpaca account, not from the (empty) local paper_broker.

Realized / unrealized split + closed-trade P&L still come from the local
paper_broker order history — they are sim-only metrics. Gated by venue.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from src.core.config import settings
from src.core.redis import get_redis
from src.core.security import activate_kill_switch, is_kill_switch_active
from src.execution.broker import _INITIAL_CASH, get_execution_venue, paper_broker
from src.execution.position_source import (
    BrokerUnavailableError,
    position_provider,
)
from src.streams.producer import produce, produce_audit

logger = structlog.get_logger()

RISK_INTERVAL = 30             # seconds between each risk sweep
CONCENTRATION_MULTIPLIER = 3   # flag if position > 3x max_risk_per_trade

DAILY_PNL_KEY = "risk:daily_pnl"
DAILY_PNL_DATE_KEY = "risk:daily_pnl_date"
RISK_METRICS_KEY = "risk:metrics"
ALERTS_STREAM = "stream:alerts"


async def _fetch_prices_for_positions(positions: list[dict]) -> dict[str, float]:
    """REST-fetch current prices for every open position."""
    if not positions:
        return {}
    from src.data.feeds.price_source import fetch_price
    prices: dict[str, float] = {}
    for pos in positions:
        sym = pos["symbol"]
        price = await fetch_price(sym)
        prices[sym] = price if price else pos["avg_price"]
    return prices


async def _reset_daily_pnl_if_new_day(redis) -> None:
    """Reset the daily P&L counter at UTC midnight."""
    today = datetime.now(UTC).date().isoformat()
    stored = await redis.get(DAILY_PNL_DATE_KEY)
    if stored != today:
        await redis.set(DAILY_PNL_KEY, "0")
        await redis.set(DAILY_PNL_DATE_KEY, today)
        # Reset the local sim broker's daily P&L too — harmless when the
        # active venue is alpaca_paper (Alpaca's day P&L is computed from
        # last_equity, not from this counter).
        await paper_broker.reset_daily_pnl()
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


async def _compute_sim_pnl_split(
    portfolio_value: float, total_pnl: float, current_prices: dict[str, float]
) -> tuple[float, float, float]:
    """Sim-only realized / unrealized / closed-trade-pnl breakdown.

    Reads paper_broker order + position history. For non-sim venues this
    metric is meaningless (Alpaca tracks P&L differently); callers should
    return zeros to keep the dashboard schema stable.
    """
    positions = await paper_broker.get_positions()
    unrealized_pnl = 0.0
    for pos in positions:
        price = current_prices.get(pos["symbol"], pos["avg_price"])
        unrealized_pnl += (price - pos["avg_price"]) * pos["quantity"]

    realized_pnl = total_pnl - unrealized_pnl

    orders_list = [o.to_dict() for o in await paper_broker.get_orders(limit=500)]
    by_sym: dict[str, list[dict]] = {}
    for o in sorted(
        orders_list, key=lambda x: x["filled_at"] or x["created_at"] or ""
    ):
        by_sym.setdefault(o["symbol"], []).append(o)

    closed_trade_pnl = 0.0
    for sym_orders in by_sym.values():
        buys: list[dict] = []
        for o in sym_orders:
            if o["status"] != "FILLED":
                continue
            if o["side"] == "BUY":
                buys.append(o)
            elif o["side"] == "SELL" and buys:
                entry = buys.pop(0)
                closed_trade_pnl += (
                    float(o.get("filled_price") or 0)
                    - float(entry.get("filled_price") or 0)
                ) * float(o.get("quantity") or 0)

    return unrealized_pnl, realized_pnl, closed_trade_pnl


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
            venue = await get_execution_venue()

            try:
                positions = await position_provider.get_positions()
            except BrokerUnavailableError as exc:
                # PRINCIPLE #3: if the venue's broker can't be read, that's a
                # safety event — trip the kill switch and skip this sweep.
                if not await is_kill_switch_active():
                    await activate_kill_switch(
                        reason=f"Auto: position_provider unavailable ({exc})",
                        operator_id="risk_monitor",
                    )
                await asyncio.sleep(RISK_INTERVAL)
                continue

            current_prices = await _fetch_prices_for_positions(positions)
            portfolio_value_dec = await position_provider.get_portfolio_value(
                current_prices
            )
            portfolio_value = float(portfolio_value_dec)
            daily_pnl_dec = await position_provider.get_daily_pnl()
            daily_pnl = float(daily_pnl_dec)

            total_exposure = sum(
                pos["quantity"] * current_prices.get(pos["symbol"], pos["avg_price"])
                for pos in positions
            )
            drawdown_pct = daily_pnl / _INITIAL_CASH if _INITIAL_CASH > 0 else 0.0

            # Total P&L is portfolio_value - starting_cash, regardless of venue.
            total_pnl = portfolio_value - _INITIAL_CASH

            # Realized / unrealized breakdown is currently sim-only. For Alpaca
            # venues, set to zero — Week 2's PortfolioConstructor adds an
            # Alpaca-aware breakdown.
            if venue == "sim":
                unrealized_pnl, realized_pnl, closed_trade_pnl = (
                    await _compute_sim_pnl_split(
                        portfolio_value, total_pnl, current_prices
                    )
                )
            else:
                unrealized_pnl = 0.0
                realized_pnl = 0.0
                closed_trade_pnl = 0.0

            snapshot_ts = datetime.now(UTC).isoformat()
            today_key = datetime.now(UTC).strftime("%Y-%m-%d")

            # Seed today's start-of-day portfolio value once
            daily_hash = f"pnl:daily:{today_key}"
            if not await redis.hexists(daily_hash, "start_portfolio"):
                await redis.hset(daily_hash, mapping={
                    "date": today_key,
                    "start_portfolio": str(round(portfolio_value, 4)),
                    "start_ts": snapshot_ts,
                })
            start_portfolio_raw = await redis.hget(daily_hash, "start_portfolio")
            start_portfolio = float(start_portfolio_raw) if start_portfolio_raw else portfolio_value
            day_pnl = portfolio_value - start_portfolio

            # Update current daily stats
            await redis.hset(daily_hash, mapping={
                "end_portfolio": str(round(portfolio_value, 4)),
                "day_pnl": str(round(day_pnl, 4)),
                "total_pnl": str(round(total_pnl, 4)),
                "realized_pnl": str(round(realized_pnl, 4)),
                "unrealized_pnl": str(round(unrealized_pnl, 4)),
                "closed_trade_pnl": str(round(closed_trade_pnl, 4)),
                "last_ts": snapshot_ts,
            })

            # Publish metrics for dashboard
            await redis.hset(RISK_METRICS_KEY, mapping={
                "venue": venue,
                "daily_pnl": str(round(daily_pnl, 4)),
                "portfolio_value": str(round(portfolio_value, 4)),
                "total_exposure": str(round(total_exposure, 4)),
                "drawdown_pct": str(round(drawdown_pct, 6)),
                "open_positions": str(len(positions)),
                "realized_pnl": str(round(realized_pnl, 4)),
                "unrealized_pnl": str(round(unrealized_pnl, 4)),
                "total_pnl": str(round(total_pnl, 4)),
                "closed_trade_pnl": str(round(closed_trade_pnl, 4)),
                "day_pnl": str(round(day_pnl, 4)),
                "starting_capital": str(_INITIAL_CASH),
                "updated_at": snapshot_ts,
            })

            # Append to running P&L history (keep last 1440 = 12h at 30s)
            snapshot = json.dumps({
                "ts": snapshot_ts,
                "venue": venue,
                "portfolio_value": round(portfolio_value, 4),
                "realized_pnl": round(realized_pnl, 4),
                "unrealized_pnl": round(unrealized_pnl, 4),
                "total_pnl": round(total_pnl, 4),
                "day_pnl": round(day_pnl, 4),
                "open_positions": len(positions),
            })
            await redis.lpush("pnl:snapshots", snapshot)
            await redis.ltrim("pnl:snapshots", 0, 1439)

            logger.info(
                "risk_monitor_cycle",
                venue=venue,
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
                        venue=venue,
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
                        "venue": venue,
                        "symbols": str(flagged),
                        "portfolio_value": str(round(portfolio_value, 2)),
                        "limit_pct": str(settings.max_risk_per_trade * CONCENTRATION_MULTIPLIER),
                    }, redis=redis)
                    await produce_audit("concentration_breach", "risk_monitor", {
                        "flagged_symbols": flagged,
                        "venue": venue,
                        "portfolio_value": portfolio_value,
                    }, redis=redis)

        except Exception as e:
            logger.error("risk_monitor_unhandled_error", error=str(e))

        await asyncio.sleep(RISK_INTERVAL)
