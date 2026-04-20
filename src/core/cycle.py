"""Cycle identity helpers (Week 1 / B1).

A *cycle* is one walk of the trading graph for one symbol. Every agent call
in a cycle shares the same `cycle_id` (UUIDv7, time-ordered). Every call also
shares the `regime_fingerprint` computed at cycle entry.

This module is intentionally small and dependency-light so it can be imported
from agents, the supervisor, and the consumer without pulling in heavy state.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from uuid6 import uuid7


def new_cycle_id() -> str:
    """Generate a fresh UUIDv7 cycle id as canonical hex form (8-4-4-4-12)."""
    return str(uuid7())


def utcnow() -> datetime:
    """UTC-aware now. Single import point so call sites don't drift to utcnow()."""
    return datetime.now(UTC)


def compute_regime_fingerprint_stub(market_data: dict[str, Any] | None) -> str:
    """Week 1 stub. Week 3 replaces this with the full regime vector hash.

    Format: ``stub-v1:{symbol}``. Stable per cycle. The ``stub-v1`` prefix lets
    downstream queries identify rows that came from the stub, so they can be
    excluded from regime-conditional analysis until the full implementation
    lands.
    """
    md = market_data or {}
    symbol = md.get("symbol", "UNKNOWN") if isinstance(md, dict) else "UNKNOWN"
    return f"stub-v1:{symbol}"


def compute_regime_fingerprint_full(vector: dict[str, Any]) -> str:
    """Week 3 implementation. Hashes the regime vector to a 16-char fingerprint.

    Vector composition (per glossary): ``vol_percentile_20d, trend_strength_60d,
    correlation_regime, news_density, time_of_day_bucket``. Order matters; we
    serialize sorted by key so callers don't need to be careful.
    """
    parts = [f"{k}={vector[k]}" for k in sorted(vector)]
    payload = "|".join(parts).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
