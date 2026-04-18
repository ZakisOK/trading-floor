---
name: news_catalyst_weight
description: Rank an incoming news headline by expected price impact and decay half-life
triggers: [news, headline, press_release, filing, catalyst]
requires_tools: [fetch_news, query_memory, fetch_ohlcv]
cost_tokens: 1800
---
## When to use
Run on every headline touching a watchlist symbol or a macro subject that affects portfolio exposure. Skip low-tier republications (aggregator reposts identical text within a 10-minute window — only the first instance triggers this skill).

## Procedure
1. Classify the catalyst. Tier 1: earnings beat/miss with guidance, M&A, FDA approval, central-bank action, major litigation, regulatory action, hack/exploit. Tier 2: analyst up/downgrades, guidance reaffirmation, insider-buy clusters, sector rotation calls. Tier 3: conference mentions, product launches without financial guidance, personnel changes below C-suite.
2. Check novelty — query firm memory for identical story in the last 48 hours. A repeat is half-weight. A rumor that became confirmed is full-weight on confirmation, not on rumor.
3. Estimate surprise magnitude. Compare to consensus (guidance beat %, analyst target delta, strike vs spot for options flow). Normalize as a z-score vs the symbol's typical news response.
4. Pull historical 1-hour and 1-day returns on the same tier of headline for this symbol. Expected impact = median historical response × (1 + surprise_z / 2).
5. Compute decay half-life: Tier 1 events decay over 3–10 sessions, Tier 2 over 1–3 sessions, Tier 3 intraday only. A headline whose decay is already priced (gap already matches expected impact) is not tradable.

## Rubric / Decision rule
Trade only Tier 1 and Tier 2. Minimum surprise z ≥ 1.0. If the pre-market gap already exceeds 0.8 × expected impact, pass — entry is stale. Confidence = 0.4 × tier_score + 0.35 × surprise_z + 0.25 × historical_hit_rate, clipped to 0.85.

## Post-conditions
- Writes `news_catalyst` episode to rex memory with tier, surprise_z, expected impact, decay half-life
- Emits directional signal with horizon tag matching decay half-life
- Shares the catalyst to firm memory so Diana can correlate across portfolio
