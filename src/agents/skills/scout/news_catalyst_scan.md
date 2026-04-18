---
name: news_catalyst_scan
description: Surface under-the-radar news items with tradable directional implication
triggers: [news_scan, catalyst_scan, pre_market_news]
requires_tools: [fetch_news, fetch_ohlcv, query_memory]
cost_tokens: 1600
---
## When to use
Run at 06:00, 08:00, 12:00, and 15:30 ET on trading days, and every 6 hours for crypto. Skip headlines already surfaced within the prior 2 hours (deduplication key: title normalized hash).

## Procedure
1. Pull headlines from the wire feeds, issuer filings (8-K, 13D/G, SEC litigation), crypto exchange announcements, and major industry blogs. Keep only items touching a symbol with sufficient tradable liquidity (20-day ADV > $5M for equities, top-200 market cap for crypto).
2. Filter out pure analyst recycles. A reiterated price target without new data is not a catalyst.
3. Classify novelty and importance. Novel + high-importance items pass to Rex for detailed weighting via `news_catalyst_weight`. Novel + low-importance items are stored as context without a signal. Non-novel items are dropped.
4. Measure market reaction. If the symbol has not yet gapped more than 0.5× ATR on the headline, the opportunity is fresh. If it has gapped 0.8× ATR or more, the catalyst is already priced — skip.
5. Cross-reference firm memory for active positions in the symbol or sector. Flag when scanned news contradicts an open thesis.

## Rubric / Decision rule
Pass a headline to Rex only if: novel (not seen in 48h), touches a tradable name, market has not fully priced it yet, and it does not contradict an already-mature thesis (contradictions go to Bull vs Bear debate instead).

## Post-conditions
- Writes `news_scan` episode to scout memory with headline list and pass/skip decisions
- Routes surviving headlines to Rex via `stream:agent:tasks`
- Raises a firm-memory alert when news contradicts an active position's thesis
