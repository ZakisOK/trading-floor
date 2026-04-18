---
name: downside_catalyst_map
description: Map and score downside catalysts for a symbol across a 90-day horizon
triggers: [downside, catalyst_map, event_risk, negative_catalyst]
requires_tools: [fetch_calendar, fetch_news, query_memory]
cost_tokens: 1700
---
## When to use
Use before opening any new long position (hazard check) and weekly on every existing long to detect stale hazard maps.

## Procedure
1. Enumerate known events in the next 90 days: earnings, investor days, analyst days, regulatory deadlines, lock-up expirations, debt maturity dates, index-rebalance dates, option-expiration congestion for the symbol.
2. Score each event on: historical move magnitude (median absolute return in a 2-day window around prior instances), directional bias (win rate for down moves), and crowding (is the market already positioned for a downside surprise via put skew).
3. Add unknown catalysts. Check short-seller report history on the name, recent SEC correspondence, class-action status, and whistleblower site mentions. Unknown catalysts get assigned a flat 5% probability per month and a median-historical magnitude.
4. Compose a hazard schedule: for each week in the window, expected downside contribution = Σ (event_probability × expected_move_if_down). Track by date so Sage can defer entries or sell into strength before a dense hazard week.
5. Cross-reference Diana's current position book. If a portfolio's aggregate hazard schedule exceeds 2% of equity in any single week, the firm is event-concentrated — pull size forward or hedge.

## Rubric / Decision rule
Reject new longs in a week where the hazard-weighted downside exceeds 1 × ATR. Reduce existing long size ahead of any single event with historical median down-move > 5%.

## Post-conditions
- Writes `hazard_map` episode to bear memory with week-by-week hazard vector
- Published firm-memory entry `hazard_schedule_<symbol>` refreshed weekly
- Triggers alerts when a freshly found catalyst lands inside an existing position's horizon
