"""
Carry signal — the return from holding a position without price appreciation.
Second most robust factor after momentum. Available in ALL asset classes.

Commodities carry = roll yield (futures term structure)
  - Backwardation (spot > futures): positive carry = bullish hold signal
  - Contango (spot < futures): negative carry = costly to hold = bearish

Forex carry = interest rate differential
  - Long high-yield currency, short low-yield currency
  - (Forex omitted in Phase 2 — no FRED integration yet)

Crypto carry = funding rate (perpetual futures)
  - High positive funding = longs paying shorts = crowded long = bearish contrarian
  - Negative funding = shorts paying longs = crowded short = bullish contrarian
"""
from __future__ import annotations

import datetime
import httpx
import structlog
import yfinance as yf

logger = structlog.get_logger()

# Annualized cap for carry normalization — 10% = confidence 1.0
CARRY_CAP_ANNUALIZED = 0.10

# Crypto funding: 8-hour rate thresholds
FUNDING_CROWDED_LONG_THRESHOLD = 0.001   # +0.1% per 8h → bearish contrarian
FUNDING_CROWDED_SHORT_THRESHOLD = -0.0001  # negative → bullish contrarian

# Maps continuous futures root → (root_code, exchange_suffix)
# Used to construct second-month tickers: {root}{month_code}{yy}.{exchange}
_FUTURES_EXCHANGE: dict[str, tuple[str, str]] = {
    "GC=F": ("GC", "CMX"),   # Gold
    "SI=F": ("SI", "CMX"),   # Silver
    "PL=F": ("PL", "NYM"),   # Platinum
    "CL=F": ("CL", "NYM"),   # WTI Crude
    "BZ=F": ("BZ", "NYM"),   # Brent Crude
    "NG=F": ("NG", "NYM"),   # Natural Gas
    "HO=F": ("HO", "NYM"),   # Heating Oil
    "HG=F": ("HG", "CMX"),   # Copper
    "ZC=F": ("ZC", "CBT"),   # Corn
    "ZW=F": ("ZW", "CBT"),   # Wheat
    "ZS=F": ("ZS", "CBT"),   # Soybeans
    "KC=F": ("KC", "NYB"),   # Coffee
}

# Futures month codes (CME standard)
_MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}


# Crypto symbols for which Binance perpetual funding is available
_CRYPTO_BINANCE_MAP: dict[str, str] = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "XRP/USDT": "XRPUSDT",
    "SOL/USDT": "SOLUSDT",
    "ADA/USDT": "ADAUSDT",
    "DOGE/USDT": "DOGEUSDT",
    "AVAX/USDT": "AVAXUSDT",
    "MATIC/USDT": "MATICUSDT",
    "DOT/USDT": "DOTUSDT",
    "LINK/USDT": "LINKUSDT",
}


def _second_month_ticker(front_ticker: str) -> str | None:
    """
    Derive the next-month futures ticker from a continuous front-month ticker.
    E.g. 'GC=F' in April 2026 → 'GCM26.CMX' (June contract, skipping May if needed).
    Returns None for unknown symbols.
    """
    if front_ticker not in _FUTURES_EXCHANGE:
        return None

    root, exchange = _FUTURES_EXCHANGE[front_ticker]
    today = datetime.date.today()
    # Use the month 2 months out to ensure it's a distinct, liquid contract
    target = today.replace(day=1) + datetime.timedelta(days=62)
    month_code = _MONTH_CODES[target.month]
    year_2d = str(target.year)[-2:]
    return f"{root}{month_code}{year_2d}.{exchange}"


