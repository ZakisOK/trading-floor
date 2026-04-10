"""Pre-trade risk checks stub."""
from src.core.config import settings


def check_position_size(notional: float, portfolio_value: float) -> bool:
    """Return True if position size is within max_risk_per_trade limit."""
    # TODO: Implement full risk check suite (Phase 1)
    return (notional / portfolio_value) <= settings.max_risk_per_trade
