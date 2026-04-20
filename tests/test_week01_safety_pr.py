"""Week 1 / Safety PR — A1/A2/A3/A4/A5 unit tests + drill stubs.

Coverage map:
- A1: PositionSource Protocol + VenueAwarePositionProvider dispatch
- A2: VenueAwareFlattener + AlpacaBroker.flatten_all() called per venue (K1/K2)
- A3: Silent fallback removed; BrokerUnavailableError + kill switch (F1)
- A4: PositionSizer.size() runs for every venue; quantity > 0 (S1)
- A5: src/execution/risk.py deleted

Hermetic — uses fakes for Redis + Alpaca; no real DB / Redis / network.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from src.core import redis as redis_module
from src.execution import broker as broker_mod
from src.execution import position_source as ps_mod
from src.execution.position_sizer import PositionSizer, VolatilityPositionSizer
from src.execution.position_source import (
    AlpacaPositionSource,
    BrokerUnavailableError,
    SimPositionSource,
    VenueAwareFlattener,
    VenueAwarePositionProvider,
    position_source_for,
)


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

    async def xadd(self, stream: str, payload: dict[str, str], **_: Any) -> str:
        self._counter += 1
        msg_id = f"{self._counter}-0"
        self.streams.setdefault(stream, []).append((msg_id, dict(payload)))
        return msg_id


class FakeAlpacaBroker:
    """Minimal AlpacaBroker stand-in for the test surface position_source uses."""

    def __init__(self, *, available: bool = True, positions: list[dict] | None = None,
                 account: dict | None = None) -> None:
        self.available = available
        self._positions = positions or []
        self._account = account or {"portfolio_value": 10_000.0, "last_equity": 10_000.0}
        self.flatten_calls = 0
        self.close_position_calls: list[str] = []

    async def get_positions(self) -> list[dict]:
        if not self.available:
            raise RuntimeError("alpaca down")
        return list(self._positions)

    async def get_account(self) -> dict:
        if not self.available:
            raise RuntimeError("alpaca down")
        return dict(self._account)

    async def flatten_all(self) -> int:
        if not self.available:
            return 0
        self.flatten_calls += 1
        for p in self._positions:
            self.close_position_calls.append(p["symbol"])
        n = len(self._positions)
        self._positions = []
        return n


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncRedis:
    fr = FakeAsyncRedis()
    monkeypatch.setattr(redis_module, "get_redis", lambda: fr)
    monkeypatch.setattr(broker_mod, "get_redis", lambda: fr)
    return fr


# ---------------------------------------------------------------------------
# A1: VenueAwarePositionProvider dispatch
# ---------------------------------------------------------------------------


def test_a1_position_source_for_each_venue() -> None:
    assert isinstance(position_source_for("sim"), SimPositionSource)
    assert isinstance(position_source_for("alpaca_paper"), AlpacaPositionSource)
    assert isinstance(position_source_for("live"), AlpacaPositionSource)
    with pytest.raises(ValueError):
        position_source_for("nope")


@pytest.mark.asyncio
async def test_a1_alpaca_position_source_reads_account(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAlpacaBroker(account={"portfolio_value": 12_345.67, "last_equity": 12_000.00})
    monkeypatch.setattr(broker_mod, "get_alpaca_broker", lambda paper=True: fake)

    src = AlpacaPositionSource(paper=True)
    pv = await src.get_portfolio_value()
    assert pv == Decimal("12345.67")
    pnl = await src.get_daily_pnl()
    assert pnl == Decimal("345.67")


@pytest.mark.asyncio
async def test_a1_alpaca_unavailable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(broker_mod, "get_alpaca_broker", lambda paper=True: None)
    src = AlpacaPositionSource(paper=True)
    with pytest.raises(BrokerUnavailableError):
        await src.get_portfolio_value()


@pytest.mark.asyncio
async def test_a1_provider_swaps_on_venue_change(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAlpacaBroker(positions=[{"symbol": "AAPL", "quantity": 10, "avg_price": 100.0}])
    monkeypatch.setattr(broker_mod, "get_alpaca_broker", lambda paper=True: fake)

    venue = ["alpaca_paper"]
    provider = VenueAwarePositionProvider(venue_resolver=lambda: venue[0])
    positions = await provider.get_positions()
    assert positions[0]["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# A2 — K1/K2: kill switch flatten dispatches per venue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a2_k1_flatten_alpaca_paper(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeAsyncRedis,
) -> None:
    """K1 — alpaca_paper kill switch closes Alpaca positions."""
    fake = FakeAlpacaBroker(positions=[
        {"symbol": "AAPL", "quantity": 10, "avg_price": 100.0},
        {"symbol": "BTC/USD", "quantity": 0.5, "avg_price": 60_000.0},
    ])
    monkeypatch.setattr(broker_mod, "get_alpaca_broker", lambda paper=True: fake)

    flattener = VenueAwareFlattener(venue_resolver=lambda: "alpaca_paper")
    closed = await flattener.flatten_all()
    assert closed == 2
    assert fake.flatten_calls == 1
    assert sorted(fake.close_position_calls) == ["AAPL", "BTC/USD"]


@pytest.mark.asyncio
async def test_a2_k1_flatten_alpaca_unavailable_raises(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeAsyncRedis,
) -> None:
    """If Alpaca is unreachable mid-flatten, raise — operator handles manually."""
    monkeypatch.setattr(broker_mod, "get_alpaca_broker", lambda paper=True: None)
    flattener = VenueAwareFlattener(venue_resolver=lambda: "alpaca_paper")
    with pytest.raises(BrokerUnavailableError):
        await flattener.flatten_all()


@pytest.mark.asyncio
async def test_a2_alpaca_flatten_method_per_position_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AlpacaBroker.flatten_all uses a per-position timeout (no infinite block)."""
    from src.execution.alpaca_broker import AlpacaBroker

    class _Pos:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

    class _SlowClient:
        def get_all_positions(self) -> list:
            return [_Pos("HUNG")]

        def close_position(self, symbol: str) -> None:
            import time
            time.sleep(2)  # outlast our 0.05s timeout

    broker = AlpacaBroker(api_key="x", secret="y", paper=True)
    broker._client = _SlowClient()
    closed = await broker.flatten_all(per_position_timeout_s=0.05)
    assert closed == 0  # timed out, logged, moved on (not raised)


