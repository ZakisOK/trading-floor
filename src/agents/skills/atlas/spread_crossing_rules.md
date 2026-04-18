---
name: spread_crossing_rules
description: Decide when to cross the spread with a marketable order versus work a limit inside the spread
triggers: [spread_cross, limit_vs_market, maker_taker]
requires_tools: [fetch_order_book, fetch_ohlcv, place_order]
cost_tokens: 1400
---
## When to use
Apply to every non-TWAP order Atlas routes. Also use as a sub-procedure inside `twap_execution` for the final slice when chasing completion.

## Procedure
1. Measure the quoted spread in basis points: `(ask − bid) / mid × 10_000`. Cheap (<3 bps equities, <5 bps majors, <10 bps crypto alts) supports limits; expensive supports crossing selectively, not blindly.
2. Measure urgency. News-driven orders with expected decay <30 minutes cross. Mean-reversion entries at a planned level work a limit. Stop-outs always cross.
3. Measure expected move. If Vera's expected move over the next slice exceeds the spread by 2×, cross — the half-spread cost is small vs the price drift.
4. Peg limits to the midpoint by default. Repost every 5 seconds if the book moves away by more than 1 tick. After 3 reposts without fill, step to the opposite side (effectively crossing).
5. On an iceberg or hidden-liquidity venue, probe with 10% of intended size at the midpoint to read the reaction. A filled probe with no price movement signals deep hidden liquidity — send the rest with slightly improved pricing.

## Rubric / Decision rule
Always cross: stop-outs, forced exits under halt_protocol, news with <15m decay. Never cross on mean-reversion entries unless the alt-fill cost (tracked by Atlas) exceeds the 2× spread gain from waiting. Default: peg-mid limit with a 3-repost fallback.

## Post-conditions
- Writes `spread_decision` episode to atlas memory with spread_bps, urgency class, chosen action
- Updates per-symbol maker-vs-taker ratio stats
- Feeds slippage data back to Diana for Kelly recalibration
