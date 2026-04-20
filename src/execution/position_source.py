"""Venue-aware position + portfolio metrics (Week 1 / A1 + A2).

The risk monitor and kill switch must read positions from the venue that
actually holds them. In ``alpaca_paper`` mode, the paper_broker singleton is
empty (or stale) — the real positions live at Alpaca. Reading from the wrong
book is the bug A1 closes.

This module gives the rest of the codebase three things:

1. ``PositionSource`` Protocol: the read surface for positions / portfolio
   value / day P&L.
2. ``SimPositionSource`` and ``AlpacaPositionSource``: per-venue impls.
3. ``VenueAwarePositionProvider`` and ``VenueAwareFlattener``: the read /
   write dispatchers callers actually use.

Spec: ``trading-floor-plan/weeks/week-01-tier0-safety-episodic.md`` A1, A2.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

import structlog

from src.core.redis import get_redis

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PositionSource(Protocol):
    """Read-side abstraction for positions + portfolio metrics.

    Implementations MUST be safe to call from any number of concurrent
    coroutines. They MUST NOT silently downgrade between venues — return
    empty/zero on failure and let the caller decide what to do.
    """

    async def get_positions(self) -> list[dict[str, Any]]: ...
    async def get_portfolio_value(
        self, current_prices: dict[str, float] | None = None
    ) -> Decimal: ...
    async def get_daily_pnl(self) -> Decimal: ...


# ---------------------------------------------------------------------------
# Sim impl — wraps paper_broker (which already does Redis-backed bookkeeping)
# ---------------------------------------------------------------------------


@dataclass
class SimPositionSource:
    """Wraps ``paper_broker`` for the local sim venue."""

    async def get_positions(self) -> list[dict[str, Any]]:
        from src.execution.broker import paper_broker

        return await paper_broker.get_positions()

    async def get_portfolio_value(
        self, current_prices: dict[str, float] | None = None
    ) -> Decimal:
        from src.execution.broker import paper_broker

        value = await paper_broker.get_portfolio_value(current_prices)
        return Decimal(str(value))

    async def get_daily_pnl(self) -> Decimal:
        from src.execution.broker import paper_broker

        value = await paper_broker.get_daily_pnl()
        return Decimal(str(value))


# ---------------------------------------------------------------------------
# Alpaca impl — wraps AlpacaBroker.get_all_positions + get_account
# ---------------------------------------------------------------------------


@dataclass
class AlpacaPositionSource:
    """Wraps the AlpacaBroker singleton for ``alpaca_paper`` and ``live``."""

    paper: bool = True

    async def _broker(self) -> Any:
        from src.execution.broker import get_alpaca_broker

        broker = get_alpaca_broker(paper=self.paper)
        if broker is None:
            # PRINCIPLE #3: no silent fallback. The caller must decide what
            # "Alpaca says nothing" means — typically: trip the kill switch
            # and refuse the next order.
            raise BrokerUnavailableError(
                f"Alpaca broker unavailable for paper={self.paper}"
            )
        return broker

    async def get_positions(self) -> list[dict[str, Any]]:
        broker = await self._broker()
        return await broker.get_positions()

    async def get_portfolio_value(
        self, current_prices: dict[str, float] | None = None
    ) -> Decimal:
        broker = await self._broker()
        account = await broker.get_account()
        # Alpaca account endpoint exposes portfolio_value directly; fall back to
        # equity if the SDK shape changes upstream.
        value = account.get("portfolio_value") or account.get("equity") or 0.0
        return Decimal(str(value))

    async def get_daily_pnl(self) -> Decimal:
        """Day P&L = portfolio_value - last_equity (yesterday's close)."""
        broker = await self._broker()
        account = await broker.get_account()
        portfolio_value = Decimal(str(account.get("portfolio_value") or 0))
        last_equity = Decimal(str(account.get("last_equity") or 0))
        return portfolio_value - last_equity


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BrokerUnavailableError(RuntimeError):
    """Raised when the active venue's broker can't be reached.

    Distinct from generic RuntimeError so the kill-switch path can detect it
    cleanly and surface a structured ``reason``.
    """


# ---------------------------------------------------------------------------
# Venue-aware dispatcher (read)
# ---------------------------------------------------------------------------


def position_source_for(venue: str) -> PositionSource:
    """Build the source matching a venue. No I/O — cheap to call repeatedly."""
    if venue == "sim":
        return SimPositionSource()
    if venue == "alpaca_paper":
        return AlpacaPositionSource(paper=True)
    if venue == "live":
        return AlpacaPositionSource(paper=False)
    raise ValueError(f"unknown venue: {venue!r}")


@dataclass
class VenueAwarePositionProvider:
    """Reads ``config:system.execution_venue`` from Redis on every call.

    Hot-swappable: an operator changing the venue at runtime takes effect on
    the next read. Tests can override the default by passing
    ``venue_resolver``.
    """

    venue_resolver: Any | None = None

    async def _venue(self) -> str:
        if self.venue_resolver is not None:
            result = self.venue_resolver()
            if asyncio.iscoroutine(result):
                return await result
            return result
        # Local import to avoid the import cycle through src.execution.broker
        from src.execution.broker import get_execution_venue

        return await get_execution_venue()

    async def source(self) -> PositionSource:
        return position_source_for(await self._venue())

    async def get_positions(self) -> list[dict[str, Any]]:
        src = await self.source()
        return await src.get_positions()

    async def get_portfolio_value(
        self, current_prices: dict[str, float] | None = None
    ) -> Decimal:
        src = await self.source()
        return await src.get_portfolio_value(current_prices)

    async def get_daily_pnl(self) -> Decimal:
        src = await self.source()
        return await src.get_daily_pnl()


# ---------------------------------------------------------------------------
# Venue-aware flatten (write — kill switch)
# ---------------------------------------------------------------------------


@dataclass
class VenueAwareFlattener:
    """Routes ``flatten_all()`` to the venue currently in effect.

    Used by the kill switch path. Returns the count of positions closed (best
    effort — partial failures are logged, not raised, because the kill switch
    must keep going).
    """

    venue_resolver: Any | None = None

    async def _venue(self) -> str:
        if self.venue_resolver is not None:
            result = self.venue_resolver()
            if asyncio.iscoroutine(result):
                return await result
            return result
        from src.execution.broker import get_execution_venue

        return await get_execution_venue()

    async def flatten_all(
        self, current_prices: dict[str, float] | None = None
    ) -> int:
        venue = await self._venue()
        if venue == "sim":
            from src.execution.broker import paper_broker

            positions = await paper_broker.get_positions()
            count = len(positions)
            await paper_broker.flatten_all(current_prices=current_prices)
            logger.critical(
                "kill_switch_flatten_completed", venue=venue, count=count
            )
            return count
        if venue in ("alpaca_paper", "live"):
            from src.execution.broker import get_alpaca_broker

            broker = get_alpaca_broker(paper=(venue != "live"))
            if broker is None:
                logger.critical(
                    "kill_switch_alpaca_unavailable",
                    venue=venue,
                    msg="cannot flatten — operator must close Alpaca positions manually",
                )
                raise BrokerUnavailableError(
                    f"Alpaca broker unavailable during kill switch flatten ({venue})"
                )
            count = await broker.flatten_all()
            logger.critical(
                "kill_switch_flatten_completed", venue=venue, count=count
            )
            return count
        raise ValueError(f"unknown venue: {venue!r}")


# Singletons. Cheap to share — they hold no state.
position_provider = VenueAwarePositionProvider()
position_flattener = VenueAwareFlattener()


__all__ = [
    "AlpacaPositionSource",
    "BrokerUnavailableError",
    "PositionSource",
    "SimPositionSource",
    "VenueAwareFlattener",
    "VenueAwarePositionProvider",
    "position_flattener",
    "position_provider",
    "position_source_for",
]
