"""Week 1 / Memory PR — unit tests T-CYCLE / T-VERSION / T-EPISODE.

Each test maps to a spec gate in week-01-tier0-safety-episodic.md. T-IMMUT-*
DB-bound tests live in tests/test_week01_immutability.py because they need a
live Postgres with the migration applied.

These tests use FakeAsyncRedis to keep them hermetic — no Redis, no Postgres,
no Anthropic.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.agents.base import AgentState, BaseAgent, EPISODE_EMISSION_FLAG
from src.agents.registry import assert_versions
from src.core import redis as redis_module
from src.core.cycle import compute_regime_fingerprint_stub, new_cycle_id
from src.core.versioning import (
    AGENT_VERSION_RE,
    compute_agent_version,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAsyncRedis:
    """In-memory async Redis stub. Implements only what BaseAgent + producer use."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self._counter = 0

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, **_: Any) -> bool:
        self.kv[key] = value
        return True

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

    async def hdel(self, key: str, *fields: str) -> int:
        bucket = self.hashes.get(key, {})
        removed = 0
        for f in fields:
            if f in bucket:
                del bucket[f]
                removed += 1
        return removed

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def xadd(self, stream: str, payload: dict[str, str], **_: Any) -> str:
        self._counter += 1
        msg_id = f"{self._counter}-0"
        self.streams.setdefault(stream, []).append((msg_id, dict(payload)))
        return msg_id


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncRedis:
    """Replace get_redis at every binding site BaseAgent / producer use.

    `from x import get_redis` binds the name into the importing module, so
    patching the source module is not enough — we have to patch each binding.
    """
    fr = FakeAsyncRedis()
    monkeypatch.setattr(redis_module, "get_redis", lambda: fr)
    from src.agents import base as base_mod
    from src.streams import producer as producer_mod
    monkeypatch.setattr(base_mod, "get_redis", lambda: fr)
    monkeypatch.setattr(producer_mod, "get_redis", lambda: fr)
    return fr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _OkAgent(BaseAgent):
    """Minimal agent that records calls + returns updated state."""

    def __init__(self, agent_id: str = "ok_agent") -> None:
        super().__init__(
            agent_id,
            agent_id,
            "TestRole",
            model_name="test-model",
            prompt_template="ok-skeleton-v1",
        )
        self.calls: list[AgentState] = []

    async def analyze(self, state: AgentState) -> AgentState:
        self.calls.append(state)
        out = dict(state)
        out["signals"] = list(state.get("signals", [])) + [
            {"agent": self.agent_id, "direction": "LONG", "confidence": 0.7}
        ]
        out["reasoning"] = f"{self.agent_id} reasoning"
        return out  # type: ignore[return-value]


class _BoomAgent(BaseAgent):
    """Agent that always raises — used to exercise the error episode path."""

    def __init__(self) -> None:
        super().__init__(
            "boom",
            "boom",
            "TestRole",
            model_name="test-model",
            prompt_template="boom-skeleton-v1",
        )

    async def analyze(self, state: AgentState) -> AgentState:
        raise RuntimeError("kapow")


def _initial_state(symbol: str = "TEST") -> AgentState:
    cycle_id = new_cycle_id()
    return {
        "cycle_id": cycle_id,
        "cycle_started_at": __import__("src.core.cycle", fromlist=["utcnow"]).utcnow(),
        "subsystem": "legacy",
        "regime_fingerprint": compute_regime_fingerprint_stub({"symbol": symbol}),
        "agent_id": "test",
        "agent_name": "Test",
        "messages": [],
        "market_data": {"symbol": symbol, "price": 100.0},
        "signals": [],
        "risk_approved": False,
        "final_decision": None,
        "confidence": 0.0,
        "reasoning": "",
    }


# ---------------------------------------------------------------------------
# T-CYCLE-01: run_trading_cycle generates a unique UUID v7 per invocation
# ---------------------------------------------------------------------------


def test_t_cycle_01_unique_per_invocation() -> None:
    ids = {new_cycle_id() for _ in range(1000)}
    assert len(ids) == 1000
    # UUIDv7 first hex char of the third group is "7"
    sample = next(iter(ids))
    assert sample[14] == "7", f"expected v7 marker, got {sample!r}"


# ---------------------------------------------------------------------------
# T-CYCLE-02: All agents in a cycle share the same cycle_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_cycle_02_shared_cycle_id_across_agents(fake_redis: FakeAsyncRedis) -> None:
    a, b, c = _OkAgent("a"), _OkAgent("b"), _OkAgent("c")
    state = _initial_state()
    cycle_id = state["cycle_id"]

    state = await a.analyze_with_heartbeat(state)
    state = await b.analyze_with_heartbeat(state)
    state = await c.analyze_with_heartbeat(state)

    # Cycle id propagates unchanged
    assert state["cycle_id"] == cycle_id

    # Every emitted episode carries the same cycle_id
    episodes = fake_redis.streams.get("stream:episodes", [])
    assert len(episodes) == 3
    assert {fields["cycle_id"] for _id, fields in episodes} == {cycle_id}


