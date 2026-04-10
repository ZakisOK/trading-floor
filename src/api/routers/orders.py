"""Orders / execution API router — implemented fully in Phase 6."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("")
async def list_orders() -> list[dict]:
    """List recent orders."""
    return []


@router.get("/positions")
async def get_positions() -> list[dict]:
    """Get current open positions."""
    return []


@router.get("/portfolio")
async def get_portfolio() -> dict:
    """Portfolio summary."""
    return {"cash": 10000.0, "positions_value": 0.0, "total": 10000.0, "daily_pnl": 0.0}
