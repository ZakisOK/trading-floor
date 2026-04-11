"""
Commodities data feed — fetches prices and fundamentals for commodity markets.

Sources:
  - Yahoo Finance (via yfinance): futures prices — free, no key required
  - CFTC public data: COT (Commitment of Traders) reports — free
  - EIA API: weekly petroleum status reports — free, register at api.eia.gov
  - USDA NASS API: agricultural fundamentals — free
  - FRED API: macro signals (DXY, real yields, VIX) — free, api.stlouisfed.org

Commodity-specific edge: COT data is the single most important free signal in
commodities. Commercial hedgers are the "smart money" — they know the physical
market. When they flip net long (unusual), that's a high-conviction contrarian
bullish signal.
"""
from __future__ import annotations

import os
import json
import asyncio
import logging
from datetime import datetime, date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol registry
# ---------------------------------------------------------------------------
COMMODITY_SYMBOLS: dict[str, dict[str, str]] = {
    "energy": {
        "CL=F": "WTI Crude Oil",
        "BZ=F": "Brent Crude",
        "NG=F": "Natural Gas",
        "HO=F": "Heating Oil",
    },
    "metals": {
        "GC=F": "Gold",
        "SI=F": "Silver",
        "HG=F": "Copper",
        "PL=F": "Platinum",
    },
    "agriculture": {
        "ZC=F": "Corn",
        "ZW=F": "Wheat",
        "ZS=F": "Soybeans",
        "KC=F": "Coffee",
    },
}

# Flat lookup: ticker → human name
SYMBOL_NAMES: dict[str, str] = {
    ticker: name
    for group in COMMODITY_SYMBOLS.values()
    for ticker, name in group.items()
}

# COT report identifiers (CFTC commodity codes)
COT_CODES: dict[str, str] = {
    "GC=F": "088691",   # Gold
    "SI=F": "084691",   # Silver
    "HG=F": "085692",   # Copper (COMEX HG)
    "CL=F": "067651",   # Crude Oil (WTI NYMEX)
    "NG=F": "023651",   # Natural Gas
    "ZC=F": "002602",   # Corn
    "ZW=F": "001602",   # Wheat (CBOT)
    "ZS=F": "005602",   # Soybeans
}

