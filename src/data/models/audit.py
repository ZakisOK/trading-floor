"""Audit log ORM model stub — append-only with SHA-256 hash chain."""
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String, Text, DateTime
from src.data.models.base import Base


class AuditLog(Base):
    """Immutable audit trail. REVOKE UPDATE, DELETE granted in migration."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # TODO: Add hash chain verification helper (Phase 1)
