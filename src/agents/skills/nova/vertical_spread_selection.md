---
name: vertical_spread_selection
description: Select the optimal vertical spread strikes and expiration for a directional thesis
triggers: [vertical_spread, debit_spread, credit_spread, bull_call, bear_put]
requires_tools: [fetch_option_chain, fetch_iv, fetch_ohlcv, query_memory]
cost_tokens: 2100
---
## When to use
Use when Vera or Marcus publishes a directional thesis with a target price and a horizon of 5–60 days. Skip for horizons under 5 days (gamma-dominated, use long options or stock instead) and over 60 days (diagonal or calendar is usually better).

## Procedure
1. Decide structure based on IV rank (IVR = (current IV − 52w low) / (52w high − 52w low) × 100). IVR > 50 favors credit spreads (sell premium, defined risk). IVR < 30 favors debit spreads (pay for movement). IVR 30–50 is a toss-up — defer to skew.
2. Choose expiration. Match to thesis horizon plus 30–50% buffer; for example, a 10-day thesis uses a 14–21 DTE expiry. Avoid expiries with earnings or FOMC inside the window unless the trade is explicitly event-driven.
3. Select strikes. For a debit call spread: long leg at 0.35–0.45 delta, short leg at the target price (or 0.15 delta, whichever is closer). For a credit put spread: short leg at 0.30 delta (70% OTM probability), long leg 1 strike further OTM to define risk.
4. Compute breakeven: debit spread breakeven = long strike + net debit; credit spread breakeven = short strike − net credit. Reject if breakeven is beyond 1.5 × 1-sigma expected move for the horizon.
5. Compute R:R. Debit spread max loss = net debit; max gain = (strike width − net debit). Require max gain / max loss ≥ 1.2:1. Credit spread: max gain = net credit; max loss = (strike width − net credit). Credit spreads accept worse R:R in exchange for higher win probability.
6. Sanity-check liquidity: open interest ≥ 500 per leg and bid-ask < 10% of mid.

## Rubric / Decision rule
Reject spreads that require crossing more than 15% of mid on entry, or where the combined commission + slippage exceeds 5% of max gain. Confidence is a function of thesis confidence × structure-fit (IVR alignment) × liquidity score. Cap at underlying-thesis confidence.

## Post-conditions
- Writes `spread_selection` episode to nova memory with strikes, expiry, net cost, R:R, IVR
- Publishes a structured options signal carrying leg instructions to atlas
- Stores expected P&L path across horizon in firm memory for Diana's stress tests
