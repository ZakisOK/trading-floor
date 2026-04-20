"""Broker — venue-aware order routing.

Execution venue is read from Redis  config:system.execution_venue  with three values:
  - sim          → local PaperBroker simulation (Redis-backed paper:* keys)
  - alpaca_paper → AlpacaBroker with paper=True (hits paper-api.alpaca.markets)
  - live         → AlpacaBroker with paper=False; ccxt venues still available for
                   binance/coinbase/kraken when exchange_id is set explicitly

Routing within a non-sim venue:
  - equity ticker or exchange_id=="alpaca" → AlpacaBroker
  - Alpaca-supported crypto pair (BTC/USD, ETH/USD, SOL/USD…) → AlpacaBroker
  - commodity futures (GC=F, CL=F…)      → PaperBroker (Alpaca has no futures)
  - exchange_id=="polymarket"            → PaperBroker (own HTTP client)
  - exchange_id in {binance,coinbase,kraken} and venue==live → live ccxt order

Backward compat: the legacy flag  config:system.paper_trading  is still honored
when execution_venue is not set — "true" maps to sim, "false" maps to alpaca_paper.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Literal

import ccxt.async_support as ccxt_async
import structlog

from src.streams.producer import produce, produce_audit
from src.streams import topology
from src.core.redis import get_redis

logger = structlog.get_logger()

# Redis keys for paper-trading state shared across processes
_K_CASH = "paper:cash"
_K_POSITIONS = "paper:positions"        # HASH: field=symbol, value=JSON
_K_ORDERS = "paper:orders"              # LIST of JSON, capped at 200
_K_DAILY_PNL = "paper:daily_pnl"
_K_TRADE_COUNT = "paper:trade_count"
_K_INIT = "paper:initialized"
_INITIAL_CASH = 10_000.0
_ORDERS_CAP = 200


async def _ensure_initialized() -> None:
    """Seed paper-trading Redis state with starting cash on first use. Idempotent."""
    redis = get_redis()
    if await redis.set(_K_INIT, "1", nx=True):
        await redis.set(_K_CASH, str(_INITIAL_CASH))
        await redis.set(_K_DAILY_PNL, "0")
        await redis.set(_K_TRADE_COUNT, "0")
        logger.info("paper_state_initialized", cash=_INITIAL_CASH)

OrderSide = Literal["BUY", "SELL"]
OrderStatus = Literal["PENDING", "FILLED", "CANCELLED", "REJECTED"]

# Commodity futures — always paper-only, real exchange trading not supported
_COMMODITY_SYMBOLS: frozenset[str] = frozenset({
    "GC=F", "CL=F", "SI=F", "HG=F", "NG=F", "ZW=F", "ZC=F", "ZS=F",
    "GC", "CL", "SI", "HG", "NG",
})
_SUPPORTED_LIVE_EXCHANGES: frozenset[str] = frozenset({"binance", "coinbase", "kraken"})


_EQUITY_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")


def _is_commodity(symbol: str) -> bool:
    """Return True for commodity futures — these never leave paper mode."""
    return symbol in _COMMODITY_SYMBOLS or symbol.endswith("=F")


def _is_equity_symbol(symbol: str) -> bool:
    """Return True for plain US-equity tickers (SPY, QQQ, NVDA, TSLA, AMD, META…).

    Conservative check: 1-5 uppercase letters, no slash (crypto pairs), no
    equals-suffix (futures), and not already on the commodity list.
    """
    if not symbol or "/" in symbol or "=" in symbol:
        return False
    if _is_commodity(symbol):
        return False
    return bool(_EQUITY_SYMBOL_RE.match(symbol))


VALID_VENUES: frozenset[str] = frozenset({"sim", "alpaca_paper", "live"})


async def get_execution_venue() -> str:
    """Return the active execution venue.

    Precedence: config:system.execution_venue → derive from paper_trading flag →
    "sim" (safest default).
    """
    redis = get_redis()
    raw = await redis.hget("config:system", "execution_venue")
    if raw:
        venue = raw.strip().lower()
        if venue in VALID_VENUES:
            return venue
    legacy = await redis.hget("config:system", "paper_trading")
    if legacy is None:
        return "sim"
    is_paper = legacy.strip().lower() not in ("false", "0", "no")
    return "sim" if is_paper else "alpaca_paper"


async def _paper_trading_enabled() -> bool:
    """Legacy helper — "paper" means anything that isn't live money.

    Retained so existing call sites don't have to change. For routing
    decisions inside submit_order we read the venue directly.
    """
    venue = await get_execution_venue()
    return venue != "live"


# Cache one AlpacaBroker per paper flag so paper and live can coexist in-process.
_alpaca_broker_cache: dict[bool, object] = {}


def get_alpaca_broker(paper: bool | None = None) -> object | None:
    """Lazy-construct AlpacaBroker using env/settings credentials.

    Returned as ``object | None`` to avoid a hard import cycle at module load;
    the broker exposes ``submit_order(...)`` matching the Order contract.
    """
    try:
        from src.core.config import settings
        from src.execution.alpaca_broker import AlpacaBroker
    except ImportError as exc:
        logger.error("alpaca_broker_import_failed", error=str(exc))
        return None

    api_key = getattr(settings, "alpaca_api_key", "") or os.getenv("ALPACA_API_KEY", "")
    secret = getattr(settings, "alpaca_secret_key", "") or os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret:
        logger.warning("alpaca_credentials_missing")
        return None

    if paper is None:
        paper_flag = getattr(settings, "alpaca_paper_trade", None)
        if paper_flag is None:
            paper_flag = os.getenv("ALPACA_PAPER_TRADE", "true")
        paper = paper_flag if isinstance(paper_flag, bool) else (
            str(paper_flag).strip().lower() not in ("false", "0", "no")
        )

    cached = _alpaca_broker_cache.get(paper)
    if cached is not None:
        return cached
    broker = AlpacaBroker(api_key=api_key, secret=secret, paper=paper)
    _alpaca_broker_cache[paper] = broker
    return broker


# Legacy alias — older call sites.
_get_alpaca_broker = get_alpaca_broker


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


def _order_to_json(order: "Order") -> dict:
    d = order.to_dict()
    # to_dict already serializes datetimes to ISO strings
    return d


def _order_from_json(data: dict) -> dict:
    """Convert JSON-decoded Order dict back to constructor kwargs."""
    out = dict(data)
    out["created_at"] = datetime.fromisoformat(out["created_at"])
    filled = out.get("filled_at")
    out["filled_at"] = datetime.fromisoformat(filled) if filled else None
    # to_dict omits fields that match dataclass defaults we still need explicit
    out.setdefault("order_type", "MARKET")
    out.setdefault("limit_price", None)
    out.setdefault("exchange_id", "paper")
    out.setdefault("live", False)
    return out


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
    """Simulate order execution with realistic slippage and commission.

    State lives in Redis so the trading loop and the API server see the same
    cash/positions/P&L — all reads and writes go through the keys under
    the ``paper:*`` namespace defined at the top of this module.
    """
    slippage_pct: float = 0.0005
    commission_pct: float = 0.001

    async def get_cash(self) -> float:
        await _ensure_initialized()
        redis = get_redis()
        val = await redis.get(_K_CASH)
        return float(val) if val is not None else _INITIAL_CASH

    async def _set_cash(self, value: float) -> None:
        await get_redis().set(_K_CASH, str(value))

    async def get_daily_pnl(self) -> float:
        await _ensure_initialized()
        val = await get_redis().get(_K_DAILY_PNL)
        return float(val) if val is not None else 0.0

    async def _incr_daily_pnl(self, delta: float) -> None:
        redis = get_redis()
        current = await redis.get(_K_DAILY_PNL)
        new_val = (float(current) if current is not None else 0.0) + delta
        await redis.set(_K_DAILY_PNL, str(new_val))

    async def reset_daily_pnl(self) -> None:
        await get_redis().set(_K_DAILY_PNL, "0")

    async def get_trade_count(self) -> int:
        await _ensure_initialized()
        val = await get_redis().get(_K_TRADE_COUNT)
        return int(val) if val is not None else 0

    async def _incr_trade_count(self) -> None:
        await get_redis().incr(_K_TRADE_COUNT)

    async def get_positions(self) -> list[dict]:
        await _ensure_initialized()
        raw = await get_redis().hgetall(_K_POSITIONS)
        return [json.loads(v) for v in (raw or {}).values()]

    async def _get_position(self, symbol: str) -> dict | None:
        raw = await get_redis().hget(_K_POSITIONS, symbol)
        return json.loads(raw) if raw else None

    async def _set_position(self, symbol: str, pos: dict) -> None:
        await get_redis().hset(_K_POSITIONS, symbol, json.dumps(pos))

    async def _delete_position(self, symbol: str) -> None:
        await get_redis().hdel(_K_POSITIONS, symbol)

    async def update_position_field(
        self, symbol: str, field_name: str, value: object
    ) -> None:
        """Used by position_monitor to update trailing_stop etc."""
        pos = await self._get_position(symbol)
        if pos is None:
            return
        pos[field_name] = value
        await self._set_position(symbol, pos)

    async def get_orders(self, limit: int = 100) -> list[Order]:
        await _ensure_initialized()
        raw = await get_redis().lrange(_K_ORDERS, 0, max(0, limit - 1))
        return [Order(**_order_from_json(json.loads(item))) for item in raw]

    async def _push_order(self, order: Order) -> None:
        redis = get_redis()
        await redis.lpush(_K_ORDERS, json.dumps(_order_to_json(order)))
        await redis.ltrim(_K_ORDERS, 0, _ORDERS_CAP - 1)

    async def get_portfolio_value(
        self, current_prices: dict[str, float] | None = None
    ) -> float:
        prices = current_prices or {}
        cash = await self.get_cash()
        positions = await self.get_positions()
        position_value = sum(
            pos["quantity"] * prices.get(pos["symbol"], pos["avg_price"])
            for pos in positions
        )
        return cash + position_value

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
        cycle_id: str | None = None,
    ) -> Order:
        """Route the order based on execution_venue + symbol type.

        ``cycle_id`` is propagated into stream:trades and stream:audit so the
        episode/outcome join in Week 2 can attribute trades back to the
        cycle that produced them. Background sweeps (position_monitor exits,
        manual flatten) pass ``cycle_id=None`` — that is correct.
        """
        from src.execution.alpaca_broker import (
            is_alpaca_crypto_symbol,
            is_alpaca_equity_symbol,
        )

        venue = await get_execution_venue()

        # Commodities: Alpaca has no futures, so they always stay on the local sim.
        if _is_commodity(symbol):
            if venue != "sim":
                logger.warning(
                    "commodity_forced_sim",
                    symbol=symbol, venue=venue,
                    msg="Commodity futures are sim-only.",
                )
            return await self._paper_fill(
                symbol, side, quantity, current_price,
                agent_id, strategy, stop_loss, take_profit,
                cycle_id=cycle_id,
            )

        # Polymarket uses its own HTTP client — sim-only here.
        if exchange_id == "polymarket":
            return await self._paper_fill(
                symbol, side, quantity, current_price,
                agent_id, strategy, stop_loss, take_profit,
                cycle_id=cycle_id,
            )

        # sim venue → local simulation for everything
        if venue == "sim":
            return await self._paper_fill(
                symbol, side, quantity, current_price,
                agent_id, strategy, stop_loss, take_profit,
                cycle_id=cycle_id,
            )

        # alpaca_paper or live: route through AlpacaBroker for equities and
        # Alpaca-supported crypto pairs. Fall back to sim on credential failure.
        routes_alpaca = (
            exchange_id == "alpaca"
            or is_alpaca_equity_symbol(symbol)
            or is_alpaca_crypto_symbol(symbol)
        )
        if routes_alpaca:
            alpaca_paper = venue != "live"
            alpaca = get_alpaca_broker(paper=alpaca_paper)
            if alpaca is None:
                # PRINCIPLE #3: no silent fallback. If Alpaca was supposed to
                # take this order, sim is NOT a valid substitute — operators
                # would see "fills" that aren't real. Trip the kill switch and
                # raise; the caller (Atlas) surfaces this to the operator.
                from src.core.security import activate_kill_switch
                from src.execution.position_source import BrokerUnavailableError

                await activate_kill_switch(
                    reason=f"alpaca_unavailable (venue={venue}, symbol={symbol})",
                    operator_id="broker_router",
                )
                raise BrokerUnavailableError(
                    f"Alpaca required for venue={venue} symbol={symbol}, "
                    f"unavailable — kill switch tripped"
                )
            order = await alpaca.submit_order(
                symbol=symbol, side=side, quantity=quantity,
                order_type="market", limit_price=None,
                agent_id=agent_id, strategy=strategy,
                cycle_id=cycle_id,
            )
            await self._push_order(order)
            return order

        # live venue + non-Alpaca crypto → ccxt (binance/coinbase/kraken)
        if venue == "live":
            exchange = await _get_live_exchange(exchange_id)
            if exchange is None:
                from src.core.security import activate_kill_switch
                from src.execution.position_source import BrokerUnavailableError

                await activate_kill_switch(
                    reason=f"live_exchange_unavailable (exchange={exchange_id}, symbol={symbol})",
                    operator_id="broker_router",
                )
                raise BrokerUnavailableError(
                    f"Live exchange {exchange_id!r} required for symbol={symbol}, "
                    f"unavailable — kill switch tripped"
                )
            return await self._live_fill(
                exchange, symbol, side, quantity, agent_id, strategy, exchange_id,
                cycle_id=cycle_id,
            )

        # alpaca_paper + non-Alpaca crypto pair → still simulate locally.
        # Don't silently flip to live ccxt from a "paper" venue. This is a
        # legitimate use of sim (the symbol simply has no real venue here),
        # not a fallback.
        return await self._paper_fill(
            symbol, side, quantity, current_price,
            agent_id, strategy, stop_loss, take_profit,
            cycle_id=cycle_id,
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
        cycle_id: str | None = None,
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
        await self._push_order(order)
        redis = get_redis()
        await produce(topology.TRADES, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": str(quantity), "filled_price": str(filled_price),
            "agent_id": agent_id, "strategy": strategy,
            "exchange": exchange_id, "live": "true",
            "cycle_id": cycle_id or "",
        }, redis=redis)
        await produce_audit("live_trade_executed", agent_id, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": quantity, "price": filled_price, "exchange": exchange_id,
        }, redis=redis, cycle_id=cycle_id)
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
        cycle_id: str | None = None,
    ) -> Order:
        """Simulate fill with slippage and commission. State persists to Redis.

        Week 1 / A4: sizing happens upstream (in Atlas, then Week 2's
        PortfolioConstructor). The broker no longer sizes — it executes the
        quantity it was given. ``quantity == 0`` is now a bug, not a pattern,
        so we reject it explicitly so the bug surfaces.
        """
        order_id = str(uuid.uuid4())[:8]

        if quantity <= 0:
            logger.error(
                "paper_fill_zero_quantity",
                symbol=symbol, side=side, agent=agent_id, strategy=strategy,
                msg="sizer must run before broker dispatch (Week 1 / A4)",
            )
            return Order(
                order_id=order_id, symbol=symbol, side=side, quantity=0.0,
                order_type="MARKET", limit_price=None, status="REJECTED",
                filled_price=None, created_at=datetime.now(UTC), filled_at=None,
                agent_id=agent_id, strategy=strategy,
                exchange_id="paper", live=False,
            )

        cash = await self.get_cash()
        slip = current_price * self.slippage_pct
        filled_price = current_price + slip if side == "BUY" else current_price - slip
        commission = filled_price * quantity * self.commission_pct

        if side == "BUY":
            cost = filled_price * quantity + commission
            if cost > cash:
                quantity = (cash * 0.95) / (filled_price * (1 + self.commission_pct))
                commission = filled_price * quantity * self.commission_pct
                cost = filled_price * quantity + commission
            await self._set_cash(cash - cost)
            # Week 2 / B4 — stamp trade_id + cycle_id on the open position so
            # the position_monitor's exit path can write a structured outcome
            # event keyed on trade_id.
            trade_id = str(uuid.uuid4())
            await self._set_position(symbol, {
                "symbol": symbol, "quantity": quantity,
                "avg_price": filled_price, "side": "LONG",
                "entry_time": datetime.now(UTC).isoformat(),
                "stop_loss": stop_loss, "take_profit": take_profit,
                "trailing_stop": None,
                "trade_id": trade_id,
                "cycle_id": cycle_id or "",
            })
        else:
            proceeds = filled_price * quantity - commission
            existing = await self._get_position(symbol)
            entry_price = existing["avg_price"] if existing else filled_price
            pnl = proceeds - (entry_price * quantity)
            await self._set_cash(cash + proceeds)
            await self._incr_daily_pnl(pnl)
            await self._delete_position(symbol)

        order = Order(
            order_id=order_id, symbol=symbol, side=side, quantity=quantity,
            order_type="MARKET", limit_price=None, status="FILLED",
            filled_price=filled_price, created_at=datetime.now(UTC),
            filled_at=datetime.now(UTC), agent_id=agent_id, strategy=strategy,
            exchange_id="paper", live=False,
        )
        await self._push_order(order)
        await self._incr_trade_count()
        redis = get_redis()
        await produce(topology.TRADES, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": str(quantity), "filled_price": str(filled_price),
            "commission": str(commission), "agent_id": agent_id, "strategy": strategy,
            "cycle_id": cycle_id or "",
        }, redis=redis)
        await produce_audit("trade_executed", agent_id, {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": quantity, "price": filled_price,
        }, redis=redis, cycle_id=cycle_id)
        logger.info("paper_order_filled", order_id=order_id, symbol=symbol,
                    side=side, price=filled_price, agent=agent_id,
                    quantity=round(quantity, 6))
        return order


    async def flatten_all(self, current_prices: dict[str, float] | None = None) -> None:
        """Emergency: mark all positions closed at last known price."""
        prices = current_prices or {}
        cash = await self.get_cash()
        positions = await self.get_positions()
        for pos in positions:
            symbol = pos["symbol"]
            price = prices.get(symbol, pos["avg_price"])
            proceeds = pos["quantity"] * price * (1 - self.commission_pct)
            cash += proceeds
            await self._delete_position(symbol)
            logger.warning("position_flattened", symbol=symbol, price=price)
        await self._set_cash(cash)


# Module-level singleton
paper_broker = PaperBroker()
