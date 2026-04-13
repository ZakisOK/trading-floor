"""
validator.py — Data quality firewall (Gap 4: Simons recommendation).

Every incoming market data bar passes through here before entering the signal
pipeline. Bad bars cause cascading garbage; it is cheaper to skip a cycle than
to trade on corrupted data.

Checks (in order):
  1. Stale timestamp     — crypto >5 min, commodity >1 day
  2. Zero / null OHLCV   — any field None or 0
  3. OHLCV coherence     — close outside [low, high]
  4. Price spike         — drop >40% in one bar (likely unadjusted split)
  5. Volume anomaly      — >10x 20-bar rolling avg (suspicious, not rejected)

Rejected bars are written to stream:data_quality_errors for monitoring.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import structlog

from src.core.redis import get_redis
from src.streams import topology

logger = structlog.get_logger()

# Symbol sets for regime-specific staleness thresholds
COMMODITY_SYMBOLS = {"CL=F", "GC=F", "SI=F", "NG=F", "ZC=F", "ZW=F", "ZS=F"}

STALE_CRYPTO_SECONDS = 300       # 5 minutes
STALE_COMMODITY_SECONDS = 86400  # 1 trading day

SPIKE_DROP_THRESHOLD = 0.40   # 40% single-bar drop = likely split
VOLUME_ANOMALY_MULTIPLIER = 10  # >10x rolling avg = suspicious
VOLUME_WINDOW = 20

# In-process rolling volume history: symbol -> list[float] (newest last)
_volume_history: dict[str, list[float]] = {}


async def _write_error(symbol: str, reason: str, bar: dict[str, Any]) -> None:
    """Append a rejected bar record to the data quality error stream."""
    try:
        redis = get_redis()
        await redis.xadd(
            "stream:data_quality_errors",
            {
                "symbol": symbol,
                "reason": reason,
                "timestamp": bar.get("timestamp", ""),
                "open": str(bar.get("open", "")),
                "high": str(bar.get("high", "")),
                "low": str(bar.get("low", "")),
                "close": str(bar.get("close", "")),
                "volume": str(bar.get("volume", "")),
                "logged_at": datetime.now(UTC).isoformat(),
            },
            maxlen=5000,
        )
    except Exception as exc:
        logger.warning("data_quality_error_write_failed", symbol=symbol, err=str(exc))


def _is_commodity(symbol: str) -> bool:
    return symbol in COMMODITY_SYMBOLS


def _stale_threshold(symbol: str) -> float:
    return STALE_COMMODITY_SECONDS if _is_commodity(symbol) else STALE_CRYPTO_SECONDS


async def validate_bar(
    symbol: str,
    bar: dict[str, Any],
    prev_close: float | None = None,
) -> tuple[bool, str]:
    """
    Validate a single OHLCV bar.

    Returns:
        (True, "ok")                    — bar passed all checks
        (True, "suspicious_volume")     — bar passed but volume is anomalous
        (False, "<reason>")             — bar rejected; caller should skip symbol
    """
    # ── 1. Stale timestamp ──────────────────────────────────────────────────
    raw_ts = bar.get("timestamp")
    if raw_ts:
        try:
            if isinstance(raw_ts, (int, float)):
                bar_time = float(raw_ts)
            else:
                bar_time = datetime.fromisoformat(str(raw_ts)).timestamp()
            age_seconds = time.time() - bar_time
            threshold = _stale_threshold(symbol)
            if age_seconds > threshold:
                reason = f"stale_bar ({int(age_seconds)}s > {threshold}s)"
                await _write_error(symbol, reason, bar)
                logger.warning("data_validator_reject", symbol=symbol, reason=reason)
                return False, reason
        except Exception:
            pass  # unparseable timestamp: let other checks decide

    # ── 2. Zero / null OHLCV ────────────────────────────────────────────────
    for field in ("open", "high", "low", "close"):
        val = bar.get(field)
        if val is None or float(val) == 0:
            reason = f"null_or_zero_{field}"
            await _write_error(symbol, reason, bar)
            logger.warning("data_validator_reject", symbol=symbol, reason=reason)
            return False, reason

    o = float(bar["open"])
    h = float(bar["high"])
    lo = float(bar["low"])
    c = float(bar["close"])

    # ── 3. OHLCV coherence ───────────────────────────────────────────────────
    if c > h or c < lo:
        reason = f"close_outside_range (c={c}, l={lo}, h={h})"
        await _write_error(symbol, reason, bar)
        logger.warning("data_validator_reject", symbol=symbol, reason=reason)
        return False, reason

    # ── 4. Price spike / split detection ─────────────────────────────────────
    if prev_close and prev_close > 0:
        drop = (prev_close - c) / prev_close
        if drop > SPIKE_DROP_THRESHOLD:
            reason = f"price_spike_drop ({drop:.1%} vs prev_close={prev_close})"
            await _write_error(symbol, reason, bar)
            logger.warning("data_validator_reject", symbol=symbol, reason=reason)
            return False, reason

    # ── 5. Volume anomaly (flag, do not reject) ───────────────────────────────
    vol = float(bar.get("volume", 0) or 0)
    history = _volume_history.setdefault(symbol, [])
    if len(history) >= VOLUME_WINDOW:
        avg_vol = sum(history[-VOLUME_WINDOW:]) / VOLUME_WINDOW
        if avg_vol > 0 and vol > avg_vol * VOLUME_ANOMALY_MULTIPLIER:
            logger.warning(
                "data_validator_suspicious_volume",
                symbol=symbol,
                volume=vol,
                avg=round(avg_vol, 2),
                multiplier=round(vol / avg_vol, 1),
            )
            # Update history and return suspicious (caller tags bar, does not drop)
            history.append(vol)
            if len(history) > VOLUME_WINDOW * 3:
                _volume_history[symbol] = history[-(VOLUME_WINDOW * 2):]
            return True, "suspicious_volume"

    if vol > 0:
        history.append(vol)
        if len(history) > VOLUME_WINDOW * 3:
            _volume_history[symbol] = history[-(VOLUME_WINDOW * 2):]

    return True, "ok"


async def validate_market_data(
    market_data: dict[str, dict[str, Any]],
    prev_closes: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Validate all symbols in a market_data dict.

    Returns a filtered dict containing only symbols that passed validation.
    Suspicious-volume bars are tagged with bar["data_quality"] = "suspicious".
    """
    prev_closes = prev_closes or {}
    clean: dict[str, dict[str, Any]] = {}
    rejected_count = 0

    for symbol, bar in market_data.items():
        passed, reason = await validate_bar(symbol, bar, prev_closes.get(symbol))
        if not passed:
            rejected_count += 1
            continue
        if reason == "suspicious_volume":
            bar = dict(bar)
            bar["data_quality"] = "suspicious"
        clean[symbol] = bar

    if rejected_count:
        logger.info(
            "data_validator_summary",
            total=len(market_data),
            passed=len(clean),
            rejected=rejected_count,
        )

    return clean
