"""
MomentumAgent — cross-sectional price momentum signal generator.

Pure math, no LLM.  Computes momentum score from recent price returns
using a short (5-bar) vs medium (20-bar) lookback — a practical proxy for
the classic Jegadeesh & Titman 12-1 momentum in intraday/short cycles.

Signal logic:
  momentum_score > +0.02  →  LONG   (recent bars outpacing medium lookback)
  momentum_score < -0.02  →  SHORT  (recent bars lagging medium lookback)
  |momentum_score| ≤ 0.02 →  NEUTRAL (no edge — agent stays silent)

Confidence = min(|momentum_score| / 0.10, 0.85)
  — capped at 85%: momentum alone never delivers full conviction.

Regime gate:
  Skips signal emission in VOLATILE regime.
  Momentum strategies fail (crash/gap risk) during volatility spikes.
"""
from __future__ import annotations

import structlog

from src.agents.base import AgentState, BaseAgent

logger = structlog.get_logger()

LONG_THRESHOLD  = 0.02   # 2% return advantage  → emit LONG
SHORT_THRESHOLD = -0.02  # -2% return advantage → emit SHORT
MAX_CONFIDENCE  = 0.85   # cap — momentum alone isn't full conviction
CONF_NORMALIZER = 0.10   # 10% spread → max confidence
