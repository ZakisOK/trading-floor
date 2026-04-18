---
name: parse_social_sentiment
description: Compute volume-weighted sentiment polarity for a symbol across X, Reddit, StockTwits
triggers: [sentiment, social_volume, retail_flow, reddit_spike]
requires_tools: [fetch_social, finbert_or_vader, query_memory]
cost_tokens: 1700
---
## When to use
Use on any symbol entering the watchlist, on-demand when Diana requests a sentiment read before sizing, and automatically once per hour on active positions. Skip symbols with less than 50 posts in the last 24 hours — the signal-to-noise ratio is too low to act on.

## Procedure
1. Pull the last 24h and last 1h buckets of posts mentioning the cashtag/ticker from X, Reddit (/r/wallstreetbets, /r/stocks, /r/cryptocurrency), and StockTwits.
2. Filter bots: drop accounts <30 days old, accounts with no bio, and posts that are pure emoji/link-only.
3. Score polarity. Prefer FinBERT if available, fall back to VADER. Aggregate to a single `-1..1` score weighted by follower count (log-scaled to cap influencers).
4. Compute volume z-score: `(24h_volume - 30d_avg_volume) / 30d_std`. Greater than +2 is a spike worth marking.
5. Break down by stance: bullish %, bearish %, neutral %. A high-volume spike with split polarity (roughly 50/50) is more actionable than a unanimous read — the split implies debate and liquidity.

## Rubric / Decision rule
Tradable sentiment: volume z ≥ +2 AND polarity magnitude ≥ 0.25 AND bullish/bearish share ≥ 55%. Contrarian read: volume z ≥ +3 AND polarity > +0.7 — extreme unanimity often marks exhaustion. Silent signal: volume z ≤ -1.5 on a position — falling chatter during uptrend is a distribution tell.

## Post-conditions
- Writes `sentiment_snapshot` episode to rex memory with polarity, volume_z, and top 3 driving themes
- Publishes to `stream:signals:raw` when tradable or contrarian rubric triggers
- Tags the symbol in firm memory with `sentiment_regime=hot|cold|neutral` for Sage's morning_brief
