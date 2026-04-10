"""Nova — Options / Volatility agent."""
from __future__ import annotations

import structlog
from src.agents.base import BaseAgent, AgentState

logger = structlog.get_logger()


class NovaAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("nova", "Nova", "Options & Volatility")

    async def analyze(self, state: AgentState) -> AgentState:
        # Phase 5 will add full options chain analysis
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        logger.info("nova_analyze", symbol=symbol, status="stub")
        return state
