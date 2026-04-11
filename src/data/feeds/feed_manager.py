"""
Feed manager — symbol lists and feed configuration.
XRP is the primary asset and gets priority placement.
"""

# XRP leads — all crypto symbols in priority order
DEFAULT_CRYPTO_SYMBOLS = ["XRP/USDT", "BTC/USDT", "ETH/USDT", "SOL/USDT"]

# XRP cross-pairs for deeper liquidity and correlation analysis
XRP_FOCUSED_SYMBOLS = ["XRP/USDT", "XRP/BTC", "XRP/ETH"]

# All symbols the system monitors
ALL_SYMBOLS = DEFAULT_CRYPTO_SYMBOLS + ["XRP/BTC", "XRP/ETH"]
