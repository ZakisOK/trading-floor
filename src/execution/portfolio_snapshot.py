"""PortfolioSnapshot — frozen point-in-time portfolio view (Week 2 / A4).

Single source of truth for portfolio state in the signal path. Built from
the venue-aware PositionProvider (Week 1 / A1) so it always reflects the
real book at the active venue.

Cached for 5 seconds: a fresh cycle every few seconds doesn't need to hit
Alpaca's get_account on every call. The cache is keyed on the venue so
flipping venue invalidates it automatically.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog

from src.execution.position_source import (
    BrokerUnavailableError,
    position_provider,
)

logger = structlog.get_logger()

_CACHE_TTL_S = 5.0


@dataclass(frozen=True)
class PortfolioSnapshot:
    venue: str
    portfolio_value: Decimal
    daily_pnl: Decimal
    positions: tuple[dict[str, Any], ...]
    gross_exposure: Decimal
    net_exposure: Decimal
    correlation_matrix: dict[str, float] = field(default_factory=dict)
    captured_at: float = 0.0

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def position_for(self, symbol: str) -> dict[str, Any] | None:
        for p in self.positions:
            if p.get("symbol") == symbol:
                return p
        return None


_cache: dict[str, tuple[float, PortfolioSnapshot]] = {}


def _compute_exposures(
    positions: list[dict[str, Any]],
    portfolio_value: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return (gross, net) exposure as absolute USD values.

    gross = sum(|notional|), net = sum(signed notional). Both as Decimal so
    downstream cap comparisons are exact.
    """
    gross = Decimal("0")
    net = Decimal("0")
    for p in positions:
        qty = Decimal(str(p.get("quantity", 0) or 0))
        price = Decimal(str(p.get("current_price", p.get("avg_price", 0)) or 0))
        notional = qty * price
        side = str(p.get("side", "LONG")).upper()
        signed = notional if side == "LONG" else -notional
        gross += abs(notional)
        net += signed
    return gross, net


async def _read_correlation_matrix() -> dict[str, float]:
    """Read latest correlation matrix from Redis. Empty dict if unavailable.

    The correlation_computer service writes ``portfolio:correlation_matrix``
    nightly. If empty, the constructor falls back to "treat as independent"
    behavior (no correlation downsizing).
    """
    try:
        from src.core.redis import get_redis

        redis = get_redis()
        raw = await redis.hgetall("portfolio:correlation_matrix")
    except Exception:  # noqa: BLE001 - never block the snapshot on Redis hiccup
        return {}
    if not raw:
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return out


async def get_portfolio_snapshot(
    *,
    current_prices: dict[str, float] | None = None,
    force_refresh: bool = False,
) -> PortfolioSnapshot:
    """Return a fresh-or-cached PortfolioSnapshot for the active venue.

    Raises BrokerUnavailableError if the venue is Alpaca and the broker
    can't be reached. Callers in the signal path should catch this and
    refuse to size — never substitute stale data when the venue is hot.
    """
    from src.execution.broker import get_execution_venue

    venue = await get_execution_venue()
    now = time.monotonic()
    cached = _cache.get(venue)
    if cached and not force_refresh and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]

    try:
        positions = await position_provider.get_positions()
    except BrokerUnavailableError:
        # Don't cache failures — the caller MUST see a fresh exception on
        # the next call so the kill-switch path still trips.
        raise

    portfolio_value = await position_provider.get_portfolio_value(current_prices)
    daily_pnl = await position_provider.get_daily_pnl()

    # Backfill current_price into positions if caller passed prices
    if current_prices:
        positions = [
            {**p, "current_price": current_prices.get(p["symbol"], p.get("current_price", p.get("avg_price")))}
            for p in positions
        ]

    gross, net = _compute_exposures(positions, portfolio_value)
    matrix = await _read_correlation_matrix()

    snapshot = PortfolioSnapshot(
        venue=venue,
        portfolio_value=portfolio_value,
        daily_pnl=daily_pnl,
        positions=tuple(positions),
        gross_exposure=gross,
        net_exposure=net,
        correlation_matrix=matrix,
        captured_at=now,
    )
    _cache[venue] = (now, snapshot)
    return snapshot


def invalidate_cache(venue: str | None = None) -> None:
    """Drop the cached snapshot. Used by tests; rarely needed in prod."""
    if venue is None:
        _cache.clear()
    else:
        _cache.pop(venue, None)
