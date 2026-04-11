"""
EIA Analyst Agent — weekly government report surprise detector.

Activation schedule (Eastern Time):
  Wednesday 10:30 AM ET → EIA Weekly Petroleum Status Report (crude, gasoline, distillates)
  Thursday  10:30 AM ET → EIA Natural Gas Storage Report

This agent is TIME-GATED: it only activates within ±4 hours of each release.
On non-release days (or outside the time window), it returns state unchanged.
This prevents the agent from injecting stale EIA data as a live signal.

Signal logic:
  z_score > +1.5  → BULL  (drawdown larger than 4-week rolling avg — tighter supply)
  z_score < -1.5  → BEAR  (build larger than 4-week rolling avg — looser supply)
  |z_score| ≤ 1.5 → NEUTRAL (within normal variation, no edge)

Why 1.5 sigma?
  Crude oil moves > 1% on release day in ~8% of EIA reports.
  A 1.5-sigma threshold captures ~93% of those move sessions while
  filtering the ~85% of reports that produce < 0.5% price moves.

Relevant symbols:
  CL=F  (crude) → activated on Wednesdays
  NG=F  (natgas) → activated on Thursdays
  BZ=F, HO=F follow crude (same Wednesday report)
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from src.agents.base import BaseAgent, AgentState
from src.data.feeds.eia_feed import EIAFeed

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
EIA_RELEASE_HOUR = 10      # 10:30 AM ET
EIA_RELEASE_MINUTE = 30
ACTIVATION_WINDOW_HOURS = 4  # ±4 hours around release time

# Wednesday report — crude / petroleum status
CRUDE_SYMBOLS = {"CL=F", "BZ=F", "HO=F"}
# Thursday report — natural gas storage
NATGAS_SYMBOLS = {"NG=F"}
ALL_EIA_SYMBOLS = CRUDE_SYMBOLS | NATGAS_SYMBOLS


class EIAAnalystAgent(BaseAgent):
    """
    EIA government report surprise detector.

    Emits high-confidence signals on report release days when the actual
    inventory change materially surprises vs the rolling 4-week baseline.
    Silent (pass-through) on all other days/symbols.
    """

    def __init__(self) -> None:
        super().__init__("eia_analyst", "EIA Analyst", "Energy Report Specialist")
        self._feed = EIAFeed()

    async def analyze(self, state: AgentState) -> AgentState:
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "")

        if symbol not in ALL_EIA_SYMBOLS:
            return state  # Not an EIA-tracked energy contract

        now_et = datetime.now(ET)
        report_type = _get_active_report(symbol, now_et)

        if report_type is None:
            logger.debug("eia_analyst_skip symbol=%s not_release_window", symbol)
            return state  # Outside release window — no stale signal injection

        logger.info("eia_analyst_active symbol=%s report=%s", symbol, report_type)

        if report_type == "petroleum":
            report = await self._feed.get_petroleum_report()
        else:
            report = await self._feed.get_natgas_report()

        if not report.get("available"):
            logger.warning("eia_report_unavailable symbol=%s reason=%s",
                           symbol, report.get("reason"))
            return state

        return await self._build_signal(state, symbol, report, report_type)

    # ------------------------------------------------------------------
    # Async signal construction — must be async to call emit_signal
    # ------------------------------------------------------------------

    async def _build_signal(
        self,
        state: AgentState,
        symbol: str,
        report: dict[str, Any],
        report_type: str,
    ) -> AgentState:
        """Build and emit a trading signal from the EIA report surprise."""
        z_score = float(report.get("surprise_z_score", 0.0))
        abs_z = abs(z_score)

        # Map z-score magnitude to confidence
        # z=1.5 → 0.65  |  z=2.0 → 0.80  |  z=3.0 → 0.95
        if abs_z >= 3.0:
            confidence = 0.95
        elif abs_z >= 2.0:
            confidence = 0.80
        elif abs_z >= 1.5:
            confidence = 0.65
        else:
            confidence = 0.35  # Below threshold — weak signal

        # Direction: only assert directional view above threshold
        raw_direction = report.get("direction", "NEUTRAL")
        direction = raw_direction if abs_z >= 1.5 else "NEUTRAL"

        # Build human-readable thesis
        if report_type == "petroleum":
            thesis = _petroleum_thesis(report, z_score)
        else:
            thesis = _natgas_thesis(report, z_score)

        await self.emit_signal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            strategy="eia_report_surprise",
        )

        updated = dict(state)
        updated["signals"] = list(state.get("signals", [])) + [{
            "agent": self.name,
            "direction": direction,
            "confidence": confidence,
            "thesis": thesis,
            "strategy": "eia_report_surprise",
            "symbol": symbol,
            "report_type": report_type,
            "z_score": z_score,
            "released_at": report.get("released_at", ""),
        }]
        return AgentState(**updated)

    async def close(self) -> None:
        await self._feed.close()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _get_active_report(symbol: str, now_et: datetime) -> str | None:
    """
    Return 'petroleum' or 'natgas' if we are within the activation window
    for that symbol's release day, otherwise None.

    Wednesday (weekday=2) → petroleum report (crude, gasoline, distillate)
    Thursday  (weekday=3) → natgas storage report
    """
    weekday = now_et.weekday()   # 0=Mon, 2=Wed, 3=Thu
    release_dt = now_et.replace(
        hour=EIA_RELEASE_HOUR, minute=EIA_RELEASE_MINUTE, second=0, microsecond=0
    )
    hours_from_release = abs((now_et - release_dt).total_seconds() / 3600)

    if symbol in CRUDE_SYMBOLS and weekday == 2:
        return "petroleum" if hours_from_release <= ACTIVATION_WINDOW_HOURS else None
    if symbol in NATGAS_SYMBOLS and weekday == 3:
        return "natgas" if hours_from_release <= ACTIVATION_WINDOW_HOURS else None
    return None


def _petroleum_thesis(report: dict[str, Any], z_score: float) -> str:
    """Build thesis string for a petroleum surprise."""
    crude = report.get("crude", {})
    change = crude.get("change")
    stocks = crude.get("latest_stocks_mbbl")
    headline = report.get("headline_series", "crude")
    change_str = f"{change:+,.0f} Mbbl" if change is not None else "N/A"
    stocks_str = f"{stocks:,.0f} Mbbl" if stocks is not None else "N/A"
    thesis = (
        f"EIA Petroleum Report: crude inventory change {change_str} "
        f"(z={z_score:+.2f} vs 4-week avg). "
        f"Total US crude stocks: {stocks_str}."
    )
    if headline != "crude":
        other_z = report.get(headline, {}).get("z_score", 0.0)
        if abs(other_z) > 1.5:
            thesis += f" Largest surprise in {headline} (z={other_z:+.2f})."
    return thesis


def _natgas_thesis(report: dict[str, Any], z_score: float) -> str:
    """Build thesis string for a natgas storage surprise."""
    change = report.get("weekly_change_bcf")
    working = report.get("working_gas_bcf")
    vs_5yr = report.get("storage_vs_5yr_bcf")
    change_str = f"{change:+.0f} Bcf" if change is not None else "N/A"
    gas_str = f"{working:,.0f} Bcf" if working is not None else "N/A"
    thesis = (
        f"EIA NatGas Storage: weekly change {change_str} "
        f"(z={z_score:+.2f} vs 4-week avg). "
        f"Working gas: {gas_str}."
    )
    if vs_5yr is not None:
        label = "surplus" if vs_5yr > 0 else "deficit"
        thesis += f" Storage {label} vs 5-yr avg: {vs_5yr:+.0f} Bcf."
    return thesis
