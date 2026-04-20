"""Week 1 / B3 — agent_episodes immutability drill (T-IMMUT-01/02/03).

Requires:
- Postgres reachable at settings.database_url
- alembic migrations applied through 002_agent_episodes
- TimescaleDB extension installed (the migration assumes it)

These tests are skipped automatically when the DB isn't reachable so CI in
stripped environments still passes. To run them locally:

    docker compose up -d postgres
    alembic upgrade head
    pytest tests/test_week01_immutability.py -v
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from src.core.config import settings
from src.core.versioning import compute_agent_version

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_session() -> AsyncSession:
    """Real Postgres session. Skips if DB unreachable.

    Function-scoped: asyncpg connections cannot be shared across pytest-asyncio
    event loops, so a fresh engine + session per test is the only safe pattern.
    """
    if os.environ.get("SKIP_DB_TESTS") == "1":
        pytest.skip("SKIP_DB_TESTS=1 set")
    engine = create_async_engine(settings.database_url, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"Postgres not reachable for immutability tests: {exc}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _ensure_table_present(session: AsyncSession) -> None:
    res = await session.execute(
        text("SELECT to_regclass('public.agent_episodes') AS t")
    )
    row = res.first()
    if row is None or row[0] is None:
        pytest.skip(
            "agent_episodes table not present — run `alembic upgrade head` first"
        )


def _episode_payload(cycle_id: str | None = None) -> dict:
    cid = cycle_id or str(uuid7())
    return {
        "episode_id": str(uuid7()),
        "ts": datetime.now(UTC),
        "cycle_id": cid,
        "cycle_started_at": datetime.now(UTC),
        "subsystem": "legacy",
        "symbol": "TEST",
        "agent_id": "test_agent",
        "agent_version": compute_agent_version("test-model", "skeleton-v1"),
        "market_snapshot": json.dumps({"symbol": "TEST", "price": 100.0}),
        "input_state": json.dumps({"k": "v"}),
        "prompt": None,
        "raw_response": None,
        "parsed_signal": json.dumps([]),
        "reasoning": None,
        "latency_ms": 10,
        "cost_usd": 0.0,
        "error": None,
        "regime_fingerprint": "stub-v1:TEST",
        "regime_tags": [],
    }


_INSERT = text(
    """
    INSERT INTO agent_episodes (
        episode_id, ts, cycle_id, cycle_started_at, subsystem, symbol,
        agent_id, agent_version, market_snapshot, input_state,
        prompt, raw_response, parsed_signal, reasoning,
        latency_ms, cost_usd, error,
        regime_fingerprint, regime_tags
    ) VALUES (
        :episode_id, :ts, :cycle_id, :cycle_started_at, :subsystem, :symbol,
        :agent_id, :agent_version, CAST(:market_snapshot AS JSONB), CAST(:input_state AS JSONB),
        :prompt, :raw_response, CAST(:parsed_signal AS JSONB), :reasoning,
        :latency_ms, :cost_usd, :error,
        :regime_fingerprint, :regime_tags
    )
    """
)


async def test_t_immut_03_insert_succeeds(db_session: AsyncSession) -> None:
    """Sanity: a well-formed payload can be inserted."""
    await _ensure_table_present(db_session)
    payload = _episode_payload()
    await db_session.execute(_INSERT, payload)
    await db_session.commit()

    res = await db_session.execute(
        text("SELECT episode_id FROM agent_episodes WHERE episode_id = :eid"),
        {"eid": payload["episode_id"]},
    )
    assert str(res.scalar_one()) == payload["episode_id"]


async def test_t_immut_01_update_is_rejected(db_session: AsyncSession) -> None:
    """The trigger must raise on UPDATE."""
    await _ensure_table_present(db_session)
    payload = _episode_payload()
    await db_session.execute(_INSERT, payload)
    await db_session.commit()

    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("UPDATE agent_episodes SET symbol = 'X' WHERE episode_id = :eid"),
            {"eid": payload["episode_id"]},
        )
        await db_session.commit()
    assert "immutable" in str(excinfo.value).lower()
    await db_session.rollback()


async def test_t_immut_02_delete_is_rejected(db_session: AsyncSession) -> None:
    """The trigger must raise on DELETE."""
    await _ensure_table_present(db_session)
    payload = _episode_payload()
    await db_session.execute(_INSERT, payload)
    await db_session.commit()

    with pytest.raises(DBAPIError) as excinfo:
        await db_session.execute(
            text("DELETE FROM agent_episodes WHERE episode_id = :eid"),
            {"eid": payload["episode_id"]},
        )
        await db_session.commit()
    assert "immutable" in str(excinfo.value).lower()
    await db_session.rollback()


async def test_agent_version_check_constraint(db_session: AsyncSession) -> None:
    """The CHECK constraint on agent_version must reject malformed values."""
    await _ensure_table_present(db_session)
    payload = _episode_payload()
    payload["agent_version"] = "not-a-version"
    with pytest.raises(DBAPIError):
        await db_session.execute(_INSERT, payload)
        await db_session.commit()
    await db_session.rollback()