# ---------------------------------------------------------------------------
# T-VERSION-01: agent_version format matches {8hex}:{model}:{8hex}
# ---------------------------------------------------------------------------


def test_t_version_01_format() -> None:
    v = compute_agent_version("claude-opus-4-7", "any prompt")
    assert AGENT_VERSION_RE.match(v), f"bad version: {v!r}"


def test_t_version_01_model_name_normalization() -> None:
    # Spaces and slashes are normalized
    v = compute_agent_version("openai/gpt 4o", "p")
    assert AGENT_VERSION_RE.match(v)


def test_t_version_01_prompt_changes_change_version() -> None:
    a = compute_agent_version("m", "prompt-a")
    b = compute_agent_version("m", "prompt-b")
    assert a != b


# ---------------------------------------------------------------------------
# T-VERSION-02: Startup fails if any agent lacks a version
# ---------------------------------------------------------------------------


def test_t_version_02_startup_rejects_missing_version() -> None:
    bad = _OkAgent("bad")
    bad.agent_version = ""  # simulate a broken subclass
    with pytest.raises(RuntimeError, match="agent_version missing"):
        assert_versions([bad])


def test_t_version_02_startup_rejects_malformed_version() -> None:
    bad = _OkAgent("bad")
    bad.agent_version = "not-a-version"
    with pytest.raises(RuntimeError, match="agent_version missing or malformed"):
        assert_versions([bad])


def test_t_version_02_startup_accepts_valid_roster() -> None:
    good = _OkAgent("good")
    roster = assert_versions([good])
    assert roster == [good]


# ---------------------------------------------------------------------------
# T-EPISODE-01: Given a cycle, emitted episode count equals agent call count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_episode_01_count_matches_agent_calls(
    fake_redis: FakeAsyncRedis,
) -> None:
    agents = [_OkAgent(f"agent_{i}") for i in range(5)]
    state = _initial_state()
    for agent in agents:
        state = await agent.analyze_with_heartbeat(state)

    episodes = fake_redis.streams.get("stream:episodes", [])
    assert len(episodes) == len(agents)


# ---------------------------------------------------------------------------
# T-EPISODE-02: Episode payload contains required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_episode_02_payload_shape(fake_redis: FakeAsyncRedis) -> None:
    a = _OkAgent("a")
    await a.analyze_with_heartbeat(_initial_state())

    msg_id, fields = fake_redis.streams["stream:episodes"][0]
    for required in (
        "episode_id", "ts", "cycle_id", "cycle_started_at", "subsystem",
        "symbol", "agent_id", "agent_version", "market_snapshot",
        "input_state", "parsed_signal", "reasoning", "latency_ms",
        "regime_fingerprint",
    ):
        assert required in fields, f"missing field: {required}"

    # latency_ms is a stringified int >= 0
    assert int(fields["latency_ms"]) >= 0
    # parsed_signal is JSON-serialized list
    signals = json.loads(fields["parsed_signal"])
    assert isinstance(signals, list)
    assert any(s.get("agent") == "a" for s in signals)
    # agent_version matches the format regex
    assert AGENT_VERSION_RE.match(fields["agent_version"])


# ---------------------------------------------------------------------------
# T-EPISODE-03: Failed agent call emits an episode with error populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_episode_03_failed_call_emits_error_episode(
    fake_redis: FakeAsyncRedis,
) -> None:
    boom = _BoomAgent()
    with pytest.raises(RuntimeError):
        await boom.analyze_with_heartbeat(_initial_state())

    episodes = fake_redis.streams.get("stream:episodes", [])
    assert len(episodes) == 1
    _id, fields = episodes[0]
    assert "kapow" in fields["error"]
    # parsed_signal is the empty list (no updated_state because analyze raised)
    assert json.loads(fields["parsed_signal"]) == []


# ---------------------------------------------------------------------------
# Killswitch flag mutes emission without breaking the cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_killswitch_mutes_episode_emission(fake_redis: FakeAsyncRedis) -> None:
    fake_redis.kv[EPISODE_EMISSION_FLAG] = "false"
    a = _OkAgent("muted")
    await a.analyze_with_heartbeat(_initial_state())
    assert "stream:episodes" not in fake_redis.streams


# ---------------------------------------------------------------------------
# Missing cycle_id is loud but non-fatal (PRINCIPLE #6 surfaced via log)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_cycle_id_does_not_crash_cycle(
    fake_redis: FakeAsyncRedis,
) -> None:
    a = _OkAgent("nocycle")
    state = _initial_state()
    state.pop("cycle_id")  # type: ignore[misc]
    # Cycle still completes
    out = await a.analyze_with_heartbeat(state)
    assert out is not None
    # No episode emitted (we refused, on purpose)
    assert "stream:episodes" not in fake_redis.streams
