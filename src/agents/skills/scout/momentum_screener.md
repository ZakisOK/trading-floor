---
name: momentum_screener
description: Rank liquid instruments by risk-adjusted cross-sectional momentum
triggers: [momentum, screener, cross_section, ranking]
requires_tools: [fetch_ohlcv, fetch_universe, query_memory]
cost_tokens: 1900
---
## When to use
Run during pre-open to seed the day's watchlist, again at lunch (12:30 ET) for equities, and every 4 hours for crypto. Skip during confirmed risk-off regimes when momentum is historically unreliable.

## Procedure
1. Define the universe. Equities: S&P 500 + Russell 2000 members above $500M market cap with 20-day ADV > $20M. Crypto: top 100 by market cap excluding pure stablecoins. Filter out names that recently reverse-split or IPO'd (<60 days history).
2. Compute multi-horizon total return: 5-day, 20-day, 60-day, 120-day. Exclude the latest day (prevents mean-reversion noise from contaminating rank).
3. Risk-adjust each horizon by the symbol's trailing 60-day realized volatility: `score_h = return_h / vol_60d`.
4. Combine with weights: `final_score = 0.15 × score_5d + 0.30 × score_20d + 0.35 × score_60d + 0.20 × score_120d`. The medium horizons dominate — they correspond to the firm's natural holding period.
5. Rank cross-sectionally. Output top decile as long candidates and bottom decile as short candidates. Apply a liquidity tilt: down-weight the illiquid half of each decile.
6. Filter candidates already in the portfolio or on an active hazard schedule.

## Rubric / Decision rule
A candidate must be in the top (or bottom) decile AND show persistent rank (in the decile for at least three of the last five pre-open runs). Persistent rank avoids hot-hand noise. Cap output at 10 longs and 10 shorts to keep the downstream agents focused.

## Post-conditions
- Writes `momentum_pass` episode to scout memory with ranked lists, horizons, and universe hash
- Publishes the top/bottom candidates to `stream:agent:tasks` routed to Vera for technical confirmation
- Refreshes firm-memory watchlist under `group_id=firm`