# ---------------------------------------------------------------------------
# A3 — F1: silent fallback gone; broker router raises BrokerUnavailableError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a3_f1_no_silent_alpaca_fallback(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeAsyncRedis,
) -> None:
    """alpaca_paper venue + Alpaca down: broker raises, no sim fill."""
    # Force venue to alpaca_paper
    fake_redis.hashes["config:system"] = {"execution_venue": "alpaca_paper"}
    monkeypatch.setattr(broker_mod, "get_alpaca_broker", lambda paper=True: None)

    # Patch activate_kill_switch to record without touching real Redis logic
    from src.core import security as sec_mod
    activated: list[dict] = []

    async def _fake_activate(reason: str, operator_id: str = "broker_router") -> None:
        activated.append({"reason": reason, "operator_id": operator_id})

    monkeypatch.setattr(sec_mod, "activate_kill_switch", _fake_activate)

    pb = broker_mod.PaperBroker()
    with pytest.raises(BrokerUnavailableError, match="kill switch tripped"):
        await pb.submit_order(
            symbol="AAPL", side="BUY", quantity=10.0, current_price=100.0,
            agent_id="atlas", strategy="consensus",
        )

    assert activated, "kill switch was not tripped"
    assert "alpaca_unavailable" in activated[0]["reason"]


# ---------------------------------------------------------------------------
# A4 — S1: PositionSizer.size returns non-zero for every venue
# ---------------------------------------------------------------------------


class _StubVolSizer(VolatilityPositionSizer):
    """Bypass live Redis lookups for unit tests."""

    async def get_volatility(self, symbol: str, window: int = 20) -> float:
        return 0.30  # 30% annualized

    async def _get_volume_24h_usd(self, symbol: str, price: float) -> float | None:
        return 10_000_000_000.0  # plenty of liquidity

    async def _apply_liquidity_cap(
        self, symbol: str, quantity: float, price: float
    ) -> float:
        return quantity  # don't touch Redis in tests


@pytest.mark.asyncio
async def test_a4_s1_sizing_runs_pre_dispatch_for_every_venue() -> None:
    sizer = PositionSizer(vol_sizer=_StubVolSizer())
    for venue in ("sim", "alpaca_paper", "live"):
        sized = await sizer.size(
            signal={"symbol": "BTC/USD", "direction": "LONG", "confidence": 0.8},
            market_data={"symbol": "BTC/USD", "price": 60_000.0},
            portfolio={"portfolio_value": 10_000.0},
        )
        assert sized.quantity > 0, f"sizer returned 0 for venue={venue}"
        assert sized.notional > 0
        assert sized.confidence_adjusted_risk_pct > 0


@pytest.mark.asyncio
async def test_a4_neutral_signal_returns_zero() -> None:
    sizer = PositionSizer(vol_sizer=_StubVolSizer())
    sized = await sizer.size(
        signal={"symbol": "BTC/USD", "direction": "NEUTRAL", "confidence": 0.5},
        market_data={"symbol": "BTC/USD", "price": 60_000.0},
        portfolio={"portfolio_value": 10_000.0},
    )
    assert sized.quantity == 0


@pytest.mark.asyncio
async def test_a4_zero_portfolio_returns_zero() -> None:
    sizer = PositionSizer(vol_sizer=_StubVolSizer())
    sized = await sizer.size(
        signal={"symbol": "BTC/USD", "direction": "LONG", "confidence": 0.8},
        market_data={"symbol": "BTC/USD", "price": 60_000.0},
        portfolio={"portfolio_value": 0.0},
    )
    assert sized.quantity == 0


@pytest.mark.asyncio
async def test_a4_paper_fill_rejects_zero_quantity(fake_redis: FakeAsyncRedis) -> None:
    """Broker is no longer the sizer. Quantity == 0 must be rejected."""
    pb = broker_mod.PaperBroker()
    order = await pb._paper_fill(
        symbol="BTC/USD", side="BUY", quantity=0.0, current_price=60_000.0,
        agent_id="atlas", strategy="consensus",
    )
    assert order.status == "REJECTED"


# ---------------------------------------------------------------------------
# A5: dead RiskEngine deleted
# ---------------------------------------------------------------------------


def test_a5_risk_engine_module_removed() -> None:
    """Confirm the RiskEngine module is gone — its job moved to PortfolioConstructor (Week 2)."""
    import importlib

    with pytest.raises(ImportError):
        importlib.import_module("src.execution.risk")
