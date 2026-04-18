"""Orders / execution API router — Phase 6 full implementation."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.redis import get_redis
from src.execution.broker import paper_broker
from src.core.security import (
    activate_kill_switch, reset_kill_switch, get_kill_switch_status, is_kill_switch_active
)

router = APIRouter(prefix="/api/orders", tags=["orders"])

# Pending signals awaiting approval (COMMANDER mode) — backed by Redis
_PENDING_KEY = "approval:pending"


class OrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    current_price: float
    agent_id: str = "operator"
    strategy: str = "manual"


class KillRequest(BaseModel):
    reason: str = "Manual kill switch activation"
    operator_id: str = "operator"


@router.get("")
async def list_orders() -> list[dict]:
    """List recent orders."""
    orders = await paper_broker.get_orders(limit=50)
    return [o.to_dict() for o in orders]


@router.get("/positions")
async def get_positions() -> list[dict]:
    """Get current open positions."""
    return await paper_broker.get_positions()


@router.get("/portfolio")
async def get_portfolio() -> dict:
    """Portfolio summary."""
    cash = await paper_broker.get_cash()
    total = await paper_broker.get_portfolio_value()
    return {
        "cash": cash,
        "positions_value": total - cash,
        "total": total,
        "daily_pnl": await paper_broker.get_daily_pnl(),
        "trade_count": await paper_broker.get_trade_count(),
    }


@router.post("/submit")
async def submit_order(req: OrderRequest) -> dict:
    """Submit a paper trade order."""
    if await is_kill_switch_active():
        raise HTTPException(503, "Kill switch is active — orders suspended")
    order = await paper_broker.submit_order(
        req.symbol, req.side, req.quantity, req.current_price,
        req.agent_id, req.strategy
    )
    return order.to_dict()


@router.get("/history")
async def order_history() -> list[dict]:
    """Return every order with trade lifecycle: open vs closed, entry/exit, pnl."""
    orders = await paper_broker.get_orders(limit=200)
    orders_list = [o.to_dict() for o in orders]
    open_positions = await paper_broker.get_positions()
    open_by_symbol = {p["symbol"]: p for p in open_positions}

    # Chronological: pair BUYs with matching SELLs per symbol
    by_symbol: dict[str, list[dict]] = {}
    for o in sorted(orders_list, key=lambda x: x["filled_at"] or x["created_at"] or ""):
        by_symbol.setdefault(o["symbol"], []).append(o)

    trades: list[dict] = []
    for symbol, sym_orders in by_symbol.items():
        buy_stack: list[dict] = []
        for o in sym_orders:
            if o["status"] != "FILLED":
                continue
            if o["side"] == "BUY":
                buy_stack.append(o)
            elif o["side"] == "SELL" and buy_stack:
                entry = buy_stack.pop(0)
                exit_price = float(o.get("filled_price") or 0)
                entry_price = float(entry.get("filled_price") or 0)
                qty = float(o.get("quantity") or entry.get("quantity") or 0)
                pnl = (exit_price - entry_price) * qty
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
                trades.append({
                    "symbol": symbol,
                    "side": "LONG",
                    "status": "closed",
                    "entry_order_id": entry["order_id"],
                    "exit_order_id": o["order_id"],
                    "entry_ts": entry["filled_at"],
                    "exit_ts": o["filled_at"],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "quantity": qty,
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl_pct, 6),
                    "exit_reason": o.get("strategy") or "manual",
                    "entry_agent": entry.get("agent_id"),
                    "exit_agent": o.get("agent_id"),
                })
        # Any remaining BUYs are open positions
        for entry in buy_stack:
            current = open_by_symbol.get(symbol)
            trades.append({
                "symbol": symbol,
                "side": "LONG",
                "status": "open",
                "entry_order_id": entry["order_id"],
                "exit_order_id": None,
                "entry_ts": entry["filled_at"],
                "exit_ts": None,
                "entry_price": float(entry.get("filled_price") or 0),
                "exit_price": None,
                "quantity": float(entry.get("quantity") or 0),
                "pnl": None,
                "pnl_pct": None,
                "exit_reason": None,
                "entry_agent": entry.get("agent_id"),
                "exit_agent": None,
                "is_live_position": bool(current),
            })
    trades.sort(key=lambda t: t["entry_ts"] or "", reverse=True)
    return trades


@router.get("/pending")
async def list_pending() -> list[dict]:
    """List pending signals awaiting COMMANDER approval."""
    redis = get_redis()
    raw = await redis.hgetall(_PENDING_KEY) or {}
    out = []
    for v in raw.values():
        try:
            out.append(json.loads(v))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    out.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return out


@router.post("/approve/{signal_id}")
async def approve_signal(signal_id: str) -> dict:
    """Approve a pending signal — executes the order via paper_broker."""
    redis = get_redis()
    raw = await redis.hget(_PENDING_KEY, signal_id)
    if not raw:
        raise HTTPException(404, "Signal not found or already processed")
    if await is_kill_switch_active():
        raise HTTPException(503, "Kill switch is active — orders suspended")
    sig = json.loads(raw)
    order = await paper_broker.submit_order(
        symbol=sig["symbol"], side=sig["side"],
        quantity=sig.get("quantity", 0.0),
        current_price=sig.get("price", 0.0),
        agent_id=sig.get("agent_id", "operator"),
        strategy="approved_by_operator",
    )
    # Record contributors for ELO update on close
    if order.status == "FILLED" and sig["side"] == "BUY":
        contributors = sig.get("contributing_agents") or []
        if contributors:
            await redis.sadd(f"paper:position:{sig['symbol']}:contributors", *contributors)
    await redis.hdel(_PENDING_KEY, signal_id)
    return {"approved": True, "order": order.to_dict()}


@router.post("/reject/{signal_id}")
async def reject_signal(signal_id: str) -> dict:
    """Reject a pending signal."""
    await get_redis().hdel(_PENDING_KEY, signal_id)
    return {"rejected": True, "signal_id": signal_id}


@router.post("/kill")
async def kill_switch(req: KillRequest) -> dict:
    """Activate the emergency kill switch and flatten all positions."""
    result = await activate_kill_switch(req.reason, req.operator_id)
    await paper_broker.flatten_all()
    return result


@router.post("/kill/reset")
async def kill_reset(operator_id: str = "operator") -> dict:
    """Reset the kill switch."""
    return await reset_kill_switch(operator_id)


@router.get("/kill/status")
async def kill_status() -> dict:
    """Get current kill switch status."""
    return await get_kill_switch_status()
