"""Alpaca broker — live equity orders via alpaca-py SDK.

Routing note: this broker handles US equities (SPY/QQQ/NVDA/etc.). The ccxt
path in src.execution.broker continues to own crypto venues. The PaperBroker
still simulates everything in paper mode.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from src.core.redis import get_redis
from src.execution.broker import Order, OrderSide
from src.streams import topology
from src.streams.producer import produce, produce_audit

logger = structlog.get_logger()

_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_LIVE_BASE_URL = "https://api.alpaca.markets"


def _paper_flag_from_env() -> bool:
    value = os.getenv("ALPACA_PAPER_TRADE", "true")
    return str(value).strip().lower() not in ("false", "0", "no")


class AlpacaBroker:
    """Thin wrapper over ``alpaca.trading.client.TradingClient``.

    Alpaca SDK calls are synchronous; we offload them to a thread with
    ``asyncio.to_thread`` so the scheduler / API event loops stay responsive.
    All exceptions are caught, logged, and surfaced as REJECTED Orders.
    """

    def __init__(
        self,
        api_key: str,
        secret: str,
        paper: bool | None = None,
    ) -> None:
        self.api_key = api_key
        self.secret = secret
        self.paper = _paper_flag_from_env() if paper is None else paper
        self.base_url = _PAPER_BASE_URL if self.paper else _LIVE_BASE_URL
        self._client: Any = None

    # ------------------------------------------------------------------
    # Client bootstrap
    # ------------------------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from alpaca.trading.client import TradingClient

            self._client = TradingClient(
                api_key=self.api_key,
                secret_key=self.secret,
                paper=self.paper,
            )
        except ImportError:
            logger.error("alpaca_py_not_installed", msg="pip install alpaca-py")
            self._client = None
        except Exception as exc:  # noqa: BLE001
            logger.error("alpaca_client_init_failed", error=str(exc))
            self._client = None
        return self._client

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: str = "market",
        limit_price: float | None = None,
        agent_id: str = "system",
        strategy: str = "manual",
    ) -> Order:
        order_id = str(uuid.uuid4())[:8]
        created_at = datetime.now(UTC)
        client = self._get_client()

        if client is None:
            return _rejected(order_id, symbol, side, quantity, order_type,
                             limit_price, agent_id, strategy, created_at,
                             reason="client_unavailable")

        try:
            from alpaca.trading.enums import OrderSide as AlpacaSide
            from alpaca.trading.enums import TimeInForce
            from alpaca.trading.requests import (
                LimitOrderRequest,
                MarketOrderRequest,
            )

            alpaca_side = AlpacaSide.BUY if side == "BUY" else AlpacaSide.SELL
            tif = TimeInForce.DAY

            if order_type.lower() == "limit" and limit_price is not None:
                request = LimitOrderRequest(
                    symbol=symbol, qty=quantity, side=alpaca_side,
                    time_in_force=tif, limit_price=limit_price,
                )
            else:
                request = MarketOrderRequest(
                    symbol=symbol, qty=quantity, side=alpaca_side,
                    time_in_force=tif,
                )

            result = await _to_thread(client.submit_order, request)
            filled_price = _extract_filled_price(result)
            status = "FILLED" if filled_price else "PENDING"
            filled_at = datetime.now(UTC) if status == "FILLED" else None

            order = Order(
                order_id=order_id, symbol=symbol, side=side,
                quantity=quantity, order_type=order_type.upper(),
                limit_price=limit_price, status=status,
                filled_price=filled_price, created_at=created_at,
                filled_at=filled_at, agent_id=agent_id, strategy=strategy,
                exchange_id="alpaca", live=True,
            )
            await _emit_trade_audit(order, filled_price or 0.0)
            logger.info(
                "alpaca_order_submitted",
                order_id=order_id, symbol=symbol, side=side,
                qty=quantity, status=status, paper=self.paper,
            )
            return order
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "alpaca_order_failed",
                order_id=order_id, symbol=symbol, error=str(exc),
            )
            return _rejected(order_id, symbol, side, quantity, order_type,
                             limit_price, agent_id, strategy, created_at,
                             reason=str(exc))

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------
    async def get_positions(self) -> list[dict]:
        client = self._get_client()
        if client is None:
            return []
        try:
            raw = await _to_thread(client.get_all_positions)
            return [_position_to_dict(p) for p in raw]
        except Exception as exc:  # noqa: BLE001
            logger.error("alpaca_positions_failed", error=str(exc))
            return []

    async def get_account(self) -> dict:
        client = self._get_client()
        if client is None:
            return {}
        try:
            raw = await _to_thread(client.get_account)
            return _account_to_dict(raw)
        except Exception as exc:  # noqa: BLE001
            logger.error("alpaca_account_failed", error=str(exc))
            return {}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
async def _to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking callable in the default thread pool."""
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)


def _extract_filled_price(result: Any) -> float | None:
    for attr in ("filled_avg_price", "limit_price", "avg_price"):
        val = getattr(result, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _position_to_dict(pos: Any) -> dict:
    return {
        "symbol": getattr(pos, "symbol", ""),
        "quantity": float(getattr(pos, "qty", 0) or 0),
        "avg_price": float(getattr(pos, "avg_entry_price", 0) or 0),
        "market_value": float(getattr(pos, "market_value", 0) or 0),
        "unrealized_pl": float(getattr(pos, "unrealized_pl", 0) or 0),
        "side": getattr(pos, "side", "LONG"),
    }


def _account_to_dict(acct: Any) -> dict:
    return {
        "cash": float(getattr(acct, "cash", 0) or 0),
        "equity": float(getattr(acct, "equity", 0) or 0),
        "buying_power": float(getattr(acct, "buying_power", 0) or 0),
        "portfolio_value": float(getattr(acct, "portfolio_value", 0) or 0),
        "status": getattr(acct, "status", "UNKNOWN"),
    }


def _rejected(
    order_id: str, symbol: str, side: OrderSide, quantity: float,
    order_type: str, limit_price: float | None,
    agent_id: str, strategy: str, created_at: datetime,
    reason: str,
) -> Order:
    logger.warning(
        "alpaca_order_rejected",
        order_id=order_id, symbol=symbol, reason=reason,
    )
    return Order(
        order_id=order_id, symbol=symbol, side=side, quantity=quantity,
        order_type=order_type.upper(), limit_price=limit_price,
        status="REJECTED", filled_price=None,
        created_at=created_at, filled_at=None,
        agent_id=agent_id, strategy=strategy,
        exchange_id="alpaca", live=True,
    )


async def _emit_trade_audit(order: Order, filled_price: float) -> None:
    redis = get_redis()
    await produce(topology.TRADES, {
        "order_id": order.order_id, "symbol": order.symbol, "side": order.side,
        "quantity": str(order.quantity), "filled_price": str(filled_price),
        "agent_id": order.agent_id, "strategy": order.strategy,
        "exchange": "alpaca", "live": "true",
    }, redis=redis)
    await produce_audit("live_trade_executed", order.agent_id, {
        "order_id": order.order_id, "symbol": order.symbol, "side": order.side,
        "quantity": order.quantity, "price": filled_price, "exchange": "alpaca",
    }, redis=redis)
