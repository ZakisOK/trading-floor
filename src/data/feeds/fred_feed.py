"""
FRED (Federal Reserve Economic Data) macro feed.
Free API from St. Louis Fed — comprehensive macro data.
Register at fred.stlouisfed.org for a free API key.

Why this matters: macro conditions govern ALL markets.
Oil → inflation → Fed → rates → all asset prices.
Detecting these cascades 1-4 weeks early is the edge macro funds have.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Series registry — every series we track and why
# ---------------------------------------------------------------------------
FRED_SERIES: dict[str, dict[str, str]] = {
    "DGS10": {
        "name": "10-Year Treasury Yield",
        "category": "rates",
        "note": "Risk-free rate. Rising = headwind for equities/crypto/gold.",
    },
    "DGS2": {
        "name": "2-Year Treasury Yield",
        "category": "rates",
        "note": "Most Fed-sensitive rate. Leads DGS10 on rate expectations.",
    },
    "T10Y2Y": {
        "name": "10Y-2Y Treasury Spread (Yield Curve)",
        "category": "rates",
        "note": "Inverted (negative) = recession signal. Most reliable leading indicator.",
    },
    "DEXUSEU": {
        "name": "USD/EUR Exchange Rate",
        "category": "fx",
        "note": "USD strength = headwind for commodities and crypto priced in USD.",
    },
    "VIXCLS": {
        "name": "CBOE VIX Volatility Index",
        "category": "risk",
        "note": "Fear gauge. VIX > 25 = risk-off. Spikes hurt crypto/commodities short-term.",
    },
    "DCOILWTICO": {
        "name": "WTI Crude Oil Price",
        "category": "commodities",
        "note": "Feeds into CPI with 6-8 week lag. Oil up = inflation up = Fed hawkish.",
    },
    "CPIAUCSL": {
        "name": "CPI All Urban Consumers",
        "category": "inflation",
        "note": "Monthly. Trend matters more than level. Rising = Fed hawkish = risk-off.",
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "category": "labor",
        "note": "Low unemployment = Fed less likely to cut. Rising = risk-off signal.",
    },
}

# Thresholds used in regime detection
VIX_RISK_OFF = 25.0
VIX_RISK_ON = 20.0
YIELD_CURVE_INVERTED = 0.0   # T10Y2Y < 0 = inverted
OIL_CASCADE_THRESHOLD = 5.0  # % move in 2 weeks to trigger cascade signal


class FREDFeed:
    """
    Federal Reserve Economic Data feed.

    All methods are async and degrade gracefully when FRED_API_KEY is absent.
    FRED data updates at different frequencies — daily for market-based series
    (VIX, yields, FX), monthly for CPI/unemployment.
    """

    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self) -> None:
        self._api_key = os.getenv("FRED_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=15.0)

    # ------------------------------------------------------------------
    # Core fetcher
    # ------------------------------------------------------------------

    async def get_series(self, series_id: str, limit: int = 20) -> list[dict]:
        """
        Fetch the most recent observations for any FRED series.

        Returns list of {date, value} dicts sorted newest-first.
        Returns empty list when API key is missing or request fails.
        """
        if not self._api_key:
            logger.debug("FRED_API_KEY not set — skipping series %s", series_id)
            return []

        try:
            resp = await self._http.get(self.BASE_URL, params={
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
                "observation_start": (
                    datetime.now() - timedelta(days=90)
                ).strftime("%Y-%m-%d"),
            })
            resp.raise_for_status()
            raw = resp.json().get("observations", [])
            # Filter out missing values (FRED uses "." for no data)
            return [
                {"date": o["date"], "value": float(o["value"])}
                for o in raw
                if o.get("value") not in (".", None, "")
            ]
        except httpx.HTTPError as exc:
            logger.warning("fred_http_error series=%s err=%s", series_id, exc)
            return []
        except Exception as exc:
            logger.warning("fred_parse_error series=%s err=%s", series_id, exc)
            return []

    async def _latest_and_change(self, series_id: str) -> dict[str, Any]:
        """
        Fetch latest value and 1-month change for a series.
        Returns {series_id, name, latest, date, change_1m, change_pct_1m}.
        """
        obs = await self.get_series(series_id, limit=35)
        meta = FRED_SERIES.get(series_id, {"name": series_id, "category": "unknown", "note": ""})
        if not obs:
            return {
                "series_id": series_id,
                "name": meta["name"],
                "available": False,
            }

        latest_val = obs[0]["value"]
        latest_date = obs[0]["date"]

        # Find observation ~21 trading days ago (approx 1 month)
        month_ago = obs[min(21, len(obs) - 1)]["value"]
        change_1m = round(latest_val - month_ago, 4)
        change_pct_1m = round((change_1m / month_ago * 100) if month_ago else 0.0, 3)

        # 2-week lookback for short-term cascade detection
        two_weeks = obs[min(10, len(obs) - 1)]["value"]
        change_2w = round(latest_val - two_weeks, 4)
        change_pct_2w = round((change_2w / two_weeks * 100) if two_weeks else 0.0, 3)

        return {
            "series_id": series_id,
            "name": meta["name"],
            "category": meta["category"],
            "note": meta["note"],
            "available": True,
            "latest": latest_val,
            "date": latest_date,
            "change_1m": change_1m,
            "change_pct_1m": change_pct_1m,
            "change_2w": change_2w,
            "change_pct_2w": change_pct_2w,
        }

    # ------------------------------------------------------------------
    # Macro snapshot — the primary interface for other agents
    # ------------------------------------------------------------------

    async def get_macro_snapshot(self) -> dict[str, Any]:
        """
        Fetch all key FRED series concurrently and return a unified snapshot.

        Returns a dict keyed by series_id with latest value, 1-month change,
        and a top-level summary of current macro regime.
        """
        tasks = [
            self._latest_and_change(sid)
            for sid in FRED_SERIES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        snapshot: dict[str, Any] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("fred_snapshot_error err=%s", result)
                continue
            if isinstance(result, dict):
                snapshot[result["series_id"]] = result

        # Pull key values for convenience
        vix = snapshot.get("VIXCLS", {}).get("latest")
        yield_curve = snapshot.get("T10Y2Y", {}).get("latest")
        dgs10 = snapshot.get("DGS10", {}).get("latest")
        dgs2 = snapshot.get("DGS2", {}).get("latest")
        oil = snapshot.get("DCOILWTICO", {}).get("latest")
        cpi_change = snapshot.get("CPIAUCSL", {}).get("change_1m")

        snapshot["_summary"] = {
            "vix": vix,
            "yield_curve_spread": yield_curve,
            "rate_10y": dgs10,
            "rate_2y": dgs2,
            "oil_price": oil,
            "cpi_monthly_change": cpi_change,
            "regime": self._classify_regime(vix, yield_curve),
            "fetched_at": datetime.utcnow().isoformat(),
        }
        return snapshot

    # ------------------------------------------------------------------
    # Risk regime classification
    # ------------------------------------------------------------------

    def _classify_regime(
        self,
        vix: float | None,
        yield_curve: float | None,
    ) -> str:
        """Internal regime logic — used by get_risk_regime."""
        if vix is None and yield_curve is None:
            return "UNKNOWN"

        risk_off_signals = 0
        risk_on_signals = 0

        if vix is not None:
            if vix > VIX_RISK_OFF:
                risk_off_signals += 2   # Strong signal — double weight
            elif vix < VIX_RISK_ON:
                risk_on_signals += 1

        if yield_curve is not None:
            if yield_curve < YIELD_CURVE_INVERTED:
                risk_off_signals += 1
            elif yield_curve > 0.5:
                risk_on_signals += 1

        if risk_off_signals >= 2:
            return "RISK_OFF"
        if risk_on_signals >= 2:
            return "RISK_ON"
        return "NEUTRAL"

    async def get_risk_regime(self) -> str:
        """
        Returns current macro risk regime: RISK_ON / RISK_OFF / NEUTRAL.

        RISK_ON:  VIX < 20, yield curve positive — markets are calm and growing.
        RISK_OFF: VIX > 25 OR yield curve inverted — defensive positioning warranted.
        NEUTRAL:  Mixed signals — no clear directional macro bias.
        """
        snapshot = await self.get_macro_snapshot()
        return snapshot.get("_summary", {}).get("regime", "UNKNOWN")

    # ------------------------------------------------------------------
    # Cascade signal detection — the macro edge
    # ------------------------------------------------------------------

    async def get_cascade_signals(self) -> list[dict]:
        """
        Detect macro cascade patterns that typically precede cross-asset moves.

        Cascades are slow-moving (1-4 weeks), but early detection is the edge.

        Pattern 1 — Oil-Inflation-Fed:
          Oil up >5% in 2 weeks AND CPI trending up → expect Fed hawkishness
          → short rate-sensitive assets (long-duration bonds, crypto, growth equities)

        Pattern 2 — VIX Spike:
          VIX jumps sharply → crypto and commodities sell off initially,
          then recover (usually 2-3 weeks). Gold often rallies in spike.

        Pattern 3 — Yield Curve Inversion:
          T10Y2Y goes negative → reduce equity and high-risk exposure.
          Recession typically follows 3-18 months later (long lead time).

        Pattern 4 — Rate Squeeze:
          DGS2 rising faster than DGS10 (curve flattening) → bank stress,
          credit tightening ahead. Bearish for crypto and growth.
        """
        snapshot = await self.get_macro_snapshot()
        signals: list[dict] = []

        oil = snapshot.get("DCOILWTICO", {})
        cpi = snapshot.get("CPIAUCSL", {})
        vix = snapshot.get("VIXCLS", {})
        yc = snapshot.get("T10Y2Y", {})
        dgs2 = snapshot.get("DGS2", {})
        dgs10 = snapshot.get("DGS10", {})

        # --- Pattern 1: Oil → Inflation → Fed cascade ---
        oil_change_2w = oil.get("change_pct_2w", 0.0) or 0.0
        cpi_change_1m = cpi.get("change_1m", 0.0) or 0.0
        if oil_change_2w > OIL_CASCADE_THRESHOLD and cpi_change_1m > 0:
            signals.append({
                "cascade": "oil_inflation_fed",
                "direction": "BEARISH_RATES_SENSITIVE",
                "confidence": min(0.70, 0.45 + oil_change_2w / 40),
                "timeframe": "medium_term",
                "thesis": (
                    f"Oil +{oil_change_2w:.1f}% in 2 weeks with CPI rising "
                    f"(+{cpi_change_1m:.3f} MoM). Fed will stay hawkish longer. "
                    "Short rate-sensitive assets: long-duration bonds, crypto, growth."
                ),
                "affected_assets": ["BTC/USDT", "ETH/USDT", "TLT", "GC=F"],
                "data": {"oil_2w_pct": oil_change_2w, "cpi_change": cpi_change_1m},
            })

        # --- Pattern 2: VIX Spike ---
        vix_latest = vix.get("latest") or 0.0
        vix_change_1m = vix.get("change_1m", 0.0) or 0.0
        if vix_latest > VIX_RISK_OFF and vix_change_1m > 5:
            signals.append({
                "cascade": "vix_spike",
                "direction": "RISK_OFF_THEN_RECOVERY",
                "confidence": min(0.65, 0.40 + vix_latest / 100),
                "timeframe": "short_term",
                "thesis": (
                    f"VIX at {vix_latest:.1f} (+{vix_change_1m:.1f} over 1mo). "
                    "Expect initial sell-off in crypto and commodities. "
                    "Gold typically rallies in the spike. Recovery follows in 2-3 weeks."
                ),
                "affected_assets": ["BTC/USDT", "ETH/USDT", "CL=F", "GC=F"],
                "data": {"vix": vix_latest, "vix_change_1m": vix_change_1m},
            })

        # --- Pattern 3: Yield Curve Inversion ---
        yc_latest = yc.get("latest")
        if yc_latest is not None and yc_latest < YIELD_CURVE_INVERTED:
            depth = abs(yc_latest)
            signals.append({
                "cascade": "yield_curve_inversion",
                "direction": "REDUCE_RISK_MEDIUM_TERM",
                "confidence": min(0.70, 0.50 + depth / 4),
                "timeframe": "medium_term",
                "thesis": (
                    f"Yield curve inverted at {yc_latest:.2f}% (10Y-2Y). "
                    "Recession historically follows 3-18 months after inversion. "
                    "Reduce equity and high-risk exposure. XRP/crypto most vulnerable."
                ),
                "affected_assets": ["BTC/USDT", "ETH/USDT", "XRP/USDT", "GC=F"],
                "data": {"yield_curve": yc_latest},
            })

        # --- Pattern 4: Curve Flattening (Rate Squeeze) ---
        dgs2_change = dgs2.get("change_1m", 0.0) or 0.0
        dgs10_change = dgs10.get("change_1m", 0.0) or 0.0
        if dgs2_change > 0.15 and dgs2_change > dgs10_change + 0.10:
            signals.append({
                "cascade": "curve_flattening",
                "direction": "BEARISH_FINANCIALS_CRYPTO",
                "confidence": 0.55,
                "timeframe": "medium_term",
                "thesis": (
                    f"2Y yield rising faster (+{dgs2_change:.2f}%) than 10Y (+{dgs10_change:.2f}%). "
                    "Curve flattening signals credit tightening ahead. "
                    "Bearish for crypto, banks, and leveraged assets."
                ),
                "affected_assets": ["BTC/USDT", "ETH/USDT", "XRP/USDT"],
                "data": {"dgs2_change": dgs2_change, "dgs10_change": dgs10_change},
            })

        return signals

    async def close(self) -> None:
        await self._http.aclose()
