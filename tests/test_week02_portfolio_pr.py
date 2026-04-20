"""Week 2 / Portfolio PR — T-PC unit tests.

Hermetic: fakes Redis + the position_provider so we don't need a live venue.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from src.agents import portfolio_constructor as pc_mod
from src.agents.base import AgentState
from src.agents.portfolio_constructor import (
    CONSTRUCTOR_FLAG,
    ConstructorDecision,
    PortfolioConstructorAgent,
)
from src.core import redis as redis_module
from src.execution import portfolio_snapshot as snapshot_mod
from src.execution.portfolio_snapshot import PortfolioSnapshot
from src.execution.position_sizer import PositionSizer, VolatilityPositionSizer
from src.execution.position_source import BrokerUnavailableError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAsyncRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.streams: dict[str, list] = {}
        self._counter = 0

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, **_: Any) -> bool:
        self.kv[key] = value
        return True

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key: str, *args: Any, mapping: dict[str, str] | None = None,
                   **kwargs: Any) -> int:
        bucket = self.hashes.setdefault(key, {})
        if mapping:
            bucket.update({k: str(v) for k, v in mapping.items()})
            return len(mapping)
        if len(args) >= 2:
            bucket[args[0]] = str(args[1])
            return 1
        return 0

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def xadd(self, stream: str, payload: dict[str, str], **_: Any) -> str:
        self._counter += 1
        msg_id = f"{self._counter}-0"
        self.streams.setdefault(stream, []).append((msg_id, dict(payload)))
        return msg_id


class _StubVolSizer(VolatilityPositionSizer):
    async def get_volatility(self, symbol: str, window: int = 20) -> float:
        return 0.30

    async def _get_volume_24h_usd(self, symbol: str, price: float) -> float | None:
        return 10_000_000_000.0

    async def _apply_liquidity_cap(self, symbol: str, quantity: float, price: float) -> float:
        return quantity


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncRedis:
    fr = FakeAsyncRedis()
    # Reset the module-level cached real redis client so a stale connection
    # from a prior test (different event loop) is never returned.
    monkeypatch.setattr(redis_module, "_redis_client", None)
    monkeypatch.setattr(redis_module, "get_redis", lambda: fr)
    monkeypatch.setattr(pc_mod, "get_redis", lambda: fr)
    # Patch the snapshot helper so we don't need a live position_provider.
    monkeypatch.setattr(snapshot_mod, "get_portfolio_snapshot", _make_snapshot_factory(fr))
    # The constructor module looked up get_portfolio_snapshot via direct
    # import — patch the binding it actually uses.
    monkeypatch.setattr(pc_mod, "get_portfolio_snapshot", _make_snapshot_factory(fr))
    return fr


def _snapshot(
    *,
    venue: str = "sim",
    portfolio_value: float = 10_000.0,
    daily_pnl: float = 0.0,
    positions: list[dict] | None = None,
    correlation: dict[str, float] | None = None,
) -> PortfolioSnapshot:
    positions_t = tuple(positions or ())
    gross = sum(
        abs(float(p["quantity"]) * float(p.get("current_price", p.get("avg_price", 0))))
        for p in (positions or [])
    )
    net = sum(
        float(p["quantity"]) * float(p.get("current_price", p.get("avg_price", 0)))
        * (1 if str(p.get("side", "LONG")).upper() == "LONG" else -1)
        for p in (positions or [])
    )
    return PortfolioSnapshot(
        venue=venue,
        portfolio_value=Decimal(str(portfolio_value)),
        daily_pnl=Decimal(str(daily_pnl)),
        positions=positions_t,
        gross_exposure=Decimal(str(gross)),
        net_exposure=Decimal(str(net)),
        correlation_matrix=correlation or {},
        captured_at=0.0,
    )


def _make_snapshot_factory(redis: FakeAsyncRedis):
    """Patched get_portfolio_snapshot pulls from redis.kv['__snapshot__']."""
    async def _f(*, current_prices=None, force_refresh=False) -> PortfolioSnapshot:
        raw = redis.kv.get("__snapshot__")
        if raw is None:
            return _snapshot()
        if raw == "RAISE":
            raise BrokerUnavailableError("alpaca down")
        return raw  # type: ignore[return-value]
    return _f


def _state(symbol: str = "BTC/USD", direction: str = "LONG", confidence: float = 0.7,
           price: float = 60_000.0) -> AgentState:
    from src.core.cycle import new_cycle_id, utcnow
    return {
        "cycle_id": new_cycle_id(),
        "cycle_started_at": utcnow(),
        "subsystem": "legacy",
        "regime_fingerprint": f"stub-v1:{symbol}",
        "agent_id": "sage", "agent_name": "Sage",
        "messages": [], "market_data": {"symbol": symbol, "price": price},
        "signals": [{"agent": "marcus", "direction": direction, "confidence": confidence}],
        "risk_approved": True,
        "final_decision": direction,
        "confidence": confidence,
        "reasoning": "test",
    }


@pytest.fixture(autouse=True)
def patch_sizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the stub vol sizer so we don't hit Redis for prices."""
    stub = PositionSizer(vol_sizer=_StubVolSizer())
    monkeypatch.setattr(pc_mod, "position_sizer", stub)


