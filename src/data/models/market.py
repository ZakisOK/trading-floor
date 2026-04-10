"""OHLCV ORM model — TimescaleDB hypertable partitioned by ts."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base, TimestampMixin


class OHLCV(Base, TimestampMixin):
    """OHLCV candlestick data.

    TimescaleDB hypertable — partition by ts.
    Dedup constraint on (symbol, exchange, timeframe, ts).
    """

    __tablename__ = "ohlcv"
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "timeframe", "ts", name="uq_ohlcv_bar"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
