"""OHLCV ORM model stub."""
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Float, BigInteger, DateTime
from src.data.models.base import Base, TimestampMixin


class OHLCV(Base, TimestampMixin):
    __tablename__ = "ohlcv"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    # TODO: Convert to TimescaleDB hypertable via migration (Phase 1)
