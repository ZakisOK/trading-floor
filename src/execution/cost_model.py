"""
cost_model.py — Transaction cost model (Gap 2: Griffin recommendation).

Every signal Nova considers must clear its own transaction costs before
being forwarded to Desk 2. Signals with negative cost-adjusted expected
value are discarded — they destroy alpha rather than create it.

Model components:
  spread_cost   = spread_bps * 2          (enter + exit)
  fee_cost      = taker_fee_bps * 2       (enter + exit)
  market_impact = sqrt(size_usd / adv_usd) * impact_factor

All values are in basis points (bps). 1 bp = 0.01%.

Asset class defaults:
  Crypto majors (BTC/ETH/SOL/XRP/BNB): spread 5 bps, taker fee 6 bps
  Crypto alts (all others):             spread 15 bps, taker fee 6 bps
  Commodities:                          spread 10 bps, taker fee 5 bps
"""
from __future__ import annotations

import math
import structlog

logger = structlog.get_logger()

# ── Asset class classification ──────────────────────────────────────────────
CRYPTO_MAJORS = {"BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD",
                 "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"}
COMMODITIES   = {"CL=F", "GC=F", "SI=F", "NG=F", "ZC=F", "ZW=F", "ZS=F"}

# ── Spread defaults (bps) ───────────────────────────────────────────────────
SPREAD_BPS: dict[str, float] = {
    "crypto_major": 5.0,
    "crypto_alt":  15.0,
    "commodity":   10.0,
}

# ── Taker fee defaults (bps) ────────────────────────────────────────────────
TAKER_FEE_BPS: dict[str, float] = {
    "crypto_major": 6.0,
    "crypto_alt":   6.0,
    "commodity":    5.0,
}

# ── Average daily volume estimates (USD) ───────────────────────────────────
# Crypto: rough 30-day trailing average. Commodities: contract ADV * notional.
ADV_USD: dict[str, float] = {
    "BTC-USD":  40_000_000_000,
    "ETH-USD":  20_000_000_000,
    "SOL-USD":   3_000_000_000,
    "XRP-USD":   2_000_000_000,
    "BNB-USD":   1_500_000_000,
    "DOGE-USD":    800_000_000,
    "ADA-USD":     600_000_000,
    "AVAX-USD":    500_000_000,
    "LINK-USD":    400_000_000,
    "DOT-USD":     300_000_000,
    "MATIC-USD":   300_000_000,
    "UNI-USD":     200_000_000,
    "ARB-USD":     200_000_000,
    "OP-USD":      150_000_000,
    "APT-USD":     120_000_000,
    "SUI-USD":     100_000_000,
    "SEI-USD":      80_000_000,
    "INJ-USD":      80_000_000,
    "TIA-USD":      60_000_000,
    "WIF-USD":      50_000_000,
    "BONK-USD":     40_000_000,
    # Commodities (contracts * typical notional)
    "CL=F":      25_000_000_000,
    "GC=F":       8_000_000_000,
    "SI=F":       2_000_000_000,
    "NG=F":       5_000_000_000,
    "ZC=F":       3_000_000_000,
    "ZW=F":       1_500_000_000,
    "ZS=F":       2_000_000_000,
}
DEFAULT_ADV_USD = 100_000_000  # fallback for unknown symbols

MARKET_IMPACT_FACTOR = 0.10   # square-root model coefficient


def _asset_class(symbol: str) -> str:
    if symbol in COMMODITIES:
        return "commodity"
    if symbol in CRYPTO_MAJORS:
        return "crypto_major"
    return "crypto_alt"


def estimate(
    symbol: str,
    size_usd: float,
    price: float,
    expected_edge_bps: float = 20.0,
) -> dict:
    """
    Estimate round-trip transaction costs for a given trade.

    Args:
        symbol:            Asset symbol (e.g. "BTC-USD", "CL=F")
        size_usd:          Notional trade size in USD
        price:             Current mid-price
        expected_edge_bps: Signal edge in bps (gross alpha before costs).
                           Default 20 bps — override with Nova's confidence * scale.

    Returns dict:
        spread_cost_bps:           Round-trip spread cost
        fee_cost_bps:              Round-trip exchange fees
        market_impact_bps:         Square-root market impact estimate
        total_cost_bps:            Sum of all costs
        breakeven_edge_bps:        Minimum gross edge required to profit
        cost_adjusted_ev:          expected_edge_bps - total_cost_bps
        asset_class:               "crypto_major" | "crypto_alt" | "commodity"
    """
    if size_usd <= 0 or price <= 0:
        return _zero_cost(symbol)

    ac = _asset_class(symbol)
    spread_bps  = SPREAD_BPS[ac]
    fee_bps     = TAKER_FEE_BPS[ac]
    adv_usd     = ADV_USD.get(symbol, DEFAULT_ADV_USD)

    # Round-trip spread + fees
    spread_cost_bps = spread_bps * 2
    fee_cost_bps    = fee_bps * 2

    # Square-root market impact (Almgren-Chriss simplified)
    participation   = size_usd / adv_usd
    impact_bps      = math.sqrt(participation) * MARKET_IMPACT_FACTOR * 10_000

    total_cost_bps  = spread_cost_bps + fee_cost_bps + impact_bps
    cost_adjusted_ev = expected_edge_bps - total_cost_bps

    result = {
        "symbol":               symbol,
        "asset_class":          ac,
        "size_usd":             round(size_usd, 2),
        "spread_cost_bps":      round(spread_cost_bps, 3),
        "fee_cost_bps":         round(fee_cost_bps, 3),
        "market_impact_bps":    round(impact_bps, 3),
        "total_cost_bps":       round(total_cost_bps, 3),
        "breakeven_edge_bps":   round(total_cost_bps, 3),
        "cost_adjusted_ev":     round(cost_adjusted_ev, 3),
    }

    logger.debug(
        "cost_model_estimate",
        symbol=symbol,
        size_usd=round(size_usd, 0),
        total_cost_bps=round(total_cost_bps, 2),
        cost_adjusted_ev=round(cost_adjusted_ev, 2),
        viable=cost_adjusted_ev > 0,
    )
    return result


def _zero_cost(symbol: str) -> dict:
    ac = _asset_class(symbol)
    return {
        "symbol": symbol, "asset_class": ac, "size_usd": 0,
        "spread_cost_bps": 0, "fee_cost_bps": 0, "market_impact_bps": 0,
        "total_cost_bps": 0, "breakeven_edge_bps": 0, "cost_adjusted_ev": 0,
    }


def confidence_to_edge_bps(confidence: float) -> float:
    """
    Convert Nova confidence score (0–1) to an expected edge estimate in bps.
    Calibration: 0.5 confidence ≈ 0 bps edge; 1.0 confidence ≈ 50 bps edge.
    Linear interpolation; floor at 0.
    """
    return max((confidence - 0.50) * 100.0, 0.0)
