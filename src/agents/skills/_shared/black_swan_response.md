---
name: black_swan_response
description: Response playbook for >3σ index moves, flash crashes, and exchange-wide outages
triggers: [black_swan, flash_crash, exchange_outage, three_sigma_move]
requires_tools: [fetch_ohlcv, fetch_vix, cancel_open_orders, produce_audit]
cost_tokens: 1800
---
## When to use
Trigger when any of the following fires: SPX or ES moves more than 3σ (rolling 30-day) inside a single 5-minute bar, VIX prints above 40 intraday, primary venue rejects a heartbeat for more than 30 seconds, or a tier-1 stablecoin depegs below $0.97. Invoke via Sage — individual agents should not run this on their own read.

## Procedure
1. Confirm the signal with two independent data sources. Coinbase + Binance for crypto, SIP + IEX for equities. A single-feed spike is treated as a data glitch and routed to data-quality review, not execution.
2. Freeze new entries immediately. Existing bracket orders stay live — the stops are the point.
3. Widen every outstanding limit order by 2× ATR to avoid adverse-selection at the print. Convert any resting take-profits inside 0.5× ATR of spot to market-on-touch to lock in gains before spread blowout.
4. Check correlation. In a real crash, VIX rises, UST yields fall, USD bid, gold bid. If only your instrument is moving, suspect venue-specific issue, not macro.
5. Reduce gross exposure by 50% if confirmed. Hedge with front-month index puts or short perps at 0.25% notional for every 1% of remaining exposure.
6. Notify the operator with a one-screen summary: move size, confirmed sources, open exposure, hedges placed, suggested next action.

## Rubric / Decision rule
A confirmed black swan drops autonomy to `COMMANDER` for the remainder of the session regardless of mode. Any venue outage longer than 5 minutes routes all remaining size to the backup venue; if no backup exists, flatten.

## Post-conditions
- Writes `black_swan_event` episode to firm memory with severity score (1-5)
- Publishes `mode_override` event forcing COMMANDER
- Every subsequent signal is tagged `risk_regime=crisis` until operator clears
