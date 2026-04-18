---
name: twap_execution
description: Slice a parent order into time-weighted child slices to minimize market impact
triggers: [twap, algo_execution, block_order, liquidity_sensitive]
requires_tools: [fetch_ohlcv, fetch_order_book, place_order, cancel_order]
cost_tokens: 1700
---
## When to use
Use when a Diana-validated order is above 0.5% of the symbol's 20-day ADV or above 10% of the current 5-minute volume. Small orders (<0.5% ADV) go straight to a smart limit — TWAP's scheduling overhead isn't worth it. Do not use on news-driven orders with short decay half-lives; use IS (implementation shortfall) instead via a dedicated skill (future).

## Procedure
1. Decide the horizon. Default window: 30 minutes for equities, 20 minutes for crypto, longer if participation limit demands it. Cap at 90 minutes — long windows leak intent.
2. Choose slice count. Target 6–12 slices. Too few and each is impactful, too many and you overpay in fees and API overhead.
3. Set per-slice participation cap at 8% of each interval's observed volume. Adjust upward to 15% if the book is deep (top-10 level depth > 5× slice size) and the spread is tight (<3 bps for equities, <8 bps for liquid crypto).
4. Post each slice as a marketable limit inside the spread, not as market orders. If the slice hasn't filled within 25% of the slice window, pull and resubmit at a 25% more aggressive price. After two reposts, cross the spread.
5. Monitor drift. If midprice moves more than 1.5 × ATR against the intended direction during execution, pause the schedule and revalidate with Diana — the thesis may have changed.
6. Record arrival price, VWAP, and TWAP slippage per slice for post-trade analysis.

## Rubric / Decision rule
Abort TWAP if: book thins to less than 2× remaining quantity at top-5 depth, spread widens beyond 3× starting spread, or a circuit-breaker / volatility halt fires. On abort, cancel remaining slices and ping Diana for guidance.

## Post-conditions
- Writes `twap_execution` episode to atlas memory with per-slice slippage, participation rate, and completion %
- Publishes `trades` events for every fill with `exec_algo=TWAP`
- Updates the strategy's post-trade-cost estimate in firm memory for Diana's next Kelly calibration
