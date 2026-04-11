"""
AgentMemory — persistent per-agent memory stored in Redis.

Each agent accumulates a history of signal calls and their trade outcomes.
This feeds two things:
  1. Nova's Bayesian aggregation (rolling accuracy weights, optionally regime-split)
  2. Lesson injection into each agent's next prompt (similar-situation retrieval)

Redis key schema:
  signal:{signal_id}                       — Hash: full signal record + outcome
  agent:{agent_id}:signals                 — Sorted set: signal_ids scored by timestamp
  agent:{agent_id}:accuracy                — Hash: rolling win/loss counts
  agent:{agent_id}:weight                  — String: current Bayesian weight (0.0–1.0)
  agent:{agent_id}:calibration:regime:{r}  — Hash: regime-split accuracy (from calibration.py)
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import structlog

from src.core.redis import get_redis

logger = structlog.get_logger()

# How many recent signals to consider for rolling accuracy
ROLLING_WINDOW = 50

# Default weight when no history exists (equal weighting)
DEFAULT_WEIGHT = 0.5


class AgentMemory:
    """Persistent memory for trading agents.

    Stores past signal calls, outcomes (win/loss), and confidence calibration.
    All writes go to Redis so they survive process restarts.
    """

    # -------------------------------------------------------------------------
    # Writing
    # -------------------------------------------------------------------------

    async def record_signal(
        self,
        agent_id: str,
        symbol: str,
        direction: str,
        confidence: float,
        thesis: str,
        regime: str = "UNKNOWN",
        signal_id: str | None = None,
    ) -> str:
        """
        Called when an agent emits a signal.
        Returns the signal_id so callers can link the outcome later.
        """
        redis = get_redis()
        sid = signal_id or str(uuid.uuid4())
        now = time.time()

        record = {
            "signal_id": sid,
            "agent_id": agent_id,
            "symbol": symbol,
            "direction": direction,
            "confidence": str(confidence),
            "thesis": thesis,
            "regime": regime,
            "timestamp": datetime.now(UTC).isoformat(),
            "outcome": "PENDING",
            "pnl_pct": "",
            "hold_time_minutes": "",
        }

        await redis.hset(f"signal:{sid}", mapping=record)
        await redis.expire(f"signal:{sid}", 60 * 60 * 24 * 90)
        await redis.zadd(f"agent:{agent_id}:signals", {sid: now})
        await redis.zremrangebyrank(f"agent:{agent_id}:signals", 0, -(ROLLING_WINDOW * 2 + 1))

        logger.debug("agent_memory_signal_recorded", agent=agent_id, signal_id=sid, symbol=symbol)
        return sid

    async def record_outcome(
        self,
        signal_id: str,
        outcome: Literal["WIN", "LOSS", "NEUTRAL"],
        pnl_pct: float,
        hold_time_minutes: int,
    ) -> None:
        """
        Called by Desk 2 (TradeDeskAgent) when a trade closes.
        Links the outcome back to every originating agent signal and updates
        their rolling accuracy weights.
        """
        redis = get_redis()

        await redis.hset(f"signal:{signal_id}", mapping={
            "outcome": outcome,
            "pnl_pct": str(pnl_pct),
            "hold_time_minutes": str(hold_time_minutes),
            "resolved_at": datetime.now(UTC).isoformat(),
        })

        agent_id = await redis.hget(f"signal:{signal_id}", "agent_id")
        if not agent_id:
            logger.warning("record_outcome_no_agent", signal_id=signal_id)
            return

        if outcome == "WIN":
            await redis.hincrby(f"agent:{agent_id}:accuracy", "wins", 1)
        elif outcome == "LOSS":
            await redis.hincrby(f"agent:{agent_id}:accuracy", "losses", 1)
        else:
            await redis.hincrby(f"agent:{agent_id}:accuracy", "neutrals", 1)

        await redis.hincrby(f"agent:{agent_id}:accuracy", "total", 1)

        new_weight = await self._recalculate_weight(agent_id)
        await redis.set(f"agent:{agent_id}:weight", str(new_weight))

        logger.info(
            "agent_memory_outcome_recorded",
            agent=agent_id,
            signal_id=signal_id,
            outcome=outcome,
            pnl_pct=pnl_pct,
            new_weight=round(new_weight, 4),
        )

    # -------------------------------------------------------------------------
    # Reading — accuracy & weights
    # -------------------------------------------------------------------------

    async def get_agent_accuracy(
        self,
        agent_id: str,
        last_n: int = ROLLING_WINDOW,
        regime: str | None = None,
    ) -> float:
        """
        Returns win rate over the last N resolved signals for this agent.

        When `regime` is provided, returns accuracy filtered to signals recorded
        in that regime only. Falls back to overall accuracy if regime-filtered
        data has fewer than 5 signals.

        Phase 2 usage in Nova:
            weight = await agent_memory.get_agent_accuracy(agent_id, regime=current_regime, last_n=30)
        """
        if regime is not None:
            # Try regime-specific accuracy from calibration cache first
            redis = get_redis()
            try:
                data = await redis.hgetall(f"agent:{agent_id}:calibration:regime:{regime}")
                if data:
                    total = int(data.get("total", 0))
                    if total >= 5:
                        return float(data.get("accuracy", DEFAULT_WEIGHT))
            except Exception:
                pass

            # Fall back: scan signal history and filter by regime
            redis = get_redis()
            recent_ids = await redis.zrevrange(f"agent:{agent_id}:signals", 0, last_n * 3 - 1)
            wins = 0
            resolved = 0
            for sid in recent_ids:
                if resolved >= last_n:
                    break
                sig_regime = await redis.hget(f"signal:{sid}", "regime")
                if sig_regime != regime:
                    continue
                outcome = await redis.hget(f"signal:{sid}", "outcome")
                if outcome in ("WIN", "LOSS"):
                    resolved += 1
                    if outcome == "WIN":
                        wins += 1

            if resolved < 5:
                # Not enough regime-specific history — fall back to overall
                return await self.get_agent_accuracy(agent_id, last_n=last_n, regime=None)
            return wins / resolved

        # Overall accuracy (no regime filter)
        redis = get_redis()
        recent_ids = await redis.zrevrange(f"agent:{agent_id}:signals", 0, last_n - 1)
        if not recent_ids:
            return DEFAULT_WEIGHT

        wins = 0
        resolved = 0
        for sid in recent_ids:
            outcome = await redis.hget(f"signal:{sid}", "outcome")
            if outcome in ("WIN", "LOSS"):
                resolved += 1
                if outcome == "WIN":
                    wins += 1

        if resolved == 0:
            return DEFAULT_WEIGHT
        return wins / resolved

    async def get_agent_weight(self, agent_id: str) -> float:
        """Returns cached Bayesian weight. Falls back to DEFAULT_WEIGHT."""
        redis = get_redis()
        raw = await redis.get(f"agent:{agent_id}:weight")
        if raw is None:
            return DEFAULT_WEIGHT
        try:
            return float(raw)
        except ValueError:
            return DEFAULT_WEIGHT

    async def suppress_agent_weight(
        self, agent_id: str, factor: float = 0.75, ttl_seconds: int = 3600
    ) -> None:
        """Temporarily reduce an agent's weight by `factor` for `ttl_seconds`."""
        redis = get_redis()
        current = await self.get_agent_weight(agent_id)
        suppressed = current * factor
        await redis.set(f"agent:{agent_id}:weight:suppressed", str(suppressed), ex=ttl_seconds)
        logger.warning(
            "agent_weight_suppressed",
            agent=agent_id,
            original=round(current, 4),
            suppressed=round(suppressed, 4),
            ttl_seconds=ttl_seconds,
        )

    async def get_effective_weight(self, agent_id: str) -> float:
        """Returns suppressed weight if active, otherwise normal weight."""
        redis = get_redis()
        suppressed = await redis.get(f"agent:{agent_id}:weight:suppressed")
        if suppressed is not None:
            try:
                return float(suppressed)
            except ValueError:
                pass
        return await self.get_agent_weight(agent_id)

    # -------------------------------------------------------------------------
    # Reading — lesson injection
    # -------------------------------------------------------------------------

    async def get_similar_situations(
        self,
        agent_id: str,
        symbol: str,
        regime: str,
        n: int = 3,
    ) -> list[dict]:
        """Retrieves the N most similar past situations this agent faced."""
        redis = get_redis()
        recent_ids = await redis.zrevrange(f"agent:{agent_id}:signals", 0, 99)
        matches: list[dict] = []

        for sid in recent_ids:
            if len(matches) >= n:
                break
            rec = await redis.hgetall(f"signal:{sid}")
            if not rec:
                continue
            if rec.get("outcome") not in ("WIN", "LOSS", "NEUTRAL"):
                continue
            if rec.get("symbol") != symbol:
                continue
            if rec.get("regime") != regime and regime != "UNKNOWN":
                continue

            matches.append({
                "situation": rec.get("thesis", "")[:200],
                "direction": rec.get("direction", ""),
                "confidence": float(rec.get("confidence", 0.5)),
                "outcome": rec.get("outcome", ""),
                "pnl_pct": float(rec.get("pnl_pct", 0)) if rec.get("pnl_pct") else 0.0,
                "timestamp": rec.get("timestamp", ""),
            })

        return matches

    async def get_lessons_for_agent(self, agent_id: str, symbol: str, regime: str) -> str:
        """Returns a formatted string of lessons to inject into the agent's next prompt."""
        similar = await self.get_similar_situations(agent_id, symbol, regime, n=5)
        if not similar:
            return ""

        accuracy = await self.get_agent_accuracy(agent_id, last_n=ROLLING_WINDOW)

        lines = [f"Your recent {symbol} calls in {regime} market regime:"]
        for s in similar:
            sign = "+" if s["pnl_pct"] > 0 else ""
            lines.append(
                f"  - {s['timestamp'][:10]}: {s['direction']} "
                f"(conf {s['confidence']:.2f}) → {s['outcome']} "
                f"({sign}{s['pnl_pct']:.1%})"
            )

        win_rate_pct = int(accuracy * 100)
        lines.append(f"Your overall accuracy across last {ROLLING_WINDOW} signals: {win_rate_pct}%.")
        if accuracy < 0.4:
            lines.append("You have been underperforming recently. Consider reducing your confidence scores.")
        elif accuracy > 0.65:
            lines.append("You have been performing well recently. Trust your analysis.")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _recalculate_weight(self, agent_id: str) -> float:
        """Recomputes rolling accuracy over last ROLLING_WINDOW resolved signals."""
        return await self.get_agent_accuracy(agent_id, last_n=ROLLING_WINDOW)


# Module-level singleton — import this everywhere
agent_memory = AgentMemory()
