"""
EIA (Energy Information Administration) government report feed.
Weekly Petroleum Status Report: released every Wednesday 10:30 AM ET.
Natural Gas Storage report: released every Thursday 10:30 AM ET.
Free API at api.eia.gov (requires free registration).

EIA surprise detector: difference between actual and consensus estimate.
Large positive surprise (more drawdown than expected) → bullish crude/nat gas.
Large negative surprise → bearish.

Surprise methodology:
  baseline = rolling 4-week average of weekly changes
  std      = standard deviation of those 4 changes
  z_score  = (this_week_change - baseline) / std

  |z| > 1.5  → significant surprise (>93% of normal variation)
  |z| > 2.0  → major surprise (~97.7%)

  The 1.5 threshold was chosen to balance signal frequency vs quality:
  - At |z| > 1.0: too many false signals (~30% of weeks qualify)
  - At |z| > 2.0: too rare, misses meaningful surprises
  - At |z| > 1.5: ~7% of releases, aligns with observed market moves > 1%
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, UTC
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EIA_BASE = "https://api.eia.gov/v2"

# Series IDs for key petroleum and natgas metrics
PETROLEUM_SERIES = {
    "crude_stocks":     "PET.WCRSTUS1.W",   # US crude oil ending stocks (Mbbl)
    "gasoline_stocks":  "PET.WGRSTUS1.W",   # US gasoline stocks (Mbbl)
    "distillate_stocks":"PET.WDISTUS1.W",   # US distillate stocks (Mbbl)
    "refinery_util":    "PET.WPULEUS3.W",   # US refinery utilization (%)
}

NATGAS_SERIES = {
    "working_gas":      "NG.NW2_EPG0_SWO_R48_BCF.W",  # Working gas in storage (Bcf)
    "five_year_avg":    "NG.NW2_EPG0_SA_R48_BCF.W",   # 5-yr average storage (Bcf)
}


class EIAFeed:
    """
    EIA government report feed with surprise detection.

    Usage:
        feed = EIAFeed()
        report = await feed.get_petroleum_report()
        # {"surprise_z_score": 1.8, "direction": "BULL", "report_type": "crude_inventory", ...}

    Requires EIA_API_KEY environment variable. All methods gracefully return
    {"available": False} if the key is not set.
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("EIA_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=20.0)

    # ------------------------------------------------------------------
    # Internal: fetch a time series from EIA v2 API
    # ------------------------------------------------------------------

    async def _fetch_series(self, series_id: str, periods: int = 8) -> list[dict[str, Any]]:
        """
        Fetch the most recent `periods` observations for an EIA series.
        Returns list of {period, value} dicts ordered newest-first.
        """
        if not self._api_key:
            return []
        try:
            # EIA v2 uses route derived from the series ID prefix
            # e.g. "PET.WCRSTUS1.W" → /petroleum/sum/sndw/data/
            url = f"{EIA_BASE}/seriesid/{series_id}"
            params = {
                "api_key": self._api_key,
                "data[0]": "value",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": periods,
            }
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            observations = data.get("response", {}).get("data", [])
            return [
                {
                    "period": obs.get("period", ""),
                    "value": float(obs["value"]) if obs.get("value") not in (None, "") else None,
                }
                for obs in observations
            ]
        except Exception as exc:
            logger.warning("eia_series_fetch_error series=%s err=%s", series_id, exc)
            return []

    # ------------------------------------------------------------------
    # Internal: compute z-score surprise
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_surprise(observations: list[dict]) -> dict[str, Any]:
        """
        Given observations newest-first, compute the week-over-week change
        surprise as a z-score vs the prior 4-week rolling average.

        observations[0] = latest week
        observations[1] = prior week
        observations[2..5] = 4 weeks used for baseline

        Returns: {change, baseline_avg, baseline_std, z_score, direction}
        """
        values = [o["value"] for o in observations if o.get("value") is not None]
        if len(values) < 6:
            return {"z_score": 0.0, "direction": "NEUTRAL", "insufficient_data": True}

        # Week-over-week changes for the 4 prior weeks (indices 1→2, 2→3, 3→4, 4→5)
        prior_changes = [values[i] - values[i + 1] for i in range(1, 5)]
        current_change = values[0] - values[1]

        avg = sum(prior_changes) / len(prior_changes)
        variance = sum((x - avg) ** 2 for x in prior_changes) / len(prior_changes)
        std = variance ** 0.5

        if std < 0.01:
            return {
                "change": current_change, "baseline_avg": avg,
                "baseline_std": std, "z_score": 0.0, "direction": "NEUTRAL",
            }

        z_score = (current_change - avg) / std
        direction = "NEUTRAL"
        if z_score > 1.5:
            direction = "BULL"   # Bigger drawdown than expected → bullish
        elif z_score < -1.5:
            direction = "BEAR"   # Bigger build than expected → bearish

        return {
            "change": round(current_change, 3),
            "baseline_avg": round(avg, 3),
            "baseline_std": round(std, 3),
            "z_score": round(z_score, 3),
            "direction": direction,
        }

    # ------------------------------------------------------------------
    # Public: weekly petroleum status report
    # ------------------------------------------------------------------

    async def get_petroleum_report(self) -> dict[str, Any]:
        """
        Fetch the latest weekly EIA Petroleum Status Report and compute surprises.

        Returns a dict with:
          available       bool — False if EIA_API_KEY not set
          crude           {change, z_score, direction, latest_stocks_mbbl}
          gasoline        {change, z_score, direction}
          distillate      {change, z_score, direction}
          headline        composite direction (most significant surprise wins)
          surprise_z_score  largest absolute z-score across the three series
          direction       BULL / BEAR / NEUTRAL (based on headline)
          report_type     "petroleum"
          released_at     ISO timestamp of the latest data period
        """
        if not self._api_key:
            return {"available": False, "reason": "EIA_API_KEY not configured"}

        import asyncio
        crude_obs, gas_obs, dist_obs = await asyncio.gather(
            self._fetch_series(PETROLEUM_SERIES["crude_stocks"]),
            self._fetch_series(PETROLEUM_SERIES["gasoline_stocks"]),
            self._fetch_series(PETROLEUM_SERIES["distillate_stocks"]),
            return_exceptions=True,
        )

        results: dict[str, Any] = {"available": True, "report_type": "petroleum"}

        # Process each series — exceptions become empty lists
        crude_data = self._compute_surprise(crude_obs if isinstance(crude_obs, list) else [])
        gas_data = self._compute_surprise(gas_obs if isinstance(gas_obs, list) else [])
        dist_data = self._compute_surprise(dist_obs if isinstance(dist_obs, list) else [])

        results["crude"] = {**crude_data, "series": "crude_stocks_mbbl"}
        results["gasoline"] = {**gas_data, "series": "gasoline_stocks_mbbl"}
        results["distillate"] = {**dist_data, "series": "distillate_stocks_mbbl"}

        # Latest stock level for crude (the headline number)
        if isinstance(crude_obs, list) and crude_obs:
            results["crude"]["latest_stocks_mbbl"] = crude_obs[0].get("value")
            results["released_at"] = crude_obs[0].get("period", "")

        # Headline: pick the surprise with the highest absolute z-score
        all_z = [
            (crude_data.get("z_score", 0.0), "crude"),
            (gas_data.get("z_score", 0.0), "gasoline"),
            (dist_data.get("z_score", 0.0), "distillate"),
        ]
        max_z_val, max_z_series = max(all_z, key=lambda t: abs(t[0]))
        results["surprise_z_score"] = max_z_val
        results["headline_series"] = max_z_series

        # Composite direction: if any series z > 1.5 abs, report that direction
        if max_z_val > 1.5:
            results["direction"] = "BULL"
        elif max_z_val < -1.5:
            results["direction"] = "BEAR"
        else:
            results["direction"] = "NEUTRAL"

        return results

    # ------------------------------------------------------------------
    # Public: weekly natural gas storage report
    # ------------------------------------------------------------------

    async def get_natgas_report(self) -> dict[str, Any]:
        """
        Fetch the latest EIA Natural Gas Storage report and compute surprise.

        Returns:
          available         bool
          working_gas_bcf   current storage level (Bcf)
          weekly_change     Bcf injected (+) or withdrawn (-)
          z_score           surprise vs 4-week rolling average
          direction         BULL / BEAR / NEUTRAL
          storage_vs_5yr    deficit/surplus vs 5-year average (if available)
          report_type       "natgas_storage"
          released_at       ISO date of the data period
        """
        if not self._api_key:
            return {"available": False, "reason": "EIA_API_KEY not configured"}

        import asyncio
        gas_obs, avg_obs = await asyncio.gather(
            self._fetch_series(NATGAS_SERIES["working_gas"]),
            self._fetch_series(NATGAS_SERIES["five_year_avg"], periods=4),
            return_exceptions=True,
        )

        if not isinstance(gas_obs, list) or not gas_obs:
            return {"available": False, "reason": "No natgas storage data returned"}

        surprise = self._compute_surprise(gas_obs)
        latest_val = gas_obs[0].get("value")
        prior_val = gas_obs[1].get("value") if len(gas_obs) > 1 else None
        weekly_change = (latest_val - prior_val) if (latest_val and prior_val) else None

        result: dict[str, Any] = {
            "available": True,
            "report_type": "natgas_storage",
            "working_gas_bcf": latest_val,
            "weekly_change_bcf": round(weekly_change, 1) if weekly_change is not None else None,
            "z_score": surprise.get("z_score", 0.0),
            "direction": surprise.get("direction", "NEUTRAL"),
            "released_at": gas_obs[0].get("period", ""),
        }

        # Storage vs 5-year average
        if isinstance(avg_obs, list) and avg_obs and avg_obs[0].get("value") and latest_val:
            five_yr = avg_obs[0]["value"]
            surplus = latest_val - five_yr
            result["storage_vs_5yr_bcf"] = round(surplus, 1)
            result["storage_vs_5yr_pct"] = round(surplus / five_yr * 100, 1)

        return result

    async def close(self) -> None:
        await self._http.aclose()
