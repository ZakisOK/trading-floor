"""Audit log ORM model — append-only with SHA-256 hash chain."""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.base import Base


class AuditLog(Base):
    """Immutable audit trail with SHA-256 hash chain.

    prev_hash: SHA-256 of the previous entry's entry_hash.
    entry_hash: SHA-256 of (prev_hash + event_type + agent_id + payload + ts).

    REVOKE UPDATE, DELETE on audit_log applied in migration.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
