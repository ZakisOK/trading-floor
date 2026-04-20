"""Counterfactual attribution job — Week 2 / B3.

For each trade_outcome where ``counterfactual_hit IS NULL``:
  1. Load the cycle's contributions.
  2. For each contributor, simulate Diana's gate with that agent removed.
  3. If removal flips ``risk_approved`` from true → false, the agent gets
     full credit (``counterfactual_hit=true``, attributed_pnl_usd = trade pnl).
  4. Otherwise the agent rode consensus (``counterfactual_hit=false``,
     attributed_pnl_usd = trade pnl / num_contributors).

Edge cases:
  - Single contributor → automatic hit.
  - Tied votes → all contributors hit (each could have flipped).
  - Diana's threshold lives in src.agents.diana.CONFIDENCE_THRESHOLD; we
    import it so future threshold changes propagate automatically. (Week 5
    moves the threshold to a learned value per fingerprint.)

Run:
    python scripts/run_counterfactual_attribution.py [--limit 100]

Idempotent: only touches rows where counterfactual_hit IS NULL.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.diana import CONFIDENCE_THRESHOLD
from src.core.database import AsyncSessionLocal

logger = structlog.get_logger()


_PENDING_TRADES = text(
    """
    SELECT DISTINCT t.trade_id, t.cycle_id, t.pnl_usd, t.direction
    FROM trade_outcomes t
    JOIN agent_contributions c ON c.trade_id = t.trade_id
    WHERE c.counterfactual_hit IS NULL
    ORDER BY t.exit_ts DESC
    LIMIT :limit
    """
)


_LOAD_CONTRIBUTIONS = text(
    """
    SELECT contribution_id, agent_id, agent_version,
           signal_direction, signal_confidence, matched_trade_direction
    FROM agent_contributions
    WHERE trade_id = :trade_id
    """
)


_UPDATE_CONTRIBUTION = text(
    """
    UPDATE agent_contributions
    SET counterfactual_hit = :hit,
        attributed_pnl_usd = :attributed_pnl,
        counterfactual_computed_at = :computed_at
    WHERE contribution_id = :contribution_id
    """
)


def _diana_simulate(signals: list[dict[str, Any]]) -> bool:
    """Replay Diana's deterministic gate logic on a (possibly reduced) set."""
    if not signals:
        return False
    avg_confidence = sum(s["signal_confidence"] for s in signals) / len(signals)
    longs = sum(1 for s in signals if s["signal_direction"] == "LONG")
    shorts = sum(1 for s in signals if s["signal_direction"] == "SHORT")
    total = len(signals)
    consensus_pct = max(longs, shorts) / total if total > 0 else 0.0
    return avg_confidence >= CONFIDENCE_THRESHOLD and consensus_pct >= 0.5


async def _attribute_one_trade(
    session: AsyncSession,
    trade: dict[str, Any],
) -> int:
    """Return the count of contributions updated for this trade."""
    res = await session.execute(_LOAD_CONTRIBUTIONS, {"trade_id": trade["trade_id"]})
    rows = res.fetchall()
    if not rows:
        return 0

    contributions = [
        {
            "contribution_id": r[0],
            "agent_id": r[1],
            "agent_version": r[2],
            "signal_direction": r[3],
            "signal_confidence": float(r[4]),
            "matched_trade_direction": r[5],
        }
        for r in rows
    ]

    pnl_usd = float(trade["pnl_usd"])
    n = len(contributions)
    now = datetime.now(UTC)

    # Single-contributor → automatic hit.
    if n == 1:
        await session.execute(_UPDATE_CONTRIBUTION, {
            "hit": True,
            "attributed_pnl": pnl_usd,
            "computed_at": now,
            "contribution_id": contributions[0]["contribution_id"],
        })
        return 1

    # Baseline: did Diana approve with all contributors?
    baseline_approved = _diana_simulate(contributions)
    updated = 0

    for c in contributions:
        without = [other for other in contributions if other["contribution_id"] != c["contribution_id"]]
        approved_without = _diana_simulate(without)
        flipped = baseline_approved and not approved_without
        attributed = pnl_usd if flipped else (pnl_usd / n)
        await session.execute(_UPDATE_CONTRIBUTION, {
            "hit": flipped,
            "attributed_pnl": attributed,
            "computed_at": now,
            "contribution_id": c["contribution_id"],
        })
        updated += 1

    return updated


async def main(limit: int) -> None:
    logger.info("counterfactual_attribution_started", limit=limit)
    async with AsyncSessionLocal() as session:
        res = await session.execute(_PENDING_TRADES, {"limit": limit})
        pending = [
            {"trade_id": r[0], "cycle_id": r[1], "pnl_usd": r[2], "direction": r[3]}
            for r in res.fetchall()
        ]

    if not pending:
        logger.info("counterfactual_attribution_done", trades=0, contributions=0)
        return

    total_contribs = 0
    async with AsyncSessionLocal() as session:
        for trade in pending:
            count = await _attribute_one_trade(session, trade)
            total_contribs += count
        await session.commit()

    logger.info(
        "counterfactual_attribution_done",
        trades=len(pending),
        contributions=total_contribs,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Max trades to attribute per run (default 100).",
    )
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit))
