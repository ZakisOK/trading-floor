"""
Portfolio Chief — Desk 3: Portfolio Oversight & Meta-Learning.

Runs every 5 minutes. Watches the whole firm:
  1. Cross-position correlation check (concentration risk)
  2. Mistake pattern detection (suppresses underperforming agents)
  3. Regime detection (TRENDING / RANGING / VOLATILE)
  4. Daily performance report at UTC midnight

Also triggers calibration checks and broadcasts regime label to all agents.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, time as dt_time
from typing import Literal

import structlog

from src.core.redis import get_redis
from src.learning.agent_memory import agent_memory
from src.learning.calibration import run_all_calibrations, should_run_calibration
from src.streams.producer import produce, produce_audit
from src.streams import topology

logger = structlog.get_logger()

# Run interval
OVERSIGHT_INTERVAL_SECONDS = 300  # 5 minutes

# Concentration: flag if more than this many concurrent longs in same asset class
MAX_CONCURRENT_LONGS_PER_CLASS = 3

# Mistake pattern: if >= this many consecutive losses with same pattern → suppress
CONSECUTIVE_LOSS_THRESHOLD = 3

# Asset class buckets (simple prefix-based classification)
ASSET_CLASS_MAP = {
    "BTC": "crypto_major", "ETH": "crypto_major", "SOL": "crypto_major",
    "XRP": "crypto_alt", "ADA": "crypto_alt", "DOGE": "crypto_alt", "AVAX": "crypto_alt",
    "MATIC": "crypto_alt", "DOT": "crypto_alt", "LINK": "crypto_alt",
}

# All research agents — used for calibration sweeps
RESEARCH_AGENTS = ["marcus", "vera", "rex", "xrp_analyst", "polymarket_scout"]

RegimeLabel = Literal["TRENDING", "RANGING", "VOLATILE"]


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

def _classify_regime(atr_current: float, atr_avg: float, price_change_pct: float) -> RegimeLabel:
    """
    Simple regime classifier:
      - VOLATILE: current ATR > 1.5× the 50-period ATR average
      - TRENDING: current ATR is normal AND absolute price move > 2% over 24h
      - RANGING: everything else
    """
    if atr_avg <= 0:
        return "VOLATILE"
    ratio = atr_current / atr_avg
    if ratio > 1.5:
        return "VOLATILE"
    if abs(price_change_pct) > 2.0:
        return "TRENDING"
    return "RANGING"


async def _detect_market_regime() -> RegimeLabel:
    """
    Read BTC ATR metrics from Redis (written by the data feed layer).
    Falls back to RANGING if no data available.
    """
    redis = get_redis()
    try:
        atr_current_raw = await redis.get("market:BTC/USDT:atr20")
        atr_avg_raw = await redis.get("market:BTC/USDT:atr50_avg")
        change_raw = await redis.get("market:BTC/USDT:change24h_pct")

        atr_current = float(atr_current_raw or 0)
        atr_avg = float(atr_avg_raw or 0)
        change_pct = float(change_raw or 0)

        regime = _classify_regime(atr_current, atr_avg, change_pct)
    except Exception as e:
        logger.warning("regime_detection_failed", error=str(e))
        regime = "RANGING"

    # Broadcast regime to Redis so all agents can read it
    await redis.set("market:regime", regime, ex=OVERSIGHT_INTERVAL_SECONDS * 2)
    logger.info("regime_detected", regime=regime)
    return regime


# ---------------------------------------------------------------------------
# Concentration risk
# ---------------------------------------------------------------------------

async def _check_concentration() -> list[str]:
    """
    Inspect open positions. Flag asset classes with >MAX_CONCURRENT_LONGS_PER_CLASS
    concurrent long positions as concentrated.
    Returns list of flagged asset classes.
    """
    redis = get_redis()
    flags: list[str] = []

    try:
        # Positions are stored as hashes: position:{symbol}
        position_keys = await redis.keys("position:*")
        class_longs: dict[str, int] = defaultdict(int)

        for key in position_keys:
            pos = await redis.hgetall(key)
            if not pos:
                continue
            symbol: str = pos.get("symbol", "")
            side: str = pos.get("side", "LONG")
            qty = float(pos.get("quantity", 0))
            if qty <= 0 or side != "LONG":
                continue

            # Classify by asset prefix
            base = symbol.split("/")[0].upper()
            asset_class = ASSET_CLASS_MAP.get(base, "other")
            class_longs[asset_class] += 1

        for asset_class, count in class_longs.items():
            if count > MAX_CONCURRENT_LONGS_PER_CLASS:
                flags.append(asset_class)
                logger.warning(
                    "concentration_risk_flagged",
                    asset_class=asset_class,
                    concurrent_longs=count,
                    threshold=MAX_CONCURRENT_LONGS_PER_CLASS,
                )
                await produce(topology.PORTFOLIO_EVENTS, {
                    "event": "concentration_risk",
                    "asset_class": asset_class,
                    "concurrent_longs": str(count),
                    "threshold": str(MAX_CONCURRENT_LONGS_PER_CLASS),
                })
    except Exception as e:
        logger.error("concentration_check_failed", error=str(e))

    return flags


# ---------------------------------------------------------------------------
# Mistake pattern detection
# ---------------------------------------------------------------------------

async def _detect_mistake_patterns() -> None:
    """
    Read the last 20 closed trades from Redis.
    If any agent has >= CONSECUTIVE_LOSS_THRESHOLD consecutive losses,
    suppress that agent's weight for 1 hour.
    """
    redis = get_redis()
    try:
        # Closed trade outcomes stored in stream:trade_outcomes
        raw_entries = await redis.xrevrange(topology.TRADE_OUTCOMES, count=20)
        if not raw_entries:
            return

        # Group outcomes by agent_id in arrival order
        agent_streaks: dict[str, list[str]] = defaultdict(list)
        for _msg_id, fields in raw_entries:
            agent_id = fields.get("originating_agent_id", "")
            outcome = fields.get("outcome", "")
            if agent_id and outcome:
                agent_streaks[agent_id].append(outcome)

        for agent_id, outcomes in agent_streaks.items():
            # Count consecutive losses from the start (most recent = first)
            consecutive_losses = 0
            for o in outcomes:
                if o == "LOSS":
                    consecutive_losses += 1
                else:
                    break

            if consecutive_losses >= CONSECUTIVE_LOSS_THRESHOLD:
                logger.warning(
                    "mistake_pattern_detected",
                    agent=agent_id,
                    consecutive_losses=consecutive_losses,
                    action="suppressing_weight_1h",
                )
                await agent_memory.suppress_agent_weight(
                    agent_id, factor=0.75, ttl_seconds=3600
                )
                await produce(topology.PORTFOLIO_EVENTS, {
                    "event": "agent_weight_suppressed",
                    "agent_id": agent_id,
                    "consecutive_losses": str(consecutive_losses),
                    "suppression_factor": "0.75",
                    "ttl_seconds": "3600",
                })

    except Exception as e:
        logger.error("mistake_pattern_detection_failed", error=str(e))


# ---------------------------------------------------------------------------
# Daily performance report
# ---------------------------------------------------------------------------

async def _write_daily_report() -> None:
    """
    Writes a daily summary to Redis at UTC midnight.
    Reads from stream:trade_outcomes to compute stats.
    """
    redis = get_redis()
    try:
        # Read last 1000 outcomes (today's trades)
        raw_entries = await redis.xrange(topology.TRADE_OUTCOMES, count=1000)
        if not raw_entries:
            logger.info("daily_report_no_trades")
            return

        total = len(raw_entries)
        wins = 0
        total_pnl = 0.0
        pnl_values: list[float] = []
        agent_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})

        for _msg_id, fields in raw_entries:
            outcome = fields.get("outcome", "")
            pnl = float(fields.get("pnl_pct", 0) or 0)
            agent_id = fields.get("originating_agent_id", "unknown")

            if outcome == "WIN":
                wins += 1
                agent_stats[agent_id]["wins"] += 1
            elif outcome == "LOSS":
                agent_stats[agent_id]["losses"] += 1

            total_pnl += pnl
            pnl_values.append(pnl)
            agent_stats[agent_id]["pnl"] += pnl

        win_rate = wins / total if total > 0 else 0.0

        # Sharpe (simplified: mean/std of PnL, annualized if >10 trades)
        sharpe = None
        if len(pnl_values) >= 10:
            import statistics
            avg_pnl = statistics.mean(pnl_values)
            std_pnl = statistics.stdev(pnl_values) if len(pnl_values) > 1 else 1e-9
            sharpe = round(avg_pnl / std_pnl * (252 ** 0.5), 2) if std_pnl > 0 else None

        # Best/worst agent by PnL
        best_agent = max(agent_stats, key=lambda a: agent_stats[a]["pnl"], default="none")
        worst_agent = min(agent_stats, key=lambda a: agent_stats[a]["pnl"], default="none")

        report = {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "total_trades": total,
            "win_rate": round(win_rate, 4),
            "total_pnl_pct": round(total_pnl, 4),
            "sharpe": sharpe,
            "best_agent": best_agent,
            "worst_agent": worst_agent,
            "agent_stats": dict(agent_stats),
            "generated_at": datetime.now(UTC).isoformat(),
        }

        date_key = f"report:daily:{datetime.now(UTC).strftime('%Y-%m-%d')}"
        await redis.set(date_key, json.dumps(report), ex=60 * 60 * 24 * 30)  # keep 30 days
        await redis.set("report:daily:latest", json.dumps(report))

        logger.info(
            "daily_report_written",
            total_trades=total,
            win_rate=f"{win_rate:.1%}",
            total_pnl_pct=f"{total_pnl:.2%}",
            sharpe=sharpe,
            best_agent=best_agent,
        )

    except Exception as e:
        logger.error("daily_report_failed", error=str(e))


# ---------------------------------------------------------------------------
# Calibration sweep
# ---------------------------------------------------------------------------

async def _run_calibration_sweep() -> None:
    """Check each research agent and run calibration if 10+ new signals have resolved."""
    for agent_id in RESEARCH_AGENTS:
        if await should_run_calibration(agent_id):
            await run_all_calibrations([agent_id])


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_last_report_date: str = ""


async def run() -> None:
    """
    Portfolio Chief main loop. Runs every 5 minutes.
    Handles regime detection, concentration risk, mistake patterns,
    calibration sweeps, and nightly reports.
    """
    logger.info("portfolio_chief_started", interval_s=OVERSIGHT_INTERVAL_SECONDS)

    while True:
        try:
            now_utc = datetime.now(UTC)

            # 1. Detect market regime and broadcast
            regime = await _detect_market_regime()

            # 2. Cross-position concentration check
            flagged = await _check_concentration()

            # 3. Mistake pattern detection → weight suppression
            await _detect_mistake_patterns()

            # 4. Calibration sweep (only when agents have 10+ new signals)
            await _run_calibration_sweep()

            # 5. Daily report at midnight UTC
            today = now_utc.strftime("%Y-%m-%d")
            global _last_report_date
            midnight_window = now_utc.hour == 0 and now_utc.minute < 5
            if midnight_window and today != _last_report_date:
                await _write_daily_report()
                _last_report_date = today

            logger.debug(
                "portfolio_chief_sweep_complete",
                regime=regime,
                concentration_flags=flagged,
            )

        except Exception as e:
            logger.error("portfolio_chief_unhandled_error", error=str(e))

        await asyncio.sleep(OVERSIGHT_INTERVAL_SECONDS)