# ---------------------------------------------------------------------------
# T-PC-04: per-mode caps enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_pc_04_commander_mode_2pct_max_risk(
    fake_redis: FakeAsyncRedis, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis.hashes["config:system"] = {"autonomy_mode": "COMMANDER"}
    fake_redis.kv["__snapshot__"] = _snapshot(portfolio_value=10_000.0)

    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    out = await constructor.analyze(_state(confidence=1.0))
    sized = out["sized_order"]
    assert sized is not None
    assert sized["confidence_adjusted_risk_pct"] <= 0.02 + 1e-9


@pytest.mark.asyncio
async def test_t_pc_04_yolo_mode_5pct_max_risk(
    fake_redis: FakeAsyncRedis, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis.hashes["config:system"] = {"autonomy_mode": "YOLO"}
    fake_redis.kv["__snapshot__"] = _snapshot(portfolio_value=10_000.0)

    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    out = await constructor.analyze(_state(confidence=1.0))
    sized = out["sized_order"]
    assert sized is not None
    assert sized["confidence_adjusted_risk_pct"] <= 0.05 + 1e-9


# ---------------------------------------------------------------------------
# T-PC-03: blackout window rejects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_pc_03_blackout_window_rejects(
    fake_redis: FakeAsyncRedis,
) -> None:
    from datetime import datetime, timedelta, UTC
    now = datetime.now(UTC)
    window = {
        "start_iso": (now - timedelta(minutes=5)).isoformat(),
        "end_iso": (now + timedelta(minutes=5)).isoformat(),
        "label": "FOMC",
    }
    fake_redis.kv["config:blackout_windows"] = json.dumps([window])
    fake_redis.kv["__snapshot__"] = _snapshot(portfolio_value=10_000.0)

    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    out = await constructor.analyze(_state())
    assert out["sized_order"] is None
    assert "blackout_window:FOMC" in out["portfolio_construction_reasoning"]
    assert out["risk_approved"] is False  # constructor's veto is final


# ---------------------------------------------------------------------------
# T-PC-01: gross exposure cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_pc_01_gross_exposure_cap_rejects(
    fake_redis: FakeAsyncRedis,
) -> None:
    fake_redis.hashes["config:system"] = {"autonomy_mode": "COMMANDER"}
    # COMMANDER cap is 150% gross. Build positions that are already at 200%.
    big_pos = {
        "symbol": "ETH/USD", "quantity": 10.0,
        "current_price": 2_000.0, "avg_price": 2_000.0, "side": "LONG",
    }  # 20k notional on 10k portfolio = 200%
    fake_redis.kv["__snapshot__"] = _snapshot(
        portfolio_value=10_000.0, positions=[big_pos],
    )

    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    out = await constructor.analyze(_state())
    assert out["sized_order"] is None
    assert "gross_exposure_cap" in out["portfolio_construction_reasoning"]


# ---------------------------------------------------------------------------
# T-PC-02: per-symbol cap downsizes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_pc_02_per_symbol_cap_downsizes(
    fake_redis: FakeAsyncRedis,
) -> None:
    fake_redis.hashes["config:system"] = {"autonomy_mode": "COMMANDER"}
    # COMMANDER per-symbol cap is 10%. PV=$10000 → cap = $1000.
    # Existing position uses $700. Sizer would propose more than $300.
    existing = {
        "symbol": "BTC/USD", "quantity": 0.0117,
        "current_price": 60_000.0, "avg_price": 60_000.0, "side": "LONG",
    }  # ~$700 notional
    fake_redis.kv["__snapshot__"] = _snapshot(
        portfolio_value=10_000.0, positions=[existing],
    )

    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    out = await constructor.analyze(_state(confidence=1.0))
    assert out["sized_order"] is not None
    sized = out["sized_order"]
    # Headroom is $300; new notional must not exceed it.
    assert sized["notional"] <= 300.0 + 1e-3, sized


# ---------------------------------------------------------------------------
# Idempotency on cycle_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_constructor_idempotent_on_cycle_id(
    fake_redis: FakeAsyncRedis,
) -> None:
    fake_redis.kv["__snapshot__"] = _snapshot(portfolio_value=10_000.0)
    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    state = _state()
    out1 = await constructor.analyze(state)
    out2 = await constructor.analyze(state)
    assert out1["sized_order"] == out2["sized_order"]


# ---------------------------------------------------------------------------
# Shadow mode does not mutate state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_constructor_shadow_mode_does_not_mutate(
    fake_redis: FakeAsyncRedis,
) -> None:
    fake_redis.kv["__snapshot__"] = _snapshot(portfolio_value=10_000.0)
    fake_redis.kv[CONSTRUCTOR_FLAG] = "shadow"
    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    state = _state()
    out = await constructor.analyze(state)
    assert "sized_order" not in out  # shadow mode returns state unchanged
    # But the decision was still computed (cached for offline review).
    assert state["cycle_id"] in constructor._decision_cache


# ---------------------------------------------------------------------------
# BrokerUnavailableError → reject (don't crash the cycle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_constructor_broker_unavailable_rejects(
    fake_redis: FakeAsyncRedis,
) -> None:
    fake_redis.kv["__snapshot__"] = "RAISE"
    constructor = PortfolioConstructorAgent()
    constructor._decision_cache.clear()
    out = await constructor.analyze(_state())
    assert out["sized_order"] is None
    assert "broker_unavailable" in out["portfolio_construction_reasoning"]
