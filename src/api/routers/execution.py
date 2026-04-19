"""Execution API — live positions enriched with current prices."""
from __future__ import annotations

import structlog
from fastapi import APIRouter

import json

from src.execution.broker import paper_broker
from src.core.redis import get_redis
from src.data.feeds.price_source import fetch_price as _fetch_price

logger = structlog.get_logger()

router = APIRouter(prefix="/api/execution", tags=["execution"])


@router.get("/portfolio")
async def get_portfolio() -> dict:
    """Portfolio summary — cash, positions value, total, daily P&L, win rate from closed trades."""
    cash = await paper_broker.get_cash()
    positions = await paper_broker.get_positions()
    prices: dict[str, float] = {}
    for pos in positions:
        price = await _fetch_price(pos["symbol"])
        if price:
            prices[pos["symbol"]] = price
    total = await paper_broker.get_portfolio_value(prices)

    # Win rate = wins / (wins + losses) across closed trades
    orders = await paper_broker.get_orders(limit=500)
    o_list = [o.to_dict() for o in orders]
    by_symbol: dict[str, list[dict]] = {}
    for o in sorted(o_list, key=lambda x: x["filled_at"] or x["created_at"] or ""):
        by_symbol.setdefault(o["symbol"], []).append(o)
    wins = losses = 0
    closed_pnl_sum = 0.0
    for sym_orders in by_symbol.values():
        buys: list[dict] = []
        for o in sym_orders:
            if o["status"] != "FILLED":
                continue
            if o["side"] == "BUY":
                buys.append(o)
            elif o["side"] == "SELL" and buys:
                entry = buys.pop(0)
                pnl = (float(o.get("filled_price") or 0) - float(entry.get("filled_price") or 0)) * float(o.get("quantity") or 0)
                closed_pnl_sum += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
    total_closed = wins + losses
    win_rate = wins / total_closed if total_closed else 0.0

    return {
        "cash": cash,
        "positions_value": total - cash,
        "total": total,
        "daily_pnl": await paper_broker.get_daily_pnl(),
        "trade_count": await paper_broker.get_trade_count(),
        "win_rate": win_rate,
        "closed_trades": total_closed,
        "wins": wins,
        "losses": losses,
        "closed_pnl_total": round(closed_pnl_sum, 4),
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
    positions = await paper_broker.get_positions()
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
            "size": pos["quantity"],
            "entry_price": avg_price,
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
        portfolio_value = await paper_broker.get_portfolio_value()
        return {
            "daily_pnl": await paper_broker.get_daily_pnl(),
            "portfolio_value": portfolio_value,
            "total_exposure": 0.0,
            "drawdown_pct": 0.0,
            "open_positions": len(await paper_broker.get_positions()),
            "updated_at": None,
        }
    return {k: (float(v) if k != "updated_at" and k != "open_positions" else v)
            for k, v in raw.items()}


@router.get("/pnl-daily")
async def pnl_daily(days: int = 30) -> dict:
    """Return per-day portfolio snapshots to track growth day-over-day."""
    from datetime import date, timedelta
    days = max(1, min(days, 90))
    redis = get_redis()
    result = []
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        raw = await redis.hgetall(f"pnl:daily:{d}")
        if not raw:
            continue
        def _f(k: str) -> float:
            try:
                return float(raw.get(k, 0) or 0)
            except ValueError:
                return 0.0
        result.append({
            "date": d,
            "start_portfolio": _f("start_portfolio"),
            "end_portfolio": _f("end_portfolio"),
            "day_pnl": _f("day_pnl"),
            "total_pnl": _f("total_pnl"),
            "realized_pnl": _f("realized_pnl"),
            "unrealized_pnl": _f("unrealized_pnl"),
            "closed_trade_pnl": _f("closed_trade_pnl"),
            "last_ts": raw.get("last_ts"),
        })
    result.reverse()  # chronological
    return {"days": result, "starting_capital": 10000.0}


@router.get("/pnl-history")
async def pnl_history(limit: int = 240) -> dict:
    """Return running P&L snapshots (risk_monitor captures one every 30s).

    Default: 240 snapshots = 2 hours of history. Max = 1440 (12 hours).
    """
    limit = max(1, min(limit, 1440))
    redis = get_redis()
    raw = await redis.lrange("pnl:snapshots", 0, limit - 1)
    points = []
    for item in raw:
        try:
            points.append(json.loads(item))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    # Redis list was LPUSHed, so index 0 is newest. Reverse for chronological order.
    points.reverse()
    return {"points": points, "count": len(points)}
