"""Alpaca broker — live equity + crypto orders via alpaca-py SDK.

Handles US equities (SPY/QQQ/NVDA) and Alpaca-supported crypto pairs
(BTC/USD, ETH/USD, SOL/USD...). Equity orders use TimeInForce.DAY,
crypto orders use GTC (Alpaca requires GTC for crypto).

Symbols arriving as `BTC/USDT` (the codebase's default crypto format) are
translated to `BTC/USD` for Alpaca. Alpaca only quotes against USD.
"""
from __future__ import annotations

import os
import re
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

_EQUITY_RE = re.compile(r"^[A-Z]{1,5}$")
_CRYPTO_PAIR_RE = re.compile(r"^([A-Z]{2,8})[/-]([A-Z]{3,5})$")
# Alpaca-supported crypto quote currencies. Orders denominated in USDT/USDC
# are rewritten to USD since that's what Alpaca quotes against.
_ALPACA_CRYPTO_QUOTES = {"USD", "USDT", "USDC", "USDP"}


def _paper_flag_from_env() -> bool:
    value = os.getenv("ALPACA_PAPER_TRADE", "true")
    return str(value).strip().lower() not in ("false", "0", "no")


def is_alpaca_equity_symbol(symbol: str) -> bool:
    """True for bare US-equity tickers (SPY, QQQ, AAPL)."""
    if not symbol or "/" in symbol or "=" in symbol or "-" in symbol:
        return False
    return bool(_EQUITY_RE.match(symbol))


def is_alpaca_crypto_symbol(symbol: str) -> bool:
    """True for pairs Alpaca can route (BTC/USD, ETH/USDT, SOL-USD)."""
    if not symbol:
        return False
    match = _CRYPTO_PAIR_RE.match(symbol.upper())
    if match is None:
        return False
    return match.group(2) in _ALPACA_CRYPTO_QUOTES


