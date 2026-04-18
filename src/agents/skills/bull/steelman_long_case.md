---
name: steelman_long_case
description: Build the strongest possible bull thesis for a symbol, even if the current read is bearish
triggers: [steelman, bull_case, long_thesis, debate]
requires_tools: [fetch_fundamentals, fetch_ohlcv, query_memory, web_search]
cost_tokens: 2200
---
## When to use
Use during the Bull-vs-Bear debate inside Sage's decision cycle, and on demand before every position sizing decision on a planned long. Use even when internal sentiment is bearish — steelmanning the other side forces a calibrated prior.

## Procedure
1. Pull the last four quarters of fundamentals (revenue, gross margin, FCF, net debt, guidance) and compute growth trajectory. Highlight any accelerating line item.
2. Identify the optionality. A bull case worth trading has either a catalyst on a known date (product launch, earnings, regulatory) or an expanding TAM with visible execution.
3. Write the three strongest reasons this could re-rate higher by 25%+ in 12 months. Each reason must cite data (historical precedent, comparable multiples, disclosed guidance) not vibes.
4. Find the smartest public bull. Read their most recent argument. Reconstruct in your own words — if you cannot, your understanding is thin.
5. Identify what kills the thesis. A steelman is not credible unless the disconfirming scenario is named and bounded. Ask: what data in the next 90 days would make you drop the trade?

## Rubric / Decision rule
A passing steelman requires three specific, data-backed reasons, one dated catalyst, and one named kill-condition. Grade on clarity: if another agent can restate the case in two sentences without losing information, it passes. Incoherent or hand-wavy cases are rejected.

## Post-conditions
- Writes `bull_case` episode to bull memory with the three reasons, dated catalyst, and kill-condition
- Provides a structured bull score 0..1 into the Bull-vs-Bear debate
- Tags firm memory with `long_thesis_live_until=<catalyst_date>` for auto-review
