"""
USDA WASDE (World Agricultural Supply and Demand Estimates).
Released monthly. Major market-moving event for corn, wheat, soybeans.
Free access via USDA's public PSD (Production, Supply and Distribution) API.

API base: https://apps.fas.usda.gov/psdonline/api/home
No API key required — fully public endpoints.

WASDE surprise detection:
  Compare latest monthly estimate for key metrics (ending stocks, production)
  vs prior month. Large revision → market-moving surprise.
  ending_stocks_change_pct > +5% → bearish (more supply than expected)
  ending_stocks_change_pct < -5% → bullish (tighter supply)

Ticker mapping:
  Corn      → ZC=F
  Wheat     → ZW=F
  Soybeans  → ZS=F
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# USDA PSD Online API — public, no auth required
USDA_PSD_BASE = "https://apps.fas.usda.gov/psdonline/api/home"
USDA_PSD_DATA_URL = "https://apps.fas.usda.gov/psdonline/api/psd/commodity"

# USDA commodity codes for the PSD database
USDA_COMMODITIES: dict[str, dict[str, str]] = {
    "ZC=F": {"name": "Corn", "usda_code": "0440000", "unit": "1000 MT"},
    "ZW=F": {"name": "Wheat", "usda_code": "0410000", "unit": "1000 MT"},
    "ZS=F": {"name": "Soybeans", "usda_code": "2222000", "unit": "1000 MT"},
}

# Attribute IDs for WASDE supply/demand components
USDA_ATTRS: dict[str, str] = {
    "production":     "Production",
    "imports":        "Imports",
    "exports":        "Exports",
    "ending_stocks":  "Ending Stocks",
    "total_supply":   "Total Supply",
    "total_use":      "Total Use/Disappearance",
}

# Country code for world aggregate
WORLD_COUNTRY_CODE = "00"


class USDAFeed:
    """
    USDA WASDE supply/demand feed for corn, wheat, and soybeans.

    Uses the USDA PSD Online API (no key required).
    Detects month-over-month revisions to ending stocks as the primary
    surprise signal — ending stocks are the single most watched WASDE number.

    Positive ending stocks revision → bearish (more supply = lower prices)
    Negative ending stocks revision → bullish (less supply = higher prices)
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=20.0,
            headers={"Accept": "application/json"},
        )

    # ------------------------------------------------------------------
    # Internal: fetch PSD data for one commodity
    # ------------------------------------------------------------------

    async def _fetch_commodity_data(
        self,
        usda_code: str,
        market_year: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch USDA PSD world balance sheet for a commodity code.
        Returns list of attribute rows with marketYear and value fields.
        """
        if market_year is None:
            market_year = datetime.now(UTC).year

        try:
            # PSD API: /commodity/{commodityCode}/country/{countryCode}/data
            url = f"{USDA_PSD_DATA_URL}/{usda_code}/country/{WORLD_COUNTRY_CODE}/data"
            params = {"marketYear": market_year}
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            return resp.json() or []
        except Exception as exc:
            logger.warning("usda_psd_fetch_error code=%s err=%s", usda_code, exc)
            return []

    # ------------------------------------------------------------------
    # Internal: parse PSD rows into a clean supply/demand dict
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_balance_sheet(rows: list[dict]) -> dict[str, Any]:
        """
        Collapse flat PSD attribute rows into a supply/demand balance sheet.
        Returns {production, ending_stocks, exports, imports, total_use, ...}
        keyed by month (calendarYear + month) for comparison.
        """
        monthly: dict[str, dict[str, Any]] = {}
        for row in rows:
            attr = row.get("attributeName", "").strip()
            val = row.get("value")
            month_key = f"{row.get('calendarYear', '')}-{str(row.get('month', '')).zfill(2)}"
            if month_key not in monthly:
                monthly[month_key] = {"month_key": month_key}
            if val is not None:
                # Normalise attribute name to snake_case key
                clean_attr = (attr.lower()
                              .replace("/", "_")
                              .replace(" ", "_")
                              .replace("__", "_"))
                monthly[month_key][clean_attr] = float(val)
        # Return as list sorted newest first
        return {
            "by_month": dict(sorted(monthly.items(), reverse=True)),
        }

    # ------------------------------------------------------------------
    # Internal: compute month-over-month surprise for a commodity
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_wasde_surprise(
        balance_sheet: dict[str, Any],
        symbol: str,
        commodity_name: str,
    ) -> dict[str, Any]:
        """
        Compare the two most recent monthly WASDE estimates for ending stocks.
        Returns a signal dict with direction, surprise_pct, and reasoning.
        """
        by_month = balance_sheet.get("by_month", {})
        months = list(by_month.keys())
        if len(months) < 2:
            return {
                "symbol": symbol,
                "available": False,
                "reason": "Insufficient monthly data for comparison",
            }

        latest_month = by_month[months[0]]
        prior_month = by_month[months[1]]

        latest_stocks = latest_month.get("ending_stocks")
        prior_stocks = prior_month.get("ending_stocks")
        latest_production = latest_month.get("production")
        prior_production = prior_month.get("production")

        if latest_stocks is None or prior_stocks is None or prior_stocks == 0:
            return {
                "symbol": symbol, "available": False,
                "reason": "Ending stocks data not available in PSD response",
            }

        # Month-over-month revision to ending stocks
        stocks_change = latest_stocks - prior_stocks
        stocks_change_pct = (stocks_change / prior_stocks) * 100

        # Signal thresholds: ±5% ending stocks revision is market-moving
        if stocks_change_pct < -5.0:
            direction = "BULL"    # Less supply than last month's estimate
            signal_strength = min(abs(stocks_change_pct) / 10.0, 1.0)
        elif stocks_change_pct > 5.0:
            direction = "BEAR"    # More supply than last month's estimate
            signal_strength = min(abs(stocks_change_pct) / 10.0, 1.0)
        else:
            direction = "NEUTRAL"
            signal_strength = 0.0

        reasoning = (
            f"USDA revised {commodity_name} world ending stocks "
            f"{stocks_change_pct:+.1f}% vs prior month "
            f"({latest_stocks:,.0f} vs {prior_stocks:,.0f} thousand MT). "
        )
        if direction == "BULL":
            reasoning += "Tighter supply than expected — bullish for futures."
        elif direction == "BEAR":
            reasoning += "More supply than expected — bearish for futures."
        else:
            reasoning += "Revision within normal range — no significant surprise."

        result: dict[str, Any] = {
            "symbol": symbol,
            "commodity": commodity_name,
            "available": True,
            "direction": direction,
            "confidence": round(signal_strength, 3),
            "ending_stocks_latest": latest_stocks,
            "ending_stocks_prior": prior_stocks,
            "stocks_change_pct": round(stocks_change_pct, 2),
            "latest_month": months[0],
            "prior_month": months[1],
            "reasoning": reasoning,
        }

        # Add production revision if available
        if latest_production and prior_production and prior_production != 0:
            prod_change_pct = (latest_production - prior_production) / prior_production * 100
            result["production_change_pct"] = round(prod_change_pct, 2)

        return result

    # ------------------------------------------------------------------
    # Public: fetch WASDE signals for all three ag commodities
    # ------------------------------------------------------------------

    async def get_wasde_signals(self) -> list[dict[str, Any]]:
        """
        Return WASDE supply/demand surprise signals for corn, wheat, and soybeans.

        Each dict contains:
          symbol            ZC=F / ZW=F / ZS=F
          commodity         human name
          available         bool
          direction         BULL / BEAR / NEUTRAL
          confidence        0.0-1.0 (based on magnitude of revision)
          ending_stocks_*   raw values (thousand MT)
          stocks_change_pct month-over-month ending stocks revision (%)
          production_change_pct optional, production revision (%)
          reasoning         human-readable explanation
        """
        import asyncio
        current_year = datetime.now(UTC).year

        tasks = {
            symbol: self._fetch_commodity_data(meta["usda_code"], current_year)
            for symbol, meta in USDA_COMMODITIES.items()
        }

        raw_results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        signals: list[dict[str, Any]] = []

        for symbol, raw in zip(tasks.keys(), raw_results):
            meta = USDA_COMMODITIES[symbol]
            if isinstance(raw, Exception) or not raw:
                signals.append({
                    "symbol": symbol,
                    "commodity": meta["name"],
                    "available": False,
                    "reason": str(raw) if isinstance(raw, Exception) else "No data returned",
                })
                continue

            balance_sheet = self._parse_balance_sheet(raw)
            signal = self._compute_wasde_surprise(balance_sheet, symbol, meta["name"])
            signals.append(signal)

        return signals

    async def close(self) -> None:
        await self._http.aclose()
