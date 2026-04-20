"""PortfolioConstructor — Week 2 / A2.

Sits between Diana and Atlas. Takes a Diana-approved cycle, sizes the trade
against the live portfolio snapshot, enforces per-mode caps, applies blackout
windows, and emits either a SizedOrder or a structured RejectedTrade.

Shadow-mode contract:
    feature:portfolio_constructor_enabled = "false"  →  passes through
        without overriding atlas's own sizing. Logs the decision it WOULD
        have made for offline comparison.
    "true" (or absent — default ON post-Week-2)      →  Atlas reads
        sized_order from state and submits exactly that quantity.

Idempotency: same cycle_id → same SizedOrder. Cached on cycle_id so a re-run
in the LangGraph supervisor doesn't double-size.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.agents.base import AgentState, BaseAgent
from src.core.config import settings
from src.core.redis import get_redis
from src.execution.portfolio_snapshot import (
    PortfolioSnapshot,
    get_portfolio_snapshot,
)
from src.execution.position_sizer import SizedOrder, position_sizer
from src.execution.position_source import BrokerUnavailableError

logger = structlog.get_logger()

CONSTRUCTOR_FLAG = "feature:portfolio_constructor_enabled"
DEFAULT_AUTONOMY = "COMMANDER"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectedTrade:
    """Constructor said no. ``reason`` is operator-readable."""

    symbol: str
    direction: str
    reason: str
    rejected_at: datetime


@dataclass(frozen=True)
class ConstructorDecision:
    """Carries either a SizedOrder OR a RejectedTrade plus reasoning text."""

    sized_order: SizedOrder | None
    rejected: RejectedTrade | None
    reasoning: str
    snapshot_venue: str
    snapshot_portfolio_value: float

    @property
    def approved(self) -> bool:
        return self.sized_order is not None and self.sized_order.quantity > 0


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


def _limits_for_mode(mode: str) -> dict[str, float]:
    """Look up per-mode caps. Falls back to COMMANDER (the safest)."""
    table = settings.autonomy_mode_limits
    return table.get(mode.upper()) or table.get(DEFAULT_AUTONOMY) or {
        "max_risk_per_trade": 0.02,
        "max_daily_loss": 0.05,
        "max_gross_exposure": 1.50,
        "max_single_symbol": 0.10,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _read_autonomy_mode() -> str:
    try:
        redis = get_redis()
        val = await redis.hget("config:system", "autonomy_mode")
        return (val or DEFAULT_AUTONOMY).upper()
    except Exception:  # noqa: BLE001
        return DEFAULT_AUTONOMY


async def _read_blackout_windows() -> list[dict[str, Any]]:
    """Read configured blackout windows from Redis.

    Format: list of dicts with ``start_iso``, ``end_iso``, ``label``. Empty
    list when none configured. Constructor rejects trades whose execution
    timestamp falls inside any window.
    """
    try:
        import json
        redis = get_redis()
        raw = await redis.get("config:blackout_windows")
        if not raw:
            return []
        loaded = json.loads(raw)
        if isinstance(loaded, list):
            return loaded
    except Exception:  # noqa: BLE001
        pass
    return []


def _blackout_active(windows: list[dict[str, Any]], now: datetime) -> str | None:
    for w in windows:
        try:
            start = datetime.fromisoformat(w["start_iso"])
            end = datetime.fromisoformat(w["end_iso"])
        except (KeyError, ValueError):
            continue
        if start <= now <= end:
            return str(w.get("label") or "blackout")
    return None


def _correlation_overlap(
    snapshot: PortfolioSnapshot, symbol: str, threshold: float = 0.7
) -> list[tuple[str, float]]:
    """Return (existing_symbol, correlation) pairs above threshold.

    Reads the matrix from snapshot. Empty matrix → no constraint applied.
    """
    if not snapshot.correlation_matrix:
        return []
    overlap: list[tuple[str, float]] = []
    for pos in snapshot.positions:
        other = pos["symbol"]
        if other == symbol:
            continue
        # Matrix keys are joined "A|B" with sorted symbols
        key = "|".join(sorted([symbol, other]))
        corr = snapshot.correlation_matrix.get(key)
        if corr is not None and abs(corr) >= threshold:
            overlap.append((other, corr))
    return overlap


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


_PROMPT_SKELETON = (
    "PortfolioConstructor — deterministic. "
    "Sizes Diana-approved cycles against PortfolioSnapshot. Enforces "
    "per-mode caps, blackout windows, correlation overlap. "
    "Output: SizedOrder (with reasoning) or RejectedTrade (with reason)."
)


class PortfolioConstructorAgent(BaseAgent):
    """Constructor as a graph node. Reads consensus from state, writes sized_order."""

    # Idempotency cache: cycle_id → ConstructorDecision
    _decision_cache: dict[str, ConstructorDecision] = {}

    def __init__(self) -> None:
        super().__init__(
            "portfolio_constructor",
            "Portfolio Constructor",
            "Sizing & Risk",
            model_name="deterministic",
            prompt_template=_PROMPT_SKELETON,
        )

    async def _shadow_enabled(self) -> bool:
        """Return True when constructor should run in shadow (decisions logged
        but Atlas keeps its own sizing). Default: live (False)."""
        try:
            redis = get_redis()
            raw = await redis.get(CONSTRUCTOR_FLAG)
            if raw is None:
                return False  # default-on for the live path
            return str(raw).lower() in ("false", "0", "off", "disabled", "shadow")
        except Exception:  # noqa: BLE001
            return False

    async def analyze(self, state: AgentState) -> AgentState:
        if not state.get("risk_approved"):
            # Diana didn't approve — skip the work entirely.
            return state

        cycle_id = state.get("cycle_id") or ""
        if not cycle_id:
            logger.error("constructor_missing_cycle_id")
            return state

        # Idempotency
        cached = self._decision_cache.get(cycle_id)
        if cached is not None:
            return self._merge_decision(state, cached)

        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")
        direction = (state.get("final_decision") or "NEUTRAL").upper()
        confidence = float(state.get("confidence") or 0.0)
        price = float(market.get("price") or market.get("close") or 0.0)

        decision = await self._build_decision(
            cycle_id=cycle_id,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            price=price,
        )
        self._decision_cache[cycle_id] = decision

        # Bound the cache so a long-running process doesn't accumulate.
        if len(self._decision_cache) > 5000:
            # Drop oldest 1000 entries (insertion order on Python 3.7+)
            for k in list(self._decision_cache.keys())[:1000]:
                self._decision_cache.pop(k, None)

        if await self._shadow_enabled():
            logger.info(
                "constructor_shadow_decision",
                cycle_id=cycle_id, symbol=symbol,
                approved=decision.approved,
                reasoning=decision.reasoning,
            )
            # Don't mutate state in shadow mode — Atlas keeps doing its thing
            return state

        return self._merge_decision(state, decision)

    def _merge_decision(
        self, state: AgentState, decision: ConstructorDecision
    ) -> AgentState:
        out = dict(state)
        out["sized_order"] = (
            {
                "symbol": decision.sized_order.symbol,
                "side": decision.sized_order.side,
                "quantity": decision.sized_order.quantity,
                "notional": decision.sized_order.notional,
                "price": decision.sized_order.price,
                "confidence_adjusted_risk_pct": decision.sized_order.confidence_adjusted_risk_pct,
                "annualized_vol": decision.sized_order.annualized_vol,
            }
            if decision.sized_order is not None
            else None
        )
        out["portfolio_construction_reasoning"] = decision.reasoning
        if not decision.approved:
            # Override Diana's approval — constructor's veto is final.
            out["risk_approved"] = False
            out["final_decision"] = None
        return out  # type: ignore[return-value]

    async def _build_decision(
        self,
        *,
        cycle_id: str,
        symbol: str,
        direction: str,
        confidence: float,
        price: float,
    ) -> ConstructorDecision:
        now = datetime.now(UTC)
        # 1. Snapshot — fail loud if venue is broken.
        try:
            snapshot = await get_portfolio_snapshot(
                current_prices={symbol: price} if price else None,
            )
        except BrokerUnavailableError as exc:
            return self._reject(
                symbol, direction,
                reason=f"broker_unavailable: {exc}",
                snapshot_venue="unknown", snapshot_pv=0.0, now=now,
            )

        # 2. Blackout windows
        windows = await _read_blackout_windows()
        active = _blackout_active(windows, now)
        if active is not None:
            return self._reject(
                symbol, direction,
                reason=f"blackout_window:{active}",
                snapshot_venue=snapshot.venue,
                snapshot_pv=float(snapshot.portfolio_value),
                now=now,
            )

        # 3. Per-mode caps
        mode = await _read_autonomy_mode()
        limits = _limits_for_mode(mode)

        # Daily loss cap — refuse new exposure if we're already at the limit
        if snapshot.portfolio_value > 0:
            day_loss_pct = float(snapshot.daily_pnl) / float(snapshot.portfolio_value)
            if day_loss_pct < 0 and abs(day_loss_pct) >= limits["max_daily_loss"]:
                return self._reject(
                    symbol, direction,
                    reason=(
                        f"daily_loss_cap:{day_loss_pct:.2%} >= "
                        f"{limits['max_daily_loss']:.2%} (mode={mode})"
                    ),
                    snapshot_venue=snapshot.venue,
                    snapshot_pv=float(snapshot.portfolio_value),
                    now=now,
                )

        # Gross exposure cap
        gross_pct = (
            float(snapshot.gross_exposure) / float(snapshot.portfolio_value)
            if snapshot.portfolio_value > 0 else 0.0
        )
        if gross_pct >= limits["max_gross_exposure"]:
            return self._reject(
                symbol, direction,
                reason=(
                    f"gross_exposure_cap:{gross_pct:.2%} >= "
                    f"{limits['max_gross_exposure']:.2%} (mode={mode})"
                ),
                snapshot_venue=snapshot.venue,
                snapshot_pv=float(snapshot.portfolio_value),
                now=now,
            )

        # 4. Size with confidence weighting + per-mode max risk cap
        sized = await position_sizer.size(
            signal={
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
            },
            market_data={"symbol": symbol, "price": price},
            portfolio={"portfolio_value": float(snapshot.portfolio_value)},
        )

        if sized.quantity <= 0:
            return self._reject(
                symbol, direction,
                reason="sizer_returned_zero",
                snapshot_venue=snapshot.venue,
                snapshot_pv=float(snapshot.portfolio_value),
                now=now,
            )

        # 5. Per-symbol cap — downsize, don't reject
        max_symbol_notional = (
            float(snapshot.portfolio_value) * limits["max_single_symbol"]
        )
        existing = snapshot.position_for(symbol)
        existing_notional = (
            float(existing.get("quantity", 0))
            * float(existing.get("current_price", existing.get("avg_price", 0)))
            if existing else 0.0
        )
        if (sized.notional + existing_notional) > max_symbol_notional:
            allowed = max(0.0, max_symbol_notional - existing_notional)
            new_qty = allowed / price if price > 0 else 0.0
            if new_qty <= 0:
                return self._reject(
                    symbol, direction,
                    reason=(
                        f"symbol_already_at_cap:{existing_notional:.2f} >= "
                        f"{max_symbol_notional:.2f}"
                    ),
                    snapshot_venue=snapshot.venue,
                    snapshot_pv=float(snapshot.portfolio_value),
                    now=now,
                )
            logger.info(
                "constructor_downsized_for_symbol_cap",
                cycle_id=cycle_id, symbol=symbol,
                from_qty=sized.quantity, to_qty=new_qty,
                cap=max_symbol_notional,
            )
            sized = SizedOrder(
                symbol=sized.symbol, side=sized.side, quantity=new_qty,
                notional=allowed, price=sized.price,
                confidence_adjusted_risk_pct=sized.confidence_adjusted_risk_pct,
                annualized_vol=sized.annualized_vol,
            )

        # 6. Correlation overlap — informational; downsize when matrix is loaded
        overlap = _correlation_overlap(snapshot, symbol)
        if overlap:
            # Halve the size for each correlated existing position. Bounded
            # at min 0.25× of original. This is conservative — Week 6 adds a
            # smarter regression-based correction.
            multiplier = max(0.25, 1.0 / (1.0 + len(overlap)))
            sized = SizedOrder(
                symbol=sized.symbol, side=sized.side,
                quantity=sized.quantity * multiplier,
                notional=sized.notional * multiplier, price=sized.price,
                confidence_adjusted_risk_pct=sized.confidence_adjusted_risk_pct,
                annualized_vol=sized.annualized_vol,
            )

        reasoning = (
            f"approved sized={sized.quantity:.6f} ({sized.side}) "
            f"notional=${sized.notional:.2f} mode={mode} "
            f"venue={snapshot.venue} pv=${float(snapshot.portfolio_value):.2f} "
            f"gross={gross_pct:.2%} corr_overlap={len(overlap)}"
        )
        return ConstructorDecision(
            sized_order=sized,
            rejected=None,
            reasoning=reasoning,
            snapshot_venue=snapshot.venue,
            snapshot_portfolio_value=float(snapshot.portfolio_value),
        )

    @staticmethod
    def _reject(
        symbol: str, direction: str, reason: str,
        snapshot_venue: str, snapshot_pv: float, now: datetime,
    ) -> ConstructorDecision:
        return ConstructorDecision(
            sized_order=None,
            rejected=RejectedTrade(
                symbol=symbol, direction=direction,
                reason=reason, rejected_at=now,
            ),
            reasoning=f"rejected: {reason}",
            snapshot_venue=snapshot_venue,
            snapshot_portfolio_value=snapshot_pv,
        )


# Singleton — registered into the graph by sage.py.
portfolio_constructor = PortfolioConstructorAgent()
