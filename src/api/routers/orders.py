"""Orders / execution API router — Phase 6 full implementation."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.execution.broker import paper_broker
from src.core.security import (
    activate_kill_switch, reset_kill_switch, get_kill_switch_status, is_kill_switch_active
)

router = APIRouter(prefix="/api/orders", tags=["orders"])

# Pending signals awaiting approval (COMMANDER mode)
_pending_signals: dict[str, dict] = {}


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


@router.get("/pending")
async def list_pending() -> list[dict]:
    """List pending signals awaiting COMMANDER approval."""
    return list(_pending_signals.values())


@router.post("/approve/{signal_id}")
async def approve_signal(signal_id: str) -> dict:
    """Approve a pending signal — executes the order."""
    sig = _pending_signals.pop(signal_id, None)
    if not sig:
        raise HTTPException(404, "Signal not found or already processed")
    if await is_kill_switch_active():
        raise HTTPException(503, "Kill switch is active — orders suspended")
    order = await paper_broker.submit_order(
        sig["symbol"], sig["side"], sig.get("quantity", 0.001),
        sig.get("price", 50000), sig.get("agent_id", "operator"), sig.get("strategy", "approved")
    )
    return {"approved": True, "order": order.to_dict()}


@router.post("/reject/{signal_id}")
async def reject_signal(signal_id: str) -> dict:
    """Reject a pending signal."""
    _pending_signals.pop(signal_id, None)
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
