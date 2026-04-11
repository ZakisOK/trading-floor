"""
Calibration — measures whether agents' stated confidence matches reality.

A well-calibrated agent who says 0.8 confidence should win 80% of the time.
After every 10 resolved trades per agent, this module:
  1. Buckets historical signals by confidence decile (0.5–0.6, 0.6–0.7, etc.)
  2. Computes actual win rate per bucket
  3. Calculates calibration error (ECE — Expected Calibration Error)
  4. Stores results in Redis
  5. Logs a warning if calibration is drifting worse

Redis keys:
  agent:{agent_id}:calibration  — Hash: ece, last_checked, bucket data (JSON)
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import structlog

from src.core.redis import get_redis

logger = structlog.get_logger()

# Minimum resolved signals before we attempt calibration
MIN_SIGNALS_FOR_CALIBRATION = 10

# Confidence buckets: 0.5–0.6, 0.6–0.7, 0.7–0.8, 0.8–0.9, 0.9–1.0
BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


async def run_calibration_check(agent_id: str) -> dict:
    """
    Runs calibration analysis for one agent.
    Reads their full signal history from Redis, bins by confidence,
    computes ECE, and persists the result.

    Returns a dict with keys: agent_id, ece, buckets, total_signals, status.
    """
    redis = get_redis()

    # Pull all signal IDs for this agent (most recent 200)
    signal_ids = await redis.zrevrange(f"agent:{agent_id}:signals", 0, 199)
    if not signal_ids:
        return {"agent_id": agent_id, "status": "no_data", "ece": None}

    # Build bucket accumulators: {bucket_label: {"count": N, "wins": N, "mid": float}}
    bucket_data: dict[str, dict] = {}
    for lo, hi in BUCKETS:
        label = f"{lo:.1f}-{hi:.1f}"
        bucket_data[label] = {"lo": lo, "hi": hi, "mid": (lo + hi) / 2, "count": 0, "wins": 0}

    total_resolved = 0

    for sid in signal_ids:
        rec = await redis.hgetall(f"signal:{sid}")
        if not rec:
            continue
        outcome = rec.get("outcome")
        if outcome not in ("WIN", "LOSS"):
            continue

        try:
            conf = float(rec.get("confidence", 0))
        except ValueError:
            continue

        total_resolved += 1

        # Find the matching bucket
        for lo, hi in BUCKETS:
            if lo <= conf < hi:
                label = f"{lo:.1f}-{hi:.1f}"
                bucket_data[label]["count"] += 1
                if outcome == "WIN":
                    bucket_data[label]["wins"] += 1
                break

    if total_resolved < MIN_SIGNALS_FOR_CALIBRATION:
        return {
            "agent_id": agent_id,
            "status": "insufficient_data",
            "total_signals": total_resolved,
            "ece": None,
        }

    # Compute Expected Calibration Error (ECE)
    # ECE = Σ (bucket_count / total) * |actual_win_rate - bucket_midpoint|
    ece = 0.0
    bucket_summary = []
    for label, b in bucket_data.items():
        if b["count"] == 0:
            continue
        actual_rate = b["wins"] / b["count"]
        weight = b["count"] / total_resolved
        error = abs(actual_rate - b["mid"])
        ece += weight * error
        bucket_summary.append({
            "bucket": label,
            "count": b["count"],
            "actual_win_rate": round(actual_rate, 4),
            "expected_win_rate": round(b["mid"], 4),
            "error": round(error, 4),
        })

    # Determine drift status
    if ece < 0.05:
        status = "well_calibrated"
    elif ece < 0.15:
        status = "moderate_drift"
    else:
        status = "poorly_calibrated"

    result = {
        "agent_id": agent_id,
        "ece": round(ece, 4),
        "total_signals": total_resolved,
        "buckets": bucket_summary,
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
    }

    # Persist to Redis
    await redis.hset(f"agent:{agent_id}:calibration", mapping={
        "ece": str(ece),
        "status": status,
        "total_signals": str(total_resolved),
        "buckets": json.dumps(bucket_summary),
        "last_checked": datetime.now(UTC).isoformat(),
    })

    if status == "poorly_calibrated":
        logger.warning(
            "agent_calibration_drift",
            agent=agent_id,
            ece=round(ece, 4),
            status=status,
            recommendation="Prompt adjustment needed — agent over/under-stating confidence",
        )
    else:
        logger.info(
            "agent_calibration_ok",
            agent=agent_id,
            ece=round(ece, 4),
            status=status,
        )

    return result


async def run_all_calibrations(agent_ids: list[str]) -> list[dict]:
    """Run calibration checks for every agent. Called by Portfolio Chief daily."""
    results = []
    for agent_id in agent_ids:
        result = await run_calibration_check(agent_id)
        results.append(result)
    return results


async def get_calibration_score(agent_id: str) -> float | None:
    """
    Returns the cached ECE score for an agent (lower = better calibrated).
    Returns None if not yet computed.
    """
    redis = get_redis()
    raw = await redis.hget(f"agent:{agent_id}:calibration", "ece")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


async def should_run_calibration(agent_id: str) -> bool:
    """
    Returns True if this agent has 10+ new resolved signals since last calibration.
    This is how Portfolio Chief decides when to trigger a re-check.
    """
    redis = get_redis()

    last_total_raw = await redis.hget(f"agent:{agent_id}:calibration", "total_signals")
    current_total_raw = await redis.hget(f"agent:{agent_id}:accuracy", "total")

    if current_total_raw is None:
        return False

    last_total = int(last_total_raw or 0)
    current_total = int(current_total_raw or 0)

    return (current_total - last_total) >= 10
