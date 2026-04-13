"""Broker — paper trading by default; switches to live ccxt when paper_trading=false.

Routing rules:
  - paper_trading=true (Redis config:system)  → PaperBroker for all assets
  - paper_trading=false, commodity symbol     → PaperBroker + warning (never real)
  - paper_trading=false, exchange=polymarket  → PaperBroker (Polymarket uses own HTTP client)
  - paper_trading=false, binance/coinbase/kraken → live ccxt order
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Literal

import ccxt.async_support as ccxt_async
import structlog

from src.streams.producer import produce, produce_audit
from src.streams import topology
from src.core.redis import get_redis
from src.execution.position_sizer import VolatilityPositionSizer

_sizer = VolatilityPositionSizer()
logger = structlog.get_logger()

OrderSide = Literal["BUY", "SELL"]
OrderStatus = Literal["PENDING", "FILLED", "CANCELLED", "REJECTED"]

# Commodity futures — always paper-only, real exchange trading not supported
_COMMODITY_SYMBOLS: frozenset[str] = frozenset({
    "GC=F", "CL=F", "SI=F", "HG=F", "NG=F", "ZW=F", "ZC=F", "ZS=F",
    "GC", "CL", "SI", "HG", "NG",
})
_SUPPORTED_LIVE_EXCHANGES: frozenset[str] = frozenset({"binance", "coinbase", "kraken"})


def _is_commodity(symbol: str) -> bool:
    """Return True for commodity futures — these never leave paper mode."""
    return symbol in _COMMODITY_SYMBOLS or symbol.endswith("=F")


async def _paper_trading_enabled() -> bool:
    """Read paper_trading flag from Redis hash config:system.
    Returns True (safe default) when the key is missing."""
    redis = get_redis()
    val: str | None = await redis.hget("config:system", "paper_trading")
    if val is None:
        return True
    return val.strip().lower() not in ("false", "0", "no")


async def _get_live_exchange(exchange_id: str) -> ccxt_async.Exchange | None:
    """Build an authenticated ccxt async exchange from credentials stored in Redis.

    Credentials live at Redis hash  config:exchange:{exchange_id}
    with fields: api_key, secret, passphrase (Coinbase), sandbox.
    Returns None when credentials are missing or the exchange is unsupported.
    """
    if exchange_id not in _SUPPORTED_LIVE_EXCHANGES:
        logger.warning("unsupported_live_exchange", exchange=exchange_id)
        return None

    redis = get_redis()
    creds: dict[str, str] = await redis.hgetall(f"config:exchange:{exchange_id}") or {}
    if not creds.get("api_key") or not creds.get("secret"):
        logger.warning("missing_exchange_credentials", exchange=exchange_id)
        return None

    params: dict[str, object] = {
        "apiKey": creds["api_key"],
        "secret": creds["secret"],
    }
    if creds.get("passphrase"):
        params["password"] = creds["passphrase"]
    if creds.get("sandbox", "").strip().lower() in ("true", "1", "yes"):
        params["sandbox"] = True

    exchange_cls = getattr(ccxt_async, exchange_id, None)
    if exchange_cls is None:
        logger.error("ccxt_exchange_class_not_found", exchange=exchange_id)
        return None
    return exchange_cls(params)  # type: ignore[no-any-return]


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: str  # MARKET, LIMIT
    limit_price: float | None
    status: OrderStatus
    filled_price: float | None
    created_at: datetime
    filled_at: datetime | None
    agent_id: str
    strategy: str
    exchange_id: str = "paper"
    live: bool = False

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id, "symbol": self.symbol, "side": self.side,
            "quantity": self.quantity, "order_type": self.order_type,
            "status": self.status, "filled_price": self.filled_price,
            "created_at": self.created_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "agent_id": self.agent_id, "strategy": self.strategy,
            "exchange_id": self.exchange_id, "live": self.live,
        }


@dataclass
class PaperBroker:
    """Simulate order execution with realistic slippage and commission."""
    slippage_pct: float = 0.0005
    commission_pct: float = 0.001
    _orders: list[Order] = field(default_factory=list)
    _positions: dict[str, dict] = field(default_factory=dict)
    _cash: float = 10000.0
    _initial_cash: float = 10000.0
    _daily_pnl: float = 0.0
    _trade_count: int = 0

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        current_price: float,
        agent_id: str = "system",
        strategy: str = "manual",
        stop_loss: float | None = None,
        take_profit: float | None = None,
        exchange_id: str = "binance",
    ) -> Order:
        """Route the order: live ccxt when enabled, paper otherwise."""
        paper = await _paper_trading_enabled()

        # Commodities always stay in paper mode
        if _is_commodity(symbol):
            if not paper:
                logger.warning(
                    "commodity_forced_paper_mode",
                    symbol=symbol,
                    msg="Commodity futures are paper-only; ignoring live trading flag.",
                )
            return await self._paper_fill(
                symbol, side, quantity, current_price,
                agent_id, strategy, stop_loss, take_profit,
            )

        # Polymarket uses its own HTTP client — keep paper here
        if exchange_id == "polymarket":
            return await self._paper_fill(
                symbol, side, quantity, current_price,
                agent_id, strategy, stop_loss, take_profit,
            )

        # Live path
        if not paper:
            exchange = await _get_live_exchange(exchange_id)
            if exchange is not None:
                return await self._live_fill(
                    exchange, symbol, side, quantity, agent_id, strategy, exchange_id,
                )
            logger.warning(
                "live_exchange_unavailable_fallback_paper",
                exchange=exchange_id, symbol=symbol,
            )

        # Default: paper simulation
        return await self._paper_fill(
            symbol, side, quantity, current_price,
            agent_id, strategy, stop_loss, take_profit,
        )


    async def _live_fill(
        self,
        exchange: ccxt_async.Exchange,
        symbol: str,
        side: OrderSide,
        quantity: float,
        agent_id: str,
        strategy: str,
        exchange_id: str,
    ) -> Order:
        """Submit a real market order via ccxt and return an Order record."""
        order_id = str(uuid.uuid4())[:8]
        ccxt_side = side.lower()  # ccxt uses "buy" / "sell"
        try:
            result = await exchange.create_order(symbol, "market", ccxt_side, quantity)
            filled_price = float(result.get("average") or result.get("price") or 0.0)
            status: OrderStatus = "FILLED"
            logger.info(
                "live_order_filled",
                order_id=order_id, symbol=symbol, side=side,
                price=filled_price, exchange=exchange_id, agent=agent_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "live_order_failed",
                order_id=order_id, symbol=symbol, exc=str(exc), exchange=exchange_id,
            )
            filled_price = 0.0
            status = "REJECTED"
        finally:
            await exchange.close()

        order = Order(
            order_id=order_id, symbol=symbol, side=side, quantity=quantity,
            order_type="MARKET", limit_price=None, status=status,
            filled_price=filled_price if filled_price else None,
            created_at=datetime.now(UTC), filled_at=datetime.now(UTC) if status == "FILLED" else None,
            agent_id=agent_id, strategy=strategy,
            exchange_id=exchange_id, live=True,
        )
        self._orders.append(order)
        redis = get_redis()
        await produce(topology.TRADES, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": str(quantity), "filled_price": str(filled_price),
            "agent_id": agent_id, "strategy": strategy,
            "exchange": exchange_id, "live": "true",
        }, redis=redis)
        await produce_audit("live_trade_executed", agent_id, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": quantity, "price": filled_price, "exchange": exchange_id,
        }, redis=redis)
        return order


    async def _paper_fill(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        current_price: float,
        agent_id: str,
        strategy: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Order:
        """Simulate fill with slippage and commission. Original paper logic."""
        order_id = str(uuid.uuid4())[:8]

        portfolio_value = self.get_portfolio_value({symbol: current_price})
        vol_quantity = await _sizer.calculate_size(
            symbol, portfolio_value, {symbol: current_price}
        )
        if vol_quantity > 0:
            quantity = vol_quantity

        slip = current_price * self.slippage_pct
        filled_price = current_price + slip if side == "BUY" else current_price - slip
        commission = filled_price * quantity * self.commission_pct

        if side == "BUY":
            cost = filled_price * quantity + commission
            if cost > self._cash:
                quantity = (self._cash * 0.95) / (filled_price * (1 + self.commission_pct))
                commission = filled_price * quantity * self.commission_pct
                cost = filled_price * quantity + commission
            self._cash -= cost
            self._positions[symbol] = {
                "symbol": symbol, "quantity": quantity,
                "avg_price": filled_price, "side": "LONG",
                "entry_time": datetime.now(UTC).isoformat(),
                "stop_loss": stop_loss, "take_profit": take_profit,
                "trailing_stop": None,
            }
        else:
            proceeds = filled_price * quantity - commission
            self._cash += proceeds
            pnl = proceeds - (
                self._positions.get(symbol, {}).get("avg_price", filled_price) * quantity
            )
            self._daily_pnl += pnl
            self._positions.pop(symbol, None)

        order = Order(
            order_id=order_id, symbol=symbol, side=side, quantity=quantity,
            order_type="MARKET", limit_price=None, status="FILLED",
            filled_price=filled_price, created_at=datetime.now(UTC),
            filled_at=datetime.now(UTC), agent_id=agent_id, strategy=strategy,
            exchange_id="paper", live=False,
        )
        self._orders.append(order)
        self._trade_count += 1
        redis = get_redis()
        await produce(topology.TRADES, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": str(quantity), "filled_price": str(filled_price),
            "commission": str(commission), "agent_id": agent_id, "strategy": strategy,
        }, redis=redis)
        await produce_audit("trade_executed", agent_id, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": quantity, "price": filled_price,
        }, redis=redis)
        logger.info("paper_order_filled", order_id=order_id, symbol=symbol,
                    side=side, price=filled_price, agent=agent_id)
        return order


    def get_positions(self) -> list[dict]:
        return list(self._positions.values())

    def get_orders(self, limit: int = 100) -> list[Order]:
        return self._orders[-limit:]

    def get_portfolio_value(self, current_prices: dict[str, float] | None = None) -> float:
        prices = current_prices or {}
        position_value = sum(
            pos["quantity"] * prices.get(pos["symbol"], pos["avg_price"])
            for pos in self._positions.values()
        )
        return self._cash + position_value

    def flatten_all(self, current_prices: dict[str, float] | None = None) -> None:
        """Emergency: mark all positions closed at last known price."""
        prices = current_prices or {}
        for symbol, pos in list(self._positions.items()):
            price = prices.get(symbol, pos["avg_price"])
            proceeds = pos["quantity"] * price * (1 - self.commission_pct)
            self._cash += proceeds
            logger.warning("position_flattened", symbol=symbol, price=price)
        self._positions.clear()


# Module-level singleton
paper_broker = PaperBroker()