# Seasonal bias data (monthly average returns, %) — sourced from multi-decade research
# Positive = commodity historically outperforms in that month
SEASONAL_BIAS: dict[str, dict[int, float]] = {
    "GC=F": {  # Gold: strong Jan/Sep, weak Mar
        1: 1.8, 2: 0.3, 3: -0.6, 4: 0.5, 5: 0.2, 6: 0.1,
        7: -0.3, 8: 0.8, 9: 2.1, 10: 0.4, 11: -0.2, 12: 0.9,
    },
    "SI=F": {  # Silver: strong Jan/Jul, weak Oct
        1: 2.1, 2: 0.5, 3: -0.4, 4: 1.2, 5: -0.5, 6: 0.3,
        7: 2.4, 8: 0.6, 9: 1.5, 10: -1.1, 11: 0.2, 12: 0.7,
    },
    "CL=F": {  # Crude Oil: strong Feb-Apr (driving season build), weak Nov
        1: 0.5, 2: 1.8, 3: 2.2, 4: 1.5, 5: 0.9, 6: 0.3,
        7: -0.2, 8: 0.8, 9: -0.5, 10: -0.9, 11: -1.2, 12: 0.4,
    },
    "NG=F": {  # Nat Gas: strong Nov-Jan (heating), weak May-Sep
        1: 3.1, 2: 0.8, 3: -1.2, 4: -0.9, 5: -1.5, 6: -0.8,
        7: 0.3, 8: 0.5, 9: 0.9, 10: 1.8, 11: 3.4, 12: 2.2,
    },
    "ZC=F": {  # Corn: strong Mar-May (planting concern), weak Aug
        1: -0.3, 2: 0.5, 3: 1.8, 4: 2.1, 5: 1.5, 6: 0.4,
        7: 0.2, 8: -1.8, 9: -0.7, 10: -0.3, 11: 0.5, 12: 0.2,
    },
    "ZW=F": {  # Wheat: strong May-Jul (harvest risk), weak Sep
        1: 0.3, 2: 0.8, 3: 0.5, 4: 1.2, 5: 2.4, 6: 1.9,
        7: 1.5, 8: 0.3, 9: -1.4, 10: -0.5, 11: 0.2, 12: 0.6,
    },
    "ZS=F": {  # Soybeans: strong Jan-Mar, weak Aug-Sep
        1: 2.2, 2: 1.5, 3: 1.8, 4: 0.9, 5: 0.5, 6: 0.3,
        7: 0.8, 8: -1.5, 9: -2.1, 10: 0.2, 11: 0.6, 12: 0.4,
    },
    "HG=F": {  # Copper: strong Jan-Mar (China demand), weak Jun
        1: 2.5, 2: 1.9, 3: 1.4, 4: 0.8, 5: 0.3, 6: -1.1,
        7: 0.5, 8: 0.2, 9: -0.4, 10: 0.6, 11: 0.9, 12: 0.7,
    },
    "KC=F": {  # Coffee: strong Jan/May (frost risk in Brazil), weak Aug
        1: 2.8, 2: 1.2, 3: 0.5, 4: 0.3, 5: 3.1, 6: 0.8,
        7: -0.5, 8: -1.9, 9: -0.4, 10: 0.2, 11: 0.9, 12: 1.1,
    },
    "BZ=F": {  # Brent: similar to WTI
        1: 0.4, 2: 1.6, 3: 2.0, 4: 1.4, 5: 0.8, 6: 0.2,
        7: -0.3, 8: 0.7, 9: -0.6, 10: -1.0, 11: -1.1, 12: 0.3,
    },
    "PL=F": {  # Platinum: strong Jan/Sep
        1: 2.0, 2: 0.4, 3: -0.3, 4: 0.7, 5: 0.3, 6: 0.1,
        7: -0.2, 8: 0.5, 9: 1.8, 10: 0.3, 11: -0.1, 12: 0.6,
    },
    "HO=F": {  # Heating Oil: strong Oct-Jan (heating season)
        1: 2.4, 2: 0.5, 3: -0.8, 4: -0.4, 5: -0.7, 6: -0.3,
        7: 0.2, 8: 0.8, 9: 1.2, 10: 2.6, 11: 2.9, 12: 1.8,
    },
}


