"""
Real-time position monitor — runs every 5 seconds.
Independently checks all open positions against live prices.
Does NOT wait for the agent cycle. Fires exits immediately.

This is what separates a real trading firm from a scheduled job.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, UTC

import structlog

from src.execution.broker import paper_broker
from src.execution.position_source import (
    BrokerUnavailableError,
    position_flattener,
    position_provider,
)
from src.core.security import is_kill_switch_active
from src.core.redis import get_redis
from src.streams.producer import produce, produce_audit
from src.streams import topology

logger = structlog.get_logger()

MONITOR_INTERVAL = 5          # seconds between each sweep
TRAILING_STOP_THRESHOLD = 0.05  # 5% profit triggers trail to breakeven
DEFAULT_STOP_PCT = 0.03       # 3% default stop if position has none
DEFAULT_TARGET_PCT = 0.06     # 6% default target if position has none


from src.data.feeds.price_source import fetch_price as _fetch_live_price  # noqa: E402


async def _check_position(pos: dict, current_price: float) -> str | None:
    """
    Evaluate stop/target/trailing for a position.
    Returns 'stop', 'target', or None.
    Side-effect: updates trailing_stop in-place when threshold is crossed.
    """
    symbol = pos["symbol"]
    avg_price = pos["avg_price"]
    stop_loss = pos.get("stop_loss") or avg_price * (1 - DEFAULT_STOP_PCT)
    take_profit = pos.get("take_profit") or avg_price * (1 + DEFAULT_TARGET_PCT)
    trailing_stop: float | None = pos.get("trailing_stop")

    pnl_pct = (current_price - avg_price) / avg_price

    # Trailing stop: position up >= 5% → trail stop to breakeven (avg_price)
    if pnl_pct >= TRAILING_STOP_THRESHOLD:
        new_trail = avg_price  # lock in breakeven
        if trailing_stop is None or new_trail > trailing_stop:
            await paper_broker.update_position_field(symbol, "trailing_stop", new_trail)
            trailing_stop = new_trail
            logger.info(
                "trailing_stop_activated",
                symbol=symbol,
                trailing_stop=round(new_trail, 6),
                pnl_pct=f"{pnl_pct:.1%}",
            )
    # Effective stop is the tighter of static stop and trailing stop
    effective_stop = max(stop_loss, trailing_stop) if trailing_stop else stop_loss

    if current_price <= effective_stop:
        return "stop"
    if current_price >= take_profit:
        return "target"
    return None


async def _exit_position(pos: dict, current_price: float, reason: str) -> None:
    """Execute a market SELL to close the position, then emit audit + PnL.

    Week 2 / B4: every exit (stop, target, trailing_stop, kill_switch, manual)
    publishes a structured event to ``stream:trade_outcomes`` carrying enough
    detail (entry/exit price/ts, qty, pnl, reason, trade_id) for the outcome
    writer to populate ``trade_outcomes``. This closes the gap where only a
    subset of exit reasons used to surface in P&L reporting.
    """
    symbol = pos["symbol"]
    quantity = pos["quantity"]
    avg_price = pos["avg_price"]
    entry_ts = pos.get("entry_time") or datetime.now(UTC).isoformat()
    trade_id = pos.get("trade_id") or ""
    cycle_id = pos.get("cycle_id") or ""
    redis = get_redis()

    logger.warning(
        "position_exit_triggered",
        symbol=symbol, reason=reason,
        current_price=round(current_price, 6),
        avg_price=round(avg_price, 6),
        pnl_pct=f"{(current_price - avg_price) / avg_price:.2%}",
    )

    order = await paper_broker.submit_order(
        symbol=symbol, side="SELL", quantity=quantity,
        current_price=current_price,
        agent_id="position_monitor",
        strategy=f"auto_exit:{reason}",
        cycle_id=cycle_id or None,
    )

    pnl = (current_price - avg_price) * quantity
    pnl_pct = (current_price - avg_price) / avg_price if avg_price else 0.0
    exit_ts = datetime.now(UTC).isoformat()

    await produce(topology.PNL, {
        "symbol": symbol, "reason": reason,
        "entry_price": str(avg_price), "exit_price": str(current_price),
        "quantity": str(quantity), "pnl": str(round(pnl, 6)),
        "order_id": order.order_id,
    }, redis=redis)

    # Week 2 / B4 — structured outcome event keyed on trade_id.
    if trade_id:
        await produce(topology.TRADE_OUTCOMES, {
            "trade_id": trade_id,
            "cycle_id": cycle_id,
            "symbol": symbol,
            "venue": "sim",
            "direction": "LONG",  # paper_broker is long-only currently
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "entry_price": str(avg_price),
            "exit_price": str(current_price),
            "quantity": str(quantity),
            "pnl_usd": str(round(pnl, 8)),
            "pnl_pct": str(round(pnl_pct, 6)),
            "exit_reason": reason,
            "regime_at_entry": pos.get("regime_at_entry") or "stub-v1:UNKNOWN",
            "regime_at_exit": pos.get("regime_at_entry") or "stub-v1:UNKNOWN",
        }, redis=redis)
    else:
        # No trade_id means this position predates Week 2 instrumentation.
        # We still write to PNL (above) for dashboards but skip the outcome
        # event — the outcome writer would have nothing to attribute against.
        logger.info(
            "exit_without_trade_id",
            symbol=symbol, reason=reason,
            msg="position predates Week 2 instrumentation; outcome event skipped",
        )

    await produce_audit("position_exit", "position_monitor", {
        "symbol": symbol, "reason": reason,
        "pnl": round(pnl, 6), "order_id": order.order_id,
        "trade_id": trade_id,
    }, redis=redis, cycle_id=cycle_id or None)

    # Update ELO for agents that contributed to the directional call
    await _update_agent_elos(symbol, pnl_pct, redis)


_ELO_K = 32  # Per-trade rating delta (standard mid-range chess K-factor)
_ELO_DRAW_PCT = 0.001  # <0.1% is a draw


async def _update_agent_elos(symbol: str, pnl_pct: float, redis) -> None:
    """Adjust ELO on Redis agent:state:* for each contributor to the entry."""
    key = f"paper:position:{symbol}:contributors"
    contributors = list(await redis.smembers(key))
    if not contributors:
        return
    if pnl_pct > _ELO_DRAW_PCT:
        delta = _ELO_K
        outcome = "win"
    elif pnl_pct < -_ELO_DRAW_PCT:
        delta = -_ELO_K
        outcome = "loss"
    else:
        delta = 0
        outcome = "draw"
    for agent_id in contributors:
        state_key = f"agent:state:{agent_id}"
        raw = await redis.hget(state_key, "elo")
        current = float(raw) if raw else 1200.0
        new_elo = round(current + delta, 2)
        await redis.hset(state_key, "elo", str(new_elo))
        await redis.hincrby(state_key, f"trades_{outcome}", 1)
    await redis.delete(key)
    logger.info("elo_updated", symbol=symbol, outcome=outcome,
                delta=delta, contributors=list(contributors))


async def _process_position(pos: dict) -> None:
    """Fetch live price, log the check, and fire exit if a level is hit."""
    symbol = pos["symbol"]
    redis = get_redis()

    price = await _fetch_live_price(symbol)
    if price is None:
        return

    # Audit every check so the Redis stream has a full trail
    await produce(topology.AUDIT, {
        "event": "position_monitor_check",
        "symbol": symbol,
        "current_price": str(round(price, 6)),
        "avg_price": str(round(pos["avg_price"], 6)),
        "stop_loss": str(pos.get("stop_loss") or ""),
        "take_profit": str(pos.get("take_profit") or ""),
        "trailing_stop": str(pos.get("trailing_stop") or ""),
    }, redis=redis)

    action = await _check_position(pos, price)
    if action in ("stop", "target"):
        await _exit_position(pos, price, action)


async def _flatten_all_for_kill_switch() -> None:
    """Close every open position immediately — kill switch is active.

    Week 1 / A2: dispatches via VenueAwareFlattener. For ``sim`` we keep the
    old per-position exit path so trailing stops, audit trail, and ELO updates
    still fire. For ``alpaca_paper`` / ``live`` we hand off to AlpacaBroker's
    flatten_all (close_position per symbol) and let the next risk_monitor
    sweep reconcile the book — Alpaca closes don't have analyst contributors
    to update.
    """
    try:
        positions = await position_provider.get_positions()
    except BrokerUnavailableError as exc:
        logger.critical(
            "kill_switch_flatten_failed_broker_unavailable",
            error=str(exc),
            msg="operator must close positions manually at the venue",
        )
        return

    if not positions:
        return

    logger.critical("kill_switch_flattening_all", count=len(positions))

    # Dispatch via the venue-aware flattener. For sim, also fire the per-
    # position exit path so audit + ELO + signed P&L records still land.
    from src.execution.broker import get_execution_venue

    venue = await get_execution_venue()
    if venue == "sim":
        tasks = []
        for pos in positions:
            price = await _fetch_live_price(pos["symbol"])
            if price:
                tasks.append(_exit_position(pos, price, "kill_switch"))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return

    # Alpaca venues — use SDK close_position via the flattener.
    try:
        await position_flattener.flatten_all()
    except BrokerUnavailableError as exc:
        logger.critical(
            "kill_switch_flatten_alpaca_unavailable",
            error=str(exc),
            msg="operator must close Alpaca positions manually",
        )


async def run() -> None:
    """
    Main monitor loop.
    Runs every 5 seconds. Checks kill switch first, then sweeps all open positions
    concurrently via asyncio.gather — one price fetch + check per position.
    """
    logger.info(
        "position_monitor_started",
        interval_s=MONITOR_INTERVAL,
        trailing_stop_threshold=f"{TRAILING_STOP_THRESHOLD:.0%}",
        default_stop_pct=f"{DEFAULT_STOP_PCT:.0%}",
        default_target_pct=f"{DEFAULT_TARGET_PCT:.0%}",
    )
    while True:
        try:
            if await is_kill_switch_active():
                await _flatten_all_for_kill_switch()
                await asyncio.sleep(MONITOR_INTERVAL)
                continue

            positions = await paper_broker.get_positions()
            if positions:
                await asyncio.gather(
                    *[_process_position(pos) for pos in positions],
                    return_exceptions=True,
                )
            logger.debug("position_monitor_sweep", open_positions=len(positions))

        except Exception as e:
            logger.error("position_monitor_unhandled_error", error=str(e))

        await asyncio.sleep(MONITOR_INTERVAL)