class CarrySignal:
    """
    Unified carry signal calculator for commodities and crypto.
    No LLM calls — pure market data math.
    """

    # -------------------------------------------------------------------
    # Commodity carry
    # -------------------------------------------------------------------

    def get_commodity_carry(self, symbol: str) -> dict:
        """
        Computes annualized roll yield between front-month and second-month futures.

        carry_yield_annualized:
          = (F1 / F2 - 1) × (365 / days_to_roll)
          Positive = backwardation (bullish), Negative = contango (bearish).

        Returns dict with keys:
          front_price, second_price, carry_yield_annualized,
          structure, signal, confidence
        """
        second_ticker = _second_month_ticker(symbol)
        if second_ticker is None:
            return {"signal": "NEUTRAL", "error": "unsupported_symbol", "symbol": symbol}

        try:
            front_data = yf.Ticker(symbol).history(period="2d")
            second_data = yf.Ticker(second_ticker).history(period="2d")
        except Exception as exc:
            logger.warning("commodity_carry_fetch_failed", symbol=symbol, error=str(exc))
            return {"signal": "NEUTRAL", "error": str(exc), "symbol": symbol}

        if front_data.empty or second_data.empty:
            # Second-month ticker lookup failed — try fallback one month later
            today = datetime.date.today()
            target = today.replace(day=1) + datetime.timedelta(days=32)
            root, exchange = _FUTURES_EXCHANGE[symbol]
            month_code = _MONTH_CODES[target.month]
            year_2d = str(target.year)[-2:]
            fallback = f"{root}{month_code}{year_2d}.{exchange}"
            try:
                second_data = yf.Ticker(fallback).history(period="2d")
                second_ticker = fallback
            except Exception:
                pass

        if front_data.empty or second_data.empty:
            return {"signal": "NEUTRAL", "error": "no_price_data", "symbol": symbol}

        front_price = float(front_data["Close"].iloc[-1])
        second_price = float(second_data["Close"].iloc[-1])

        if second_price <= 0:
            return {"signal": "NEUTRAL", "error": "invalid_second_price", "symbol": symbol}

        # Approximate days to roll: ~30 days between monthly contracts
        days_to_roll = 30
        spot_to_futures_ratio = front_price / second_price
        carry_yield_annualized = (spot_to_futures_ratio - 1.0) * (365.0 / days_to_roll)

        structure = "backwardation" if carry_yield_annualized > 0 else "contango"
        abs_carry = abs(carry_yield_annualized)

        if carry_yield_annualized > 0.005:    # >0.5% annualized
            signal = "BULL"
        elif carry_yield_annualized < -0.005:
            signal = "BEAR"
        else:
            signal = "NEUTRAL"

        confidence = round(min(abs_carry / CARRY_CAP_ANNUALIZED, 1.0), 4)

        return {
            "symbol": symbol,
            "second_month_ticker": second_ticker,
            "front_price": round(front_price, 4),
            "second_price": round(second_price, 4),
            "carry_yield_annualized": round(carry_yield_annualized, 6),
            "structure": structure,
            "signal": signal,
            "confidence": confidence,
        }

    # -------------------------------------------------------------------
    # Crypto carry (Binance perpetual funding rate)
    # -------------------------------------------------------------------

    async def get_crypto_carry(self, symbol: str) -> dict:
        """
        Fetches the latest 8-hour perpetual funding rate from Binance public API.

        Interpretation (contrarian):
          funding > +0.1%/8h → longs crowded → bearish signal
          funding < 0         → shorts crowded → bullish signal
          else                → neutral

        Returns dict with keys:
          symbol, binance_symbol, funding_rate, annualized_rate,
          crowding, signal, confidence
        """
        binance_sym = _CRYPTO_BINANCE_MAP.get(symbol)
        if binance_sym is None:
            return {"signal": "NEUTRAL", "error": "not_a_crypto_perp", "symbol": symbol}

        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={binance_sym}&limit=1"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("crypto_carry_fetch_failed", symbol=symbol, error=str(exc))
            return {"signal": "NEUTRAL", "error": str(exc), "symbol": symbol}

        if not data:
            return {"signal": "NEUTRAL", "error": "empty_response", "symbol": symbol}

        funding_rate = float(data[0].get("fundingRate", 0))
        # Annualize: 3 funding periods per day × 365 days
        annualized_rate = funding_rate * 3 * 365

        if funding_rate >= FUNDING_CROWDED_LONG_THRESHOLD:
            crowding = "crowded_long"
            signal = "BEAR"   # contrarian: longs will get squeezed
        elif funding_rate <= FUNDING_CROWDED_SHORT_THRESHOLD:
            crowding = "crowded_short"
            signal = "BULL"   # contrarian: shorts will get squeezed
        else:
            crowding = "balanced"
            signal = "NEUTRAL"

        # Confidence: how extreme the funding vs threshold
        if signal == "BEAR":
            raw = (funding_rate - FUNDING_CROWDED_LONG_THRESHOLD) / FUNDING_CROWDED_LONG_THRESHOLD
        elif signal == "BULL":
            raw = abs(funding_rate) / abs(FUNDING_CROWDED_SHORT_THRESHOLD)
        else:
            raw = 0.0

        confidence = round(min(abs(raw), 1.0), 4)

        return {
            "symbol": symbol,
            "binance_symbol": binance_sym,
            "funding_rate_8h": round(funding_rate, 6),
            "annualized_rate": round(annualized_rate, 4),
            "crowding": crowding,
            "signal": signal,
            "confidence": confidence,
        }

    # -------------------------------------------------------------------
    # Unified entry point
    # -------------------------------------------------------------------

    async def get_carry_signal(self, symbol: str) -> dict:
        """
        Route to the correct carry calculation based on symbol type.
        Returns a unified dict always containing: signal, confidence, carry_type.
        """
        if symbol in _CRYPTO_BINANCE_MAP:
            result = await self.get_crypto_carry(symbol)
            result["carry_type"] = "crypto_funding"
            return result

        if symbol in _FUTURES_EXCHANGE or symbol.endswith("=F"):
            result = self.get_commodity_carry(symbol)
            result["carry_type"] = "commodity_roll_yield"
            return result

        # Forex and unsupported symbols — return neutral
        return {
            "symbol": symbol,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "carry_type": "unsupported",
            "error": "no_carry_model_for_symbol",
        }