def to_alpaca_symbol(symbol: str) -> str:
    """Normalize a pair to Alpaca's format: BASE/USD.

    `BTC/USDT` -> `BTC/USD`, `SOL-USD` -> `SOL/USD`, `AAPL` -> `AAPL`.
    """
    if not symbol:
        return symbol
    upper = symbol.upper()
    match = _CRYPTO_PAIR_RE.match(upper)
    if match is None:
        return upper
    base = match.group(1)
    return f"{base}/USD"


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
        alpaca_symbol = to_alpaca_symbol(symbol)
        is_crypto = is_alpaca_crypto_symbol(symbol)

        if client is None:
            return _rejected(order_id, alpaca_symbol, side, quantity, order_type,
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
            # Crypto must use GTC; equities use DAY so unfilled orders expire at close
            tif = TimeInForce.GTC if is_crypto else TimeInForce.DAY

            if order_type.lower() == "limit" and limit_price is not None:
                request = LimitOrderRequest(
                    symbol=alpaca_symbol, qty=quantity, side=alpaca_side,
                    time_in_force=tif, limit_price=limit_price,
                )
            else:
                request = MarketOrderRequest(
                    symbol=alpaca_symbol, qty=quantity, side=alpaca_side,
                    time_in_force=tif,
                )

            result = await _to_thread(client.submit_order, request)
            filled_price = _extract_filled_price(result)
            # Equities typically return PENDING and fill asynchronously; crypto
            # usually fills immediately. Either way the reconciler in
            # position_monitor will confirm via get_orders/get_positions.
            alpaca_status = (getattr(result, "status", "") or "").lower()
            status = "FILLED" if filled_price and "fill" in alpaca_status else "PENDING"
            if not filled_price and alpaca_status in ("rejected", "canceled"):
                status = "REJECTED"
            filled_at = datetime.now(UTC) if status == "FILLED" else None

            order = Order(
                order_id=order_id, symbol=alpaca_symbol, side=side,
                quantity=quantity, order_type=order_type.upper(),
                limit_price=limit_price, status=status,
                filled_price=filled_price, created_at=created_at,
                filled_at=filled_at, agent_id=agent_id, strategy=strategy,
                exchange_id="alpaca", live=True,
            )
            await _emit_trade_audit(order, filled_price or 0.0)
            logger.info(
                "alpaca_order_submitted",
                order_id=order_id, alpaca_order_id=getattr(result, "id", None),
                symbol=alpaca_symbol, side=side, qty=quantity,
                status=status, alpaca_status=alpaca_status,
                paper=self.paper, asset_class="crypto" if is_crypto else "equity",
            )
            return order
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "alpaca_order_failed",
                order_id=order_id, symbol=alpaca_symbol, error=str(exc),
            )
            return _rejected(order_id, alpaca_symbol, side, quantity, order_type,
                             limit_price, agent_id, strategy, created_at,
                             reason=str(exc))

    # ------------------------------------------------------------------
    # Read paths — used by the unified account view in Mission Control
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

    async def get_orders(self, limit: int = 100, status: str = "all") -> list[dict]:
        """Return recent Alpaca orders as plain dicts ready for the MC feed."""
        client = self._get_client()
        if client is None:
            return []
        try:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest

            status_map = {
                "open": QueryOrderStatus.OPEN,
                "closed": QueryOrderStatus.CLOSED,
                "all": QueryOrderStatus.ALL,
            }
            req = GetOrdersRequest(
                status=status_map.get(status, QueryOrderStatus.ALL),
                limit=max(1, min(int(limit), 500)),
            )
            raw = await _to_thread(client.get_orders, filter=req)
            return [_order_to_dict(o) for o in raw]
        except Exception as exc:  # noqa: BLE001
            logger.error("alpaca_orders_failed", error=str(exc))
            return []


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
    qty = float(getattr(pos, "qty", 0) or 0)
    avg_price = float(getattr(pos, "avg_entry_price", 0) or 0)
    market_value = float(getattr(pos, "market_value", 0) or 0)
    unrealized = float(getattr(pos, "unrealized_pl", 0) or 0)
    current_price = float(getattr(pos, "current_price", 0) or 0) or (
        market_value / qty if qty else avg_price
    )
    side_raw = getattr(pos, "side", "long")
    side = str(side_raw.value if hasattr(side_raw, "value") else side_raw).upper()
    return {
        "symbol": getattr(pos, "symbol", ""),
        "quantity": qty,
        "size": qty,
        "avg_price": avg_price,
        "entry_price": avg_price,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": round(unrealized, 4),
        "unrealized_pnl_pct": round(unrealized / (avg_price * qty), 6) if qty and avg_price else 0.0,
        "side": "LONG" if side == "LONG" else "SHORT",
        "asset_class": getattr(pos, "asset_class", None),
        "exchange": "alpaca",
    }


def _account_to_dict(acct: Any) -> dict:
    return {
        "cash": float(getattr(acct, "cash", 0) or 0),
        "equity": float(getattr(acct, "equity", 0) or 0),
        "buying_power": float(getattr(acct, "buying_power", 0) or 0),
        "portfolio_value": float(getattr(acct, "portfolio_value", 0) or 0),
        "status": getattr(acct, "status", "UNKNOWN"),
        "last_equity": float(getattr(acct, "last_equity", 0) or 0),
        "crypto_status": getattr(acct, "crypto_status", None),
    }


def _order_to_dict(order: Any) -> dict:
    """Shape an Alpaca Order object for the MC feed."""
    def _iso(val: Any) -> str | None:
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    status_raw = getattr(order, "status", "")
    status = str(status_raw.value if hasattr(status_raw, "value") else status_raw).upper()
    side_raw = getattr(order, "side", "")
    side = str(side_raw.value if hasattr(side_raw, "value") else side_raw).upper()

    return {
        "order_id": str(getattr(order, "id", "")),
        "client_order_id": getattr(order, "client_order_id", ""),
        "symbol": getattr(order, "symbol", ""),
        "side": side,
        "quantity": float(getattr(order, "qty", 0) or 0),
        "filled_quantity": float(getattr(order, "filled_qty", 0) or 0),
        "filled_price": float(getattr(order, "filled_avg_price", 0) or 0) or None,
        "status": status,
        "order_type": str(getattr(order, "order_type", "") or "").upper(),
        "created_at": _iso(getattr(order, "created_at", None)),
        "filled_at": _iso(getattr(order, "filled_at", None)),
        "exchange_id": "alpaca",
        "live": True,
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
