"""Risk engine — full implementation."""
from __future__ import annotations

from dataclasses import dataclass
import structlog
from src.core.config import settings

logger = structlog.get_logger()


@dataclass
class RiskCheck:
    approved: bool
    reason: str
    adjusted_size: float | None = None


class RiskEngine:
    def __init__(self) -> None:
        self.max_risk_pct = settings.max_risk_per_trade
        self.max_daily_loss = settings.max_daily_loss
        self._daily_pnl: float = 0.0
        self._portfolio_value: float = 10000.0

    def check_trade(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        proposed_size_pct: float,
    ) -> RiskCheck:
        if confidence < 0.5:
            return RiskCheck(False, f"Confidence {confidence:.0%} below 50% minimum")

        adjusted: float | None = None
        if proposed_size_pct > self.max_risk_pct:
            adjusted = self.max_risk_pct
            logger.info("risk_size_adjusted", from_pct=proposed_size_pct, to_pct=adjusted)

        daily_loss_pct = (
            abs(self._daily_pnl) / self._portfolio_value if self._portfolio_value > 0 else 0.0
        )
        if self._daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss:
            return RiskCheck(
                False,
                f"Daily loss limit {self.max_daily_loss:.0%} reached (current: {daily_loss_pct:.1%})",
            )

        reason = f"Approved — size={adjusted or proposed_size_pct:.1%}, confidence={confidence:.0%}"
        if adjusted:
            reason = f"Size adjusted to {adjusted:.1%} — {reason}"
        return RiskCheck(True, reason, adjusted)

    def update_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl
        logger.info("risk_pnl_updated", daily_pnl=self._daily_pnl)

    def reset_daily(self) -> None:
        self._daily_pnl = 0.0
        logger.info("risk_daily_reset")

    def set_portfolio_value(self, value: float) -> None:
        self._portfolio_value = value

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def portfolio_value(self) -> float:
        return self._portfolio_value


# Singleton risk engine
risk_engine = RiskEngine()


def check_position_size(notional: float, portfolio_value: float) -> bool:
    """Legacy helper — return True if size is within limit."""
    return (notional / portfolio_value) <= settings.max_risk_per_trade if portfolio_value else False
