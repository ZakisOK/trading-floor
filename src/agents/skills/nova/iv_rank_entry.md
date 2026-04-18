---
name: iv_rank_entry
description: Use IV rank and percentile to gate long-premium vs short-premium option structures
triggers: [iv_rank, implied_volatility, vega_regime, premium_selling]
requires_tools: [fetch_iv, fetch_hv, fetch_option_chain, query_memory]
cost_tokens: 1600
---
## When to use
Run before any options structure is chosen. A single-leg long call or put and any multi-leg structure should consult this skill first.

## Procedure
1. Pull 52-week IV series and compute IV rank (IVR = (IV_today − IV_min) / (IV_max − IV_min) × 100) and IV percentile (% of days in the last 252 with lower IV). IVR reacts to extremes, IVP to frequency. Report both.
2. Compute HV(20) and HV(60). Compute IV-HV spread: IV − HV(20). Positive spread (IV rich) supports selling premium; negative (IV cheap) supports buying.
3. Check the term structure. Contango (front month lower IV than back) is normal; backwardation (front higher) typically occurs around events and means time premium will collapse — favor selling short-dated.
4. Check skew. Put skew steeper than usual (25-delta put IV >> 25-delta call IV) signals downside hedging demand. This is a bearish tell but also makes put-selling expensive-rich; prefer put credit spreads over naked put sales.
5. Cross-reference earnings/event calendar. Event vol is elevated by design — do not mistake event-driven IVR > 80 for a generic premium-sell signal.

## Rubric / Decision rule
Sell premium (credit spreads, iron condors, covered calls) when IVR ≥ 50, IV-HV20 > 0, and no tier-1 event in the expiry window. Buy premium (debit spreads, long calls/puts) when IVR ≤ 30 and HV is expanding week-over-week. Between 30 and 50 default to directional structures (verticals) rather than pure premium plays.

## Post-conditions
- Writes `iv_regime` episode to nova memory with IVR, IVP, IV-HV spread, term-structure state
- Tags the underlying in firm memory with `vega_regime=high|mid|low` for 24 hours
- Blocks any long-premium signal on an underlying tagged `vega_regime=high` unless Marcus provides an event catalyst
