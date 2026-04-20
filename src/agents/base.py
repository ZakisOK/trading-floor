"""BaseAgent — Week 1 instrumentation:

- ``cycle_id``, ``cycle_started_at``, ``subsystem``, ``regime_fingerprint`` are
  now part of every AgentState. The supervisor (sage.run_trading_cycle) is
  responsible for stamping them at cycle entry.
- Every agent computes ``self.agent_version`` at init from
  ``(git_sha, model_name, prompt_template)``. Format is enforced by
  ``compute_agent_version`` AND by the agent_episodes CHECK constraint.
- ``analyze_with_heartbeat`` now wraps ``analyze`` with episode emission:
  every successful or failed agent invocation produces one row in
  ``stream:episodes`` (Redis), which the EpisodeWriter consumer drains into
  Postgres.

Episode emission is fire-and-forget. Redis outage does not fail a cycle —
we log a warning and continue. This is consistent with PRINCIPLES #11
(immutability is structural) and the spec's stated trade-off "episode loss
is preferable to cycle loss, but must be alerted".
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, TypedDict

import structlog
from uuid6 import uuid7

from src.core.cycle import utcnow
from src.core.redis import get_redis
from src.core.versioning import compute_agent_version
from src.streams import topology
from src.streams.producer import produce, produce_audit

# Skill loader is optional; stripped environments may not have the skills dir.
try:  # pragma: no cover - tested via fallback path
    from src.agents.skills import SkillLoader, get_skill_loader

    _SKILLS_AVAILABLE = True
except ImportError:  # pragma: no cover
    SkillLoader = object  # type: ignore[assignment,misc]
    get_skill_loader = None  # type: ignore[assignment]
    _SKILLS_AVAILABLE = False

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


# Redis flag that lets ops disable episode emission without redeploying.
# Default-on; set to "false" in Redis to mute the producer (the consumer keeps
# draining whatever is already on the stream).
EPISODE_EMISSION_FLAG = "feature:episode_pipeline_enabled"


class AgentState(TypedDict, total=False):
    """Cycle-shared state passed through the trading graph.

    Week 1 added: ``cycle_id``, ``cycle_started_at``, ``subsystem``,
    ``regime_fingerprint``. Week 2 added: ``sized_order``,
    ``portfolio_construction_reasoning``. Pre-existing fields kept for
    backwards compat.

    Marked ``total=False`` because LangGraph nodes mutate partial state.
    LangGraph's StateGraph only propagates keys declared here between
    nodes — if you add a new field, declare it here.
    """

    # Week 1 cycle identity
    cycle_id: str
    cycle_started_at: datetime
    subsystem: str
    regime_fingerprint: str

    # Week 2 portfolio construction
    sized_order: dict | None
    portfolio_construction_reasoning: str

    # Pre-existing
    agent_id: str
    agent_name: str
    messages: list[dict]
    market_data: dict | None
    signals: list[dict]
    risk_approved: bool
    final_decision: str | None
    confidence: float
    reasoning: str


def _redact_for_episode(state: AgentState | dict) -> dict:
    """Strip fields that would balloon the episode row.

    ``messages`` history is unbounded; we keep length only. ``market_data`` is
    snapshot separately so we don't double-store it.
    """
    safe = {}
    for k, v in dict(state).items():
        if k == "messages":
            safe[k + "_count"] = len(v) if isinstance(v, list) else 0
        elif k == "market_data":
            continue
        else:
            safe[k] = v
    return safe


class BaseAgent(ABC):
    """All Trading Floor agents extend this class."""

    name: str = "base"

    def __init__(
        self,
        agent_id: str,
        name: str,
        role: str,
        *,
        model_name: str = "unknown",
        prompt_template: str | None = None,
        subsystem: str = "legacy",
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self.role = role
        self.subsystem = subsystem
        self.model_name = model_name
        self.prompt_template = prompt_template if prompt_template is not None else f"role:{role}"
        self.agent_version = compute_agent_version(self.model_name, self.prompt_template)
        if model_name == "unknown" or prompt_template is None:
            # Loud-but-non-fatal so we can iteratively upgrade each subclass
            # in follow-up commits. The version is still well-formed and
            # unique-per-process; it's just uninformative.
            logger.warning(
                "agent_version_default_inputs",
                agent_id=agent_id,
                hint="pass model_name= and prompt_template= to super().__init__",
            )
        self._skill_loader = get_skill_loader() if _SKILLS_AVAILABLE and get_skill_loader else None

    # ------------------------------------------------------------------ skills

    def available_skills(self) -> list[dict[str, str]]:
        """Return the cheap skill index for this agent (no bodies loaded)."""
        if self._skill_loader is None:
            return []
        return self._skill_loader.list_skills(self.agent_id)

    def load_skill(self, skill_name: str) -> Any:
        """Load a full skill by name (agent-scoped with shared fallback)."""
        if self._skill_loader is None:
            return None
        return self._skill_loader.load(skill_name, agent_id=self.agent_id)

    def skill_index_prompt(self) -> str:
        """Return raw SKILL_INDEX markdown for inclusion in a system prompt."""
        if self._skill_loader is None:
            return ""
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
        cycle_id: str | None = None,
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
            "cycle_id": cycle_id or "",
        }, redis=redis)
        await produce_audit("signal_emitted", self.agent_id, {
            "symbol": symbol, "direction": direction, "confidence": confidence,
            "cycle_id": cycle_id,
        }, redis=redis)
        logger.info("signal_emitted", agent=self.name, symbol=symbol,
                    direction=direction, confidence=confidence,
                    cycle_id=cycle_id)

    async def heartbeat(
        self, status: str = "active", current_task: str | None = None
    ) -> None:
        """Publish the agent's live state to Redis so the dashboard reflects it.

        Elo is owned by position_monitor (updated on position close). Heartbeat
        writes only liveness fields so it doesn't stomp the Elo value.
        """
        redis = get_redis()
        mapping: dict[str, str] = {
            "status": status,
            "last_heartbeat": utcnow().isoformat(),
        }
        if current_task is not None:
            mapping["current_task"] = current_task
        await redis.hset(f"agent:state:{self.agent_id}", mapping=mapping)
        if status == "idle":
            await redis.hdel(f"agent:state:{self.agent_id}", "current_task")

    async def _episode_emission_enabled(self) -> bool:
        """Read the kill-switch-style feature flag from Redis. Default-on."""
        try:
            redis = get_redis()
            raw = await redis.get(EPISODE_EMISSION_FLAG)
            if raw is None:
                return True
            return str(raw).lower() not in ("false", "0", "off", "disabled")
        except Exception:  # noqa: BLE001 - never block a cycle on flag read
            return True

    async def _emit_episode(
        self,
        *,
        state: AgentState,
        updated_state: AgentState | None,
        latency_ms: int,
        error: str | None,
    ) -> None:
        """Fire-and-forget episode write to ``stream:episodes``.

        Keeps the trading path resilient: any failure here is logged and
        swallowed. The consumer is responsible for everything past Redis.
        """
        if not await self._episode_emission_enabled():
            return

        cycle_id = state.get("cycle_id")
        if not cycle_id:
            # Spec PRINCIPLE #6: "A cycle without a cycle_id is a bug." We log
            # loudly so the bug surfaces, but we don't raise here — raising
            # would convert a missed-instrumentation into a production outage.
            logger.error(
                "episode_missing_cycle_id",
                agent=self.agent_id,
                hint="run_trading_cycle must stamp cycle_id before agent dispatch",
            )
            return

        market = state.get("market_data") or {}
        symbol = (
            market.get("symbol", "UNKNOWN")
            if isinstance(market, dict) else "UNKNOWN"
        )

        payload = {
            "episode_id": str(uuid7()),
            "ts": utcnow().isoformat(),
            "cycle_id": cycle_id,
            "cycle_started_at": (
                state.get("cycle_started_at").isoformat()
                if isinstance(state.get("cycle_started_at"), datetime)
                else str(state.get("cycle_started_at") or utcnow().isoformat())
            ),
            "subsystem": state.get("subsystem") or self.subsystem or "legacy",
            "symbol": symbol,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "market_snapshot": json.dumps(market) if market else "{}",
            "input_state": json.dumps(_redact_for_episode(state), default=str),
            "parsed_signal": json.dumps(
                (updated_state or {}).get("signals") or [], default=str
            ),
            "reasoning": (updated_state or {}).get("reasoning", "") or "",
            "latency_ms": str(latency_ms),
            "error": error or "",
            "regime_fingerprint": state.get("regime_fingerprint") or "stub-v1:UNKNOWN",
        }

        try:
            redis = get_redis()
            await produce(topology.EPISODES, payload, redis=redis)
        except Exception as exc:  # noqa: BLE001 - never block a cycle on episode emit
            logger.warning(
                "episode_emit_failed",
                agent=self.agent_id,
                cycle_id=cycle_id,
                error=str(exc),
            )

    async def analyze_with_heartbeat(self, state: AgentState) -> AgentState:
        """Wrap analyze() with heartbeat updates AND episode emission.

        Every invocation produces exactly one episode (success or failure).
        The heartbeat semantics MC depends on (active → idle around analyze)
        are preserved.
        """
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "") if isinstance(market, dict) else ""
        started = time.monotonic()
        updated_state: AgentState | None = None
        error_str: str | None = None
        try:
            await self.heartbeat(status="active", current_task=symbol or None)
            updated_state = await self.analyze(state)
            return updated_state
        except Exception as exc:
            error_str = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            try:
                await self._emit_episode(
                    state=state,
                    updated_state=updated_state,
                    latency_ms=latency_ms,
                    error=error_str,
                )
            finally:
                # heartbeat MUST run last, regardless of episode emit outcome
                await self.heartbeat(status="idle", current_task=None)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Legacy run interface — delegates to analyze."""
        return await self.analyze(AgentState(**state))  # type: ignore[arg-type]

    @abstractmethod
    async def analyze(self, state: AgentState) -> AgentState:
        """Process state and return updated state with signals."""
        ...
