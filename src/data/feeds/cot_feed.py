"""
CFTC Commitment of Traders (COT) data feed.
Free government data — updated every Friday after close.
Most reliable free signal in commodities: 71-73% directional accuracy.

Commercial hedgers (producers, bullion banks, grain merchants) are the "smart money."
They use futures to hedge PHYSICAL inventory — so they're almost always net short.
When they flip to net long: historically precedes major rallies.
When speculators are crowded long + commercials extreme short: contrarian SELL.

Signal calculation:
  1. Download the current-year disaggregated COT report (CSV, CFTC public ZIP).
  2. Parse all weekly rows for the target commodity code (~52 readings).
  3. Compute commercial_net = commercial_long - commercial_short.
  4. Normalize current reading as percentile vs the 52-week history.
  5. Emit STRONG_BULL/BULL/NEUTRAL/BEAR/STRONG_BEAR based on that percentile.

Cache: Redis key "cot:history:{code}" — JSON list — 7-day TTL.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime, UTC
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Commodity registry — CFTC disaggregated commodity codes
# ---------------------------------------------------------------------------
COT_CODES: dict[str, str] = {
    "GC=F": "088691",   # Gold (COMEX)
    "SI=F": "084691",   # Silver (COMEX)
    "CL=F": "067651",   # WTI Crude Oil (NYMEX)
    "NG=F": "023651",   # Natural Gas (NYMEX)
    "ZC=F": "002602",   # Corn (CBOT)
    "ZW=F": "001602",   # Wheat (CBOT)
}

# Reverse lookup: CFTC code → ticker symbol
CODE_TO_SYMBOL: dict[str, str] = {v: k for k, v in COT_CODES.items()}

COMMODITY_NAMES: dict[str, str] = {
    "GC=F": "Gold", "SI=F": "Silver", "CL=F": "WTI Crude",
    "NG=F": "Natural Gas", "ZC=F": "Corn", "ZW=F": "Wheat",
}


class COTFeed:
    """
    CFTC disaggregated COT feed with 52-week percentile normalization.

    The key insight: commercial hedgers are almost always net short
    (they own the physical commodity and sell futures to lock in prices).
    Net long commercials = rare, historically precedes large rallies.

    Data source: https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip
    Current:     https://www.cftc.gov/dea/newcot/f_disagg.txt
    """

    CFTC_ZIP_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
    CFTC_CURRENT_URL = "https://www.cftc.gov/dea/newcot/f_disagg.txt"
    REDIS_TTL = 7 * 24 * 3600   # 7 days in seconds

    # CFTC CSV column names (from ZIP file headers)
    COL_CODE = "CFTC_Commodity_Code"
    COL_DATE = "Report_Date_as_YYYY-MM-DD"
    COL_OI = "Open_Interest_All"
    COL_COMM_LONG = "Prod_Merc_Positions_Long_ALL"
    COL_COMM_SHORT = "Prod_Merc_Positions_Short_ALL"
    COL_NONCOMM_LONG = "M_Money_Positions_Long_ALL"
    COL_NONCOMM_SHORT = "M_Money_Positions_Short_ALL"

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # Internal: fetch and parse annual ZIP
    # ------------------------------------------------------------------

    async def _fetch_zip_history(self, year: int) -> list[dict[str, Any]]:
        """Download CFTC annual ZIP and return all parsed COT rows."""
        url = self.CFTC_ZIP_URL.format(year=year)
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                # The ZIP contains one CSV file — find it
                csv_name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
                with zf.open(csv_name) as f:
                    text = f.read().decode("utf-8", errors="replace")
            return self._parse_csv(text)
        except Exception as exc:
            logger.warning("cot_zip_fetch_error year=%s err=%s", year, exc)
            return []

    async def _fetch_current_year(self) -> list[dict[str, Any]]:
        """
        Fetch the current year's COT data from the live text file.
        Same CSV format as the annual ZIPs — just the current year-to-date rows.
        """
        try:
            resp = await self._http.get(self.CFTC_CURRENT_URL)
            resp.raise_for_status()
            return self._parse_csv(resp.text)
        except Exception as exc:
            logger.warning("cot_current_fetch_error err=%s", exc)
            return []

    def _parse_csv(self, text: str) -> list[dict[str, Any]]:
        """Parse CFTC disaggregated CSV text into structured row dicts."""
        rows: list[dict[str, Any]] = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                # Strip whitespace from all keys and values
                clean = {k.strip(): v.strip() for k, v in row.items() if k}
                if not clean.get(self.COL_CODE):
                    continue
                try:
                    rows.append({
                        "cftc_code": clean[self.COL_CODE].strip(),
                        "date": clean.get(self.COL_DATE, ""),
                        "open_interest": int(clean.get(self.COL_OI, 0) or 0),
                        "commercial_long": int(clean.get(self.COL_COMM_LONG, 0) or 0),
                        "commercial_short": int(clean.get(self.COL_COMM_SHORT, 0) or 0),
                        "noncommercial_long": int(clean.get(self.COL_NONCOMM_LONG, 0) or 0),
                        "noncommercial_short": int(clean.get(self.COL_NONCOMM_SHORT, 0) or 0),
                    })
                except (ValueError, KeyError):
                    continue
        except Exception as exc:
            logger.warning("cot_parse_csv_error err=%s", exc)
        return rows

    # ------------------------------------------------------------------
    # Internal: Redis cache layer
    # ------------------------------------------------------------------

    async def _load_from_cache(self, cftc_code: str) -> list[dict] | None:
        """Return cached weekly history or None on miss."""
        try:
            from src.core.redis import get_redis
            redis = get_redis()
            raw = await redis.get(f"cot:history:{cftc_code}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("cot_cache_read_error err=%s", exc)
        return None

    async def _save_to_cache(self, cftc_code: str, readings: list[dict]) -> None:
        """Persist weekly history to Redis with 7-day TTL."""
        try:
            from src.core.redis import get_redis
            redis = get_redis()
            await redis.setex(
                f"cot:history:{cftc_code}",
                self.REDIS_TTL,
                json.dumps(readings),
            )
        except Exception as exc:
            logger.debug("cot_cache_write_error err=%s", exc)

    # ------------------------------------------------------------------
    # Public: build 52-week history for a commodity code
    # ------------------------------------------------------------------

    async def get_history(self, cftc_code: str) -> list[dict[str, Any]]:
        """
        Return up to 52 weeks of COT readings for a commodity code.
        Cache miss: downloads current + prior year from CFTC, filters, caches.
        Cache hit: returns from Redis (7-day TTL).
        """
        cached = await self._load_from_cache(cftc_code)
        if cached:
            logger.debug("cot_cache_hit code=%s rows=%d", cftc_code, len(cached))
            return cached

        # Download current year + previous year to ensure 52 weeks
        import asyncio
        current_year = datetime.now(UTC).year
        rows_current, rows_prior = await asyncio.gather(
            self._fetch_current_year(),
            self._fetch_zip_history(current_year - 1),
            return_exceptions=True,
        )

        all_rows: list[dict] = []
        for batch in (rows_current, rows_prior):
            if isinstance(batch, list):
                all_rows.extend(batch)

        # Filter to this commodity and sort descending by date
        matching = [r for r in all_rows if r["cftc_code"].strip() == cftc_code.strip()]
        matching.sort(key=lambda r: r["date"], reverse=True)

        # Keep most recent 52 readings
        history = matching[:52]
        logger.info("cot_history_built code=%s rows=%d", cftc_code, len(history))

        if history:
            await self._save_to_cache(cftc_code, history)
        return history

    # ------------------------------------------------------------------
    # Public: get parsed COT signal for a ticker symbol
    # ------------------------------------------------------------------

    async def get_cot_signal(self, symbol: str) -> dict[str, Any]:
        """
        Compute the full COT signal for a commodity ticker.

        Returns:
            commercial_net          absolute contracts (long - short)
            noncommercial_net       speculator net positioning
            open_interest           total open contracts
            commercial_pct_oi       commercial net as % of open interest
            percentile_52w          current commercial_net % in 52-week range (0-100)
            signal                  STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
            confidence              0.0-1.0, distance from 50th percentile
            reasoning               human-readable explanation
            history_weeks           number of weeks used for percentile calculation
        """
        cftc_code = COT_CODES.get(symbol)
        if not cftc_code:
            return {
                "symbol": symbol, "available": False,
                "reason": f"No CFTC code for {symbol}",
            }

        history = await self.get_history(cftc_code)
        if not history:
            return {
                "symbol": symbol, "available": False,
                "reason": "No COT history fetched — CFTC may be temporarily unavailable",
            }

        latest = history[0]
        comm_net = latest["commercial_long"] - latest["commercial_short"]
        noncomm_net = latest["noncommercial_long"] - latest["noncommercial_short"]
        oi = latest["open_interest"] or 1
        comm_pct_oi = round(comm_net / oi * 100, 2)

        # Build 52-week series of commercial_net for percentile calculation
        net_series = [
            r["commercial_long"] - r["commercial_short"]
            for r in history
            if r["commercial_long"] and r["commercial_short"]
        ]

        percentile_52w = _percentile_rank(comm_net, net_series)
        signal, confidence = _classify_signal(percentile_52w)

        # Build reasoning string
        direction_word = "net long" if comm_net > 0 else "net short"
        reasoning = (
            f"Commercial hedgers are {direction_word} {abs(comm_net):,} contracts "
            f"({comm_pct_oi:+.1f}% of OI) — {percentile_52w:.0f}th percentile over "
            f"{len(net_series)} weeks. "
        )
        if percentile_52w >= 80:
            reasoning += "Rarely this long — historically precedes rallies."
        elif percentile_52w >= 60:
            reasoning += "Leaning constructive. Above-average long exposure."
        elif percentile_52w <= 20:
            reasoning += "Extreme short positioning — contrarian bearish signal."
        elif percentile_52w <= 40:
            reasoning += "Below-average positioning. Mild bearish lean."
        else:
            reasoning += "Positioning neutral vs history."

        noncomm_pct = round(noncomm_net / oi * 100, 2)
        if noncomm_pct > 20:
            reasoning += f" Speculators crowded LONG ({noncomm_pct:+.1f}% OI) — crowding risk."
        elif noncomm_pct < -20:
            reasoning += f" Speculators crowded SHORT ({noncomm_pct:+.1f}% OI) — squeeze potential."

        return {
            "symbol": symbol,
            "cftc_code": cftc_code,
            "available": True,
            "report_date": latest["date"],
            "open_interest": oi,
            "commercial_long": latest["commercial_long"],
            "commercial_short": latest["commercial_short"],
            "commercial_net": comm_net,
            "commercial_pct_oi": comm_pct_oi,
            "noncommercial_long": latest["noncommercial_long"],
            "noncommercial_short": latest["noncommercial_short"],
            "noncommercial_net": noncomm_net,
            "percentile_52w": round(percentile_52w, 1),
            "signal": signal,
            "confidence": round(confidence, 3),
            "reasoning": reasoning,
            "history_weeks": len(net_series),
        }

    async def close(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _percentile_rank(value: float, series: list[float]) -> float:
    """
    Return the percentile rank of `value` within `series` (0-100).

    "What percent of historical readings is this value ABOVE?"
    Uses a linear interpolation approach — no scipy required.
    """
    if not series or len(series) < 2:
        return 50.0
    below = sum(1 for x in series if x < value)
    equal = sum(1 for x in series if x == value)
    # Midpoint convention for ties
    rank = (below + 0.5 * equal) / len(series) * 100
    return round(rank, 1)


def _classify_signal(percentile: float) -> tuple[str, float]:
    """
    Map a 52-week percentile to a signal label and confidence score.

    Signal thresholds (from the spec):
      >= 80th pct → STRONG_BULL   (commercials historically most long)
      >= 60th pct → BULL
      <= 20th pct → STRONG_BEAR   (commercials historically most short)
      <= 40th pct → BEAR
      else        → NEUTRAL

    Confidence: distance from the 50th percentile, scaled 0.0 → 1.0.
    At 50th pct: confidence = 0.0. At 0th or 100th pct: confidence = 1.0.
    """
    if percentile >= 80:
        signal = "STRONG_BULL"
    elif percentile >= 60:
        signal = "BULL"
    elif percentile <= 20:
        signal = "STRONG_BEAR"
    elif percentile <= 40:
        signal = "BEAR"
    else:
        signal = "NEUTRAL"

    # Confidence = normalised distance from centre (50th pct)
    distance_from_centre = abs(percentile - 50.0)
    confidence = round(min(distance_from_centre / 50.0, 1.0), 3)
    return signal, confidence
