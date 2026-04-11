"""
Feed manager — symbol lists and feed configuration.

XRP is the primary crypto asset.
Commodities run on a slower cycle (15 min) vs crypto (2 min) because
fundamental data (EIA reports, COT) updates weekly, not by the minute.
"""

# ---------------------------------------------------------------------------
# Crypto symbols
# ---------------------------------------------------------------------------

# XRP leads — all crypto symbols in priority order
DEFAULT_CRYPTO_SYMBOLS = ["XRP/USDT", "BTC/USDT", "ETH/USDT", "SOL/USDT"]

# XRP cross-pairs for deeper liquidity and correlation analysis
XRP_FOCUSED_SYMBOLS = ["XRP/USDT", "XRP/BTC", "XRP/ETH"]

# All crypto symbols the system monitors
ALL_CRYPTO_SYMBOLS = DEFAULT_CRYPTO_SYMBOLS + ["XRP/BTC", "XRP/ETH"]

# ---------------------------------------------------------------------------
# Commodity symbols — Yahoo Finance futures tickers
# Priority set: liquid, highly traded, COT data available
# ---------------------------------------------------------------------------

# Priority 1: metals + energy (most liquid, COT data richest)
COMMODITY_FEED_SYMBOLS = ["GC=F", "CL=F", "NG=F", "SI=F"]

# Priority 2: agriculture + more energy
COMMODITY_EXTENDED_SYMBOLS = ["ZC=F", "ZW=F", "ZS=F", "HG=F", "BZ=F"]

# Full commodity universe
ALL_COMMODITY_SYMBOLS = COMMODITY_FEED_SYMBOLS + COMMODITY_EXTENDED_SYMBOLS + ["KC=F", "PL=F", "HO=F"]

# ---------------------------------------------------------------------------
# Feed cycle configuration
# ---------------------------------------------------------------------------

# Crypto: fast cycle — price moves matter minute to minute
CRYPTO_FEED_INTERVAL_SECONDS = 120       # 2 minutes

# Commodities: slower cycle — fundamentals change daily/weekly
COMMODITY_FEED_INTERVAL_SECONDS = 900   # 15 minutes

# COT data updates once per week (Fridays after 3:30 PM ET)
# Full refresh runs every 6 hours to catch the weekly release
COT_REFRESH_INTERVAL_SECONDS = 21600   # 6 hours

# ---------------------------------------------------------------------------
# Combined symbol registry for the full system
# ---------------------------------------------------------------------------

ALL_SYMBOLS = ALL_CRYPTO_SYMBOLS + ALL_COMMODITY_SYMBOLS


def get_feed_interval(symbol: str) -> int:
    """Return the polling interval in seconds for a given symbol."""
    if symbol.endswith("=F"):
        return COMMODITY_FEED_INTERVAL_SECONDS
    return CRYPTO_FEED_INTERVAL_SECONDS


def get_asset_class(symbol: str) -> str:
    """Classify a symbol into its asset class."""
    from src.data.feeds.commodities_feed import COMMODITY_SYMBOLS
    if symbol.endswith("=F"):
        for cls, tickers in COMMODITY_SYMBOLS.items():
            if symbol in tickers:
                return cls
        return "commodity"
    if any(x in symbol for x in ["XRP", "BTC", "ETH", "SOL", "BNB", "USDT"]):
        return "crypto"
    return "equity"