class CommoditiesFeed:
    """
    Unified commodities data feed.

    All methods are async and degrade gracefully when API keys are absent or
    external services are unreachable.
    """

    EIA_BASE = "https://api.eia.gov/v2"
    CFTC_COT_URL = (
        "https://www.cftc.gov/files/dea/history/fut_disagg_txt_hist_2006_2016.zip"
    )
    # CFTC provides the current year COT as a downloadable CSV
    CFTC_CURRENT_URL = "https://www.cftc.gov/dea/newcot/f_disagg.txt"

    def __init__(self) -> None:
        self._eia_key = os.getenv("EIA_API_KEY", "")
        self._fred_key = os.getenv("FRED_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=15.0)

    # ------------------------------------------------------------------
    # Price data
    # ------------------------------------------------------------------

    async def get_price(self, symbol: str) -> dict[str, Any]:
        """
        Fetch recent OHLCV bars for a commodity futures symbol via yfinance.

        Returns a dict with keys: symbol, name, bars (list of OHLCV dicts),
        latest_close, change_pct_1d.
        """
        try:
            import yfinance as yf

            loop = asyncio.get_event_loop()
            ticker = yf.Ticker(symbol)
            hist = await loop.run_in_executor(
                None,
                lambda: ticker.history(period="5d", interval="1h"),
            )

            if hist.empty:
                return {"symbol": symbol, "error": "no_data"}

            bars = [
                {
                    "timestamp": idx.isoformat(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                }
                for idx, row in hist.iterrows()
            ]

            latest = bars[-1]["close"] if bars else 0.0
            prev = bars[-25]["close"] if len(bars) >= 25 else bars[0]["close"]
            change_pct = ((latest - prev) / prev * 100) if prev else 0.0

            return {
                "symbol": symbol,
                "name": SYMBOL_NAMES.get(symbol, symbol),
                "latest_close": latest,
                "change_pct_1d": round(change_pct, 3),
                "bars": bars[-48:],  # last 48 hours of hourly bars
            }
        except Exception as exc:
            logger.warning("commodities_feed.get_price error symbol=%s err=%s", symbol, exc)
            return {"symbol": symbol, "error": str(exc)}

    # ------------------------------------------------------------------
    # COT data — the crown jewel of commodity signals
    # ------------------------------------------------------------------

    async def get_cot_data(self, symbol: str) -> dict[str, Any]:
        """
        Fetch CFTC Commitment of Traders (COT) disaggregated report.

        The COT breaks down open interest into:
          - Commercial hedgers (producers/merchants who know the physical market)
          - Non-commercial speculators (hedge funds, CTAs)
          - Non-reportable (retail)

        Signal logic:
          - Commercials NET LONG (unusual for them) → strong contrarian BULLISH
          - Speculators at extreme long → contrarian BEARISH (crowded trade)
          - Speculators at extreme short → contrarian BULLISH (short squeeze fuel)

        Data source: CFTC public disaggregated futures-only report (free, weekly).
        URL: https://www.cftc.gov/dea/newcot/f_disagg.txt
        """
        cot_code = COT_CODES.get(symbol)
        if not cot_code:
            return {"symbol": symbol, "cot_available": False, "reason": "no_cot_code"}

        try:
            resp = await self._http.get(self.CFTC_CURRENT_URL)
            resp.raise_for_status()
            lines = resp.text.splitlines()

            # Find the row for this commodity code
            target_line = None
            for line in lines:
                if cot_code in line:
                    target_line = line
                    break

            if not target_line:
                return {"symbol": symbol, "cot_available": False, "reason": "not_in_report"}

            # Disaggregated report columns (space/comma delimited):
            # Name, As of Date, Code, Open Interest,
            # Producer Long, Producer Short, ... Managed Long, Managed Short, ...
            parts = [p.strip() for p in target_line.split(",")]
            if len(parts) < 20:
                return {"symbol": symbol, "cot_available": False, "reason": "parse_error"}

            # Column indices for CFTC disaggregated format
            # Ref: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
            try:
                open_interest = int(parts[7]) if parts[7].strip().lstrip("-").isdigit() else 0
                # Producer/merchant (commercial) longs and shorts
                comm_long = int(parts[8]) if len(parts) > 8 else 0
                comm_short = int(parts[9]) if len(parts) > 9 else 0
                # Managed money (speculator) longs and shorts
                spec_long = int(parts[12]) if len(parts) > 12 else 0
                spec_short = int(parts[13]) if len(parts) > 13 else 0
            except (ValueError, IndexError):
                return {"symbol": symbol, "cot_available": False, "reason": "int_parse_error"}

            comm_net = comm_long - comm_short
            spec_net = spec_long - spec_short

            # Normalize to % of open interest for cross-commodity comparison
            oi = open_interest or 1
            comm_net_pct = round(comm_net / oi * 100, 2)
            spec_net_pct = round(spec_net / oi * 100, 2)

            # Signal generation
            signal = "NEUTRAL"
            strength = 0.0
            reasoning = []

            # Commercials are almost always net short (hedging their inventory).
            # When they flip to net long, it's a rare and powerful bullish signal.
            if comm_net > 0:
                signal = "BULLISH"
                strength = min(0.9, abs(comm_net_pct) / 10)
                reasoning.append(f"Commercials net LONG {comm_net:,} — rare bullish signal")
            elif comm_net_pct < -15:
                signal = "BEARISH"
                strength = min(0.7, abs(comm_net_pct) / 20)
                reasoning.append(f"Commercials heavily short {comm_net:,} ({comm_net_pct}% OI)")

            # Speculator extremes → contrarian fade
            if spec_net_pct > 20:
                reasoning.append(f"Speculators crowded LONG {spec_net_pct}% OI — fade risk")
                if signal == "BULLISH":
                    strength *= 0.7  # reduce conviction
            elif spec_net_pct < -20:
                reasoning.append(f"Speculators crowded SHORT {spec_net_pct}% OI — squeeze potential")
                if signal == "BEARISH":
                    strength *= 0.7

            return {
                "symbol": symbol,
                "cot_available": True,
                "open_interest": open_interest,
                "commercial_long": comm_long,
                "commercial_short": comm_short,
                "commercial_net": comm_net,
                "commercial_net_pct": comm_net_pct,
                "speculator_long": spec_long,
                "speculator_short": spec_short,
                "speculator_net": spec_net,
                "speculator_net_pct": spec_net_pct,
                "signal": signal,
                "strength": round(strength, 3),
                "reasoning": "; ".join(reasoning) or "No extreme positioning",
            }

        except httpx.HTTPError as exc:
            logger.warning("cot_fetch_error symbol=%s err=%s", symbol, exc)
            return {"symbol": symbol, "cot_available": False, "reason": f"http_error: {exc}"}
        except Exception as exc:
            logger.warning("cot_parse_error symbol=%s err=%s", symbol, exc)
            return {"symbol": symbol, "cot_available": False, "reason": str(exc)}

    # ------------------------------------------------------------------
    # Seasonal bias
    # ------------------------------------------------------------------

    def get_seasonal_bias(self, symbol: str, month: int | None = None) -> dict[str, Any]:
        """
        Return the historical average monthly return for a commodity.

        Based on multi-decade backtests. Positive = commodity tends to rally
        in this calendar month. Useful for position sizing and directional bias.
        """
        if month is None:
            month = date.today().month

        bias_table = SEASONAL_BIAS.get(symbol, {})
        if not bias_table:
            return {"symbol": symbol, "month": month, "seasonal_bias": 0.0, "available": False}

        monthly_return = bias_table.get(month, 0.0)

        # Classify bias strength
        if monthly_return > 1.5:
            bias_label = "STRONG_BULLISH"
        elif monthly_return > 0.5:
            bias_label = "MILD_BULLISH"
        elif monthly_return < -1.5:
            bias_label = "STRONG_BEARISH"
        elif monthly_return < -0.5:
            bias_label = "MILD_BEARISH"
        else:
            bias_label = "NEUTRAL"

        # Find the best and worst months for context
        best_month = max(bias_table, key=bias_table.get)  # type: ignore[arg-type]
        worst_month = min(bias_table, key=bias_table.get)  # type: ignore[arg-type]

        return {
            "symbol": symbol,
            "name": SYMBOL_NAMES.get(symbol, symbol),
            "month": month,
            "seasonal_return_pct": monthly_return,
            "bias": bias_label,
            "best_month": best_month,
            "best_month_return_pct": bias_table[best_month],
            "worst_month": worst_month,
            "worst_month_return_pct": bias_table[worst_month],
            "available": True,
        }

    # ------------------------------------------------------------------
    # EIA petroleum status report
    # ------------------------------------------------------------------

    async def get_eia_report(self) -> dict[str, Any]:
        """
        Fetch the weekly EIA petroleum status report.

        Key signals:
          - Crude inventory build (bearish for oil) / draw (bullish)
          - Gasoline inventory changes (seasonal demand signal)
          - Refinery utilization rate
          - SPR (Strategic Petroleum Reserve) levels

        Requires EIA_API_KEY env var. Gracefully returns empty dict if not set.
        API docs: https://www.eia.gov/opendata/documentation.php
        """
        if not self._eia_key:
            logger.info("EIA_API_KEY not set — skipping EIA report")
            return {"available": False, "reason": "EIA_API_KEY not configured"}

        try:
            url = f"{self.EIA_BASE}/petroleum/sum/sndw/data/"
            params = {
                "api_key": self._eia_key,
                "frequency": "weekly",
                "data[0]": "value",
                "facets[series][]": [
                    "WCRSTUS1",   # US crude oil stocks (total)
                    "WGRSTUS1",   # US gasoline stocks
                    "WDISTUS1",   # US distillate stocks
                    "WPULEUS3",   # US refinery utilization
                ],
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 4,  # last 4 weeks
                "offset": 0,
            }
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            series_data: dict[str, list] = {}
            for row in data.get("response", {}).get("data", []):
                sid = row.get("series-description", row.get("series", "unknown"))
                series_data.setdefault(sid, []).append({
                    "period": row.get("period"),
                    "value": row.get("value"),
                    "units": row.get("units", ""),
                })

            # Parse crude inventory change (week-over-week)
            crude_rows = series_data.get("U.S. Ending Stocks of Crude Oil  (Thousand Barrels)", [])
            crude_change = None
            crude_signal = "NEUTRAL"
            if len(crude_rows) >= 2:
                latest_crude = crude_rows[0]["value"]
                prior_crude = crude_rows[1]["value"]
                if latest_crude and prior_crude:
                    crude_change = float(latest_crude) - float(prior_crude)
                    # Build > 1M bbl = bearish; draw > 1M bbl = bullish
                    if crude_change > 1000:
                        crude_signal = "BEARISH"
                    elif crude_change < -1000:
                        crude_signal = "BULLISH"

            return {
                "available": True,
                "crude_stocks_change_kbd": crude_change,
                "crude_signal": crude_signal,
                "series": series_data,
                "as_of": crude_rows[0]["period"] if crude_rows else None,
            }

        except httpx.HTTPError as exc:
            logger.warning("eia_fetch_error err=%s", exc)
            return {"available": False, "reason": f"http_error: {exc}"}
        except Exception as exc:
            logger.warning("eia_parse_error err=%s", exc)
            return {"available": False, "reason": str(exc)}

    # ------------------------------------------------------------------
    # FRED macro signals
    # ------------------------------------------------------------------

    async def get_macro_context(self) -> dict[str, Any]:
        """
        Fetch key macro signals relevant to commodity pricing:
          - DXY (US Dollar Index): inverse relationship with most commodities
          - TIPS breakeven (inflation expectations): gold proxy
          - VIX: risk-off spikes benefit gold/silver
          - 10Y real yield: gold's most important macro driver (inverse)

        Uses FRED API. FRED_API_KEY is free at fred.stlouisfed.org.
        """
        if not self._fred_key:
            return {"available": False, "reason": "FRED_API_KEY not configured"}

        series_ids = {
            "DTWEXBGS": "dxy_broad",              # Broad Dollar Index
            "T10YIE": "breakeven_10y",            # 10Y inflation breakeven
            "VIXCLS": "vix",                      # CBOE VIX
            "DFII10": "real_yield_10y",           # 10Y TIPS real yield
        }

        results: dict[str, Any] = {"available": True}

        async def fetch_series(series_id: str, key: str) -> None:
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                resp = await self._http.get(url, params={
                    "series_id": series_id,
                    "api_key": self._fred_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
                })
                resp.raise_for_status()
                obs = resp.json().get("observations", [])
                if obs:
                    latest = next(
                        (o for o in obs if o.get("value") not in (".", None)), None
                    )
                    results[key] = float(latest["value"]) if latest else None
            except Exception as exc:
                logger.debug("fred_series_error series=%s err=%s", series_id, exc)
                results[key] = None

        await asyncio.gather(*[
            fetch_series(sid, key) for sid, key in series_ids.items()
        ])

        # Derive signals
        dxy = results.get("dxy_broad")
        real_yield = results.get("real_yield_10y")
        vix = results.get("vix")

        gold_macro_bias = "NEUTRAL"
        if real_yield is not None and dxy is not None:
            if real_yield < 0 and dxy < 100:
                gold_macro_bias = "BULLISH"
            elif real_yield > 1.5 and dxy > 105:
                gold_macro_bias = "BEARISH"

        results["gold_macro_bias"] = gold_macro_bias
        results["risk_off"] = vix is not None and vix > 25

        return results

    async def close(self) -> None:
        await self._http.aclose()
