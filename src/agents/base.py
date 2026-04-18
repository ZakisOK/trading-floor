"""BaseAgent — full implementation with Redis stream integration, skill library,
and firm-memory hooks.

The skill and memory helpers degrade gracefully — if the Graphiti service is
down or the skills directory is unreadable, the agent still runs. Recall
returns an empty list and remember is a no-op in those failure modes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Any, TypedDict

import structlog

from src.core.redis import get_redis
from src.streams.producer import produce, produce_audit
from src.streams import topology

# Skill loader is local-filesystem and always safe to import.
from src.agents.skills import SkillLoader, get_skill_loader

# Memory client talks to Graphiti over HTTP; guard the import so BaseAgent
# still imports even if httpx is missing in a stripped environment.
try:  # pragma: no cover - tested via fallback path
    from src.core.memory import FirmMemory, get_memory

    _MEMORY_AVAILABLE = True
except ImportError:  # pragma: no cover
    FirmMemory = None  # type: ignore[assignment,misc]
    get_memory = None  # type: ignore[assignment]
    _MEMORY_AVAILABLE = False

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
        self._skill_loader: SkillLoader = get_skill_loader()

    # ------------------------------------------------------------------ skills

    def available_skills(self) -> list[dict[str, str]]:
        """Return the cheap skill index for this agent (no bodies loaded)."""
        return self._skill_loader.list_skills(self.agent_id)

    def load_skill(self, skill_name: str) -> Any:
        """Load a full skill by name (agent-scoped with shared fallback)."""
        return self._skill_loader.load(skill_name, agent_id=self.agent_id)

    def skill_index_prompt(self) -> str:
        """Return raw SKILL_INDEX markdown for inclusion in a system prompt."""
        return self._skill_loader.get_system_prompt_index(self.agent_id)

    # ------------------------------------------------------------------ memory

    async def remember(
        self, content: str, episode_type: str = "observation"
    ) -> None:
        """Persist a free-form episode to this agent's private memory group."""
        if not _MEMORY_AVAILABLE or get_memory is None:
            logger.debug("remember_skipped_no_memory", agent=self.agent_id)
            return
        try:
            await get_memory().add_episode(
                agent_id=self.agent_id,
                episode_type=episode_type,
                content=content,
            )
        except Exception as exc:  # noqa: BLE001 - memory is best-effort
            logger.warning(
                "remember_failed",
                agent=self.agent_id,
                episode_type=episode_type,
                error=str(exc),
            )

    async def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search this agent's private memory group."""
        if not _MEMORY_AVAILABLE or get_memory is None:
            return []
        try:
            return await get_memory().search(
                query=query, group_ids=[self.agent_id], limit=limit
            )
        except Exception as exc:  # noqa: BLE001 - memory is best-effort
            logger.warning(
                "recall_failed",
                agent=self.agent_id,
                query=query,
                error=str(exc),
            )
            return []

    async def recall_firm(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search firm-wide memory (no group filter)."""
        if not _MEMORY_AVAILABLE or get_memory is None:
            return []
        try:
            return await get_memory().search(query=query, limit=limit)
        except Exception as exc:  # noqa: BLE001 - memory is best-effort
            logger.warning(
                "recall_firm_failed",
                agent=self.agent_id,
                query=query,
                error=str(exc),
            )
            return []

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

    async def heartbeat(
        self, status: str = "active", current_task: str | None = None
    ) -> None:
        """Publish the agent's live state to Redis so the dashboard reflects it."""
        redis = get_redis()
        mapping: dict[str, str] = {
            "status": status,
            "last_heartbeat": datetime.now(UTC).isoformat(),
            "elo": str(self.elo_rating),
        }
        if current_task is not None:
            mapping["current_task"] = current_task
        await redis.hset(f"agent:state:{self.agent_id}", mapping=mapping)
        if status == "idle":
            await redis.hdel(f"agent:state:{self.agent_id}", "current_task")

    async def analyze_with_heartbeat(self, state: AgentState) -> AgentState:
        """Wrap analyze() with Redis heartbeat updates so /api/agents shows live status."""
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "") if isinstance(market, dict) else ""
        try:
            await self.heartbeat(status="active", current_task=symbol or None)
            return await self.analyze(state)
        finally:
            await self.heartbeat(status="idle", current_task=None)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Legacy run interface — delegates to analyze."""
        return await self.analyze(AgentState(**state))  # type: ignore[arg-type]

    @abstractmethod
    async def analyze(self, state: AgentState) -> AgentState:
        """Process state and return updated state with signals."""
        ...
