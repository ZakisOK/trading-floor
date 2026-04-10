"""Paper trading broker — simulates order execution with slippage and commission."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Literal

import structlog

from src.streams.producer import produce, produce_audit
from src.streams import topology
from src.core.redis import get_redis

logger = structlog.get_logger()

OrderSide = Literal["BUY", "SELL"]
OrderStatus = Literal["PENDING", "FILLED", "CANCELLED", "REJECTED"]


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

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id, "symbol": self.symbol, "side": self.side,
            "quantity": self.quantity, "order_type": self.order_type,
            "status": self.status, "filled_price": self.filled_price,
            "created_at": self.created_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "agent_id": self.agent_id, "strategy": self.strategy,
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
    ) -> Order:
        order_id = str(uuid.uuid4())[:8]
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
            }
        else:
            proceeds = filled_price * quantity - commission
            self._cash += proceeds
            pnl = proceeds - (self._positions.get(symbol, {}).get("avg_price", filled_price) * quantity)
            self._daily_pnl += pnl
            self._positions.pop(symbol, None)

        order = Order(
            order_id=order_id, symbol=symbol, side=side, quantity=quantity,
            order_type="MARKET", limit_price=None, status="FILLED",
            filled_price=filled_price, created_at=datetime.now(UTC),
            filled_at=datetime.now(UTC), agent_id=agent_id, strategy=strategy,
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
        logger.info("order_filled", order_id=order_id, symbol=symbol,
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
        """Emergency: mark all positions as closed at last known price."""
        prices = current_prices or {}
        for symbol, pos in list(self._positions.items()):
            price = prices.get(symbol, pos["avg_price"])
            proceeds = pos["quantity"] * price * (1 - self.commission_pct)
            self._cash += proceeds
            logger.warning("position_flattened", symbol=symbol, price=price)
        self._positions.clear()


# Module-level singleton
paper_broker = PaperBroker()
