"""Agent ORM models: AgentState, Signal, AgentMessage."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base, TimestampMixin


class AgentState(Base, TimestampMixin):
    """Persistent state snapshot for each agent."""

    __tablename__ = "agent_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="IDLE")
    # IDLE | WORKING | ERROR
    current_task: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    elo_rating: Mapped[float] = mapped_column(Float, nullable=False, default=1200.0)
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Signal(Base, TimestampMixin):
    """A trading signal produced by an agent."""

    __tablename__ = "signal"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # LONG | SHORT | NEUTRAL
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 - 1.0
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)


class AgentMessage(Base, TimestampMixin):
    """An inter-agent message for collaboration and debate."""

    __tablename__ = "agent_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_agent: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    to_agent: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # text or JSON string
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
