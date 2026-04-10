"""BaseAgent — full implementation with Redis stream integration."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Any, TypedDict

import structlog

from src.core.redis import get_redis
from src.streams.producer import produce, produce_audit
from src.streams import topology

logger = structlog.get_logger()


class AgentState(TypedDict):
    agent_id: str
    agent_name: str
    messages: list[dict]
    market_data: dict | None
    signals: list[dict]
    risk_approved: bool
    final_decision: str | None
    confidence: float
    reasoning: str


class BaseAgent(ABC):
    """All Trading Floor agents extend this class."""

    name: str = "base"

    def __init__(self, agent_id: str, name: str, role: str) -> None:
        self.agent_id = agent_id
        self.name = name
        self.role = role
        self.elo_rating = 1200.0

    async def emit_signal(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        thesis: str,
        strategy: str,
        entry: float | None = None,
        stop: float | None = None,
        target: float | None = None,
    ) -> None:
        redis = get_redis()
        await produce(topology.SIGNALS_RAW, {
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "symbol": symbol,
            "direction": direction,
            "confidence": str(confidence),
            "thesis": thesis,
            "strategy": strategy,
            "entry_price": str(entry) if entry else "",
            "stop_loss": str(stop) if stop else "",
            "take_profit": str(target) if target else "",
        }, redis=redis)
        await produce_audit("signal_emitted", self.agent_id, {
            "symbol": symbol, "direction": direction, "confidence": confidence,
        }, redis=redis)
        logger.info("signal_emitted", agent=self.name, symbol=symbol,
                    direction=direction, confidence=confidence)

    async def heartbeat(self) -> None:
        redis = get_redis()
        await redis.hset(f"agent:state:{self.agent_id}", mapping={
            "status": "active",
            "last_heartbeat": datetime.now(UTC).isoformat(),
            "elo": str(self.elo_rating),
        })

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Legacy run interface — delegates to analyze."""
        return await self.analyze(AgentState(**state))  # type: ignore[arg-type]

    @abstractmethod
    async def analyze(self, state: AgentState) -> AgentState:
        """Process state and return updated state with signals."""
        ...
