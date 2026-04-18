---
name: eod_review
description: End-of-day P&L attribution, lessons learned, and next-day plan
triggers: [eod_review, end_of_day, after_close, pnl_attribution]
requires_tools: [fetch_trades, fetch_positions, query_memory]
cost_tokens: 2200
---
## When to use
Run at 16:30 ET on US trading days, at 00:15 UTC for the crypto rollover, and on-demand after any day where daily P&L exceeds ±2%.

## Procedure
1. Compute day's P&L attribution: realized vs unrealized, per-strategy, per-agent, per-instrument. Flag any single trade contributing more than 30% of day P&L — outsized contributions deserve a write-up.
2. Compute realized costs: slippage vs arrival, commission, borrow cost, financing. Compare to Diana's pre-trade estimates. A systematic drift >25% between estimate and actual is a calibration issue — feed it back.
3. Compute agent Elo updates based on today's signals vs market outcomes at the horizon each agent committed to. Persist to firm memory.
4. Classify the day's regime. Did morning-brief's regime assumption hold? If not, capture the miss under `regime_miss` episode with evidence.
5. Write three lessons in plain English. Each lesson must point to a specific trade or signal. No generalities.
6. Produce the next-day plan: thesis updates needed, hazard map weeks coming up, agent tuning items, any positions to trim/add/hedge pre-open.

## Rubric / Decision rule
A clean day is one where: attribution sums to reconciled P&L within $1, no unlogged trades, every agent's Elo update computes without errors, every lesson points to a specific artifact (trade id, signal id, episode id). A day with unreconciled P&L or missing signal traces is a red: block next-day live trading until resolved.

## Post-conditions
- Writes `eod_review` episode to sage memory with full attribution table, lessons, and plan
- Updates per-agent Elo in firm memory
- Emits the review over `stream:alerts` as `severity=info` tagged `eod_summary`
