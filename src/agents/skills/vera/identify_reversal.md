---
name: identify_reversal
description: Flag a high-probability reversal at a tested support or resistance with momentum divergence
triggers: [reversal, divergence, exhaustion, key_level_test]
requires_tools: [fetch_ohlcv, compute_rsi, query_memory]
cost_tokens: 1900
---
## When to use
Use when price is approaching a previously tested level (swing high/low from at least 20 bars ago, prior day's high/low, or a round number with history). Do not use on freshly broken ranges — reversal setups require a known anchor.

## Procedure
1. Identify the level. Cluster prior pivots within 0.5 × ATR — treat them as one zone. A level with ≥3 touches is high-quality, 2 touches is medium, 1 is weak.
2. Require momentum divergence on RSI(14). On an uptrend reversal: price makes a higher high, RSI makes a lower high. On a downtrend: price lower low, RSI higher low. Absence of divergence drops the setup.
3. Require a rejection candle at the level — pin bar, engulfing, or inside-outside bar. The rejection wick must reach at least 1.0 × ATR into the zone.
4. Volume should fade into the level and spike on the rejection bar. A rejection on thin volume is a trap.
5. Entry on break of the rejection bar's opposite side, stop 0.5 × ATR beyond the wick extreme, target at the nearest opposite-side pivot for first scale and 2× risk for runner.

## Rubric / Decision rule
Reject the setup if any of: no divergence, rejection wick < 0.5 × ATR, the level has been touched 5+ times without reversing, or next higher-timeframe trend is strongly aligned against the reversal direction. Reversal confidence max is 0.75 — trend-continuation trades deserve more trust than fades.

## Post-conditions
- Writes `reversal_observation` episode to vera memory including level source, divergence delta, wick depth
- Emits a counter-trend signal with reduced size (0.5× normal)
- Tags the level in firm memory as `reversed_YYYYMMDD` or `failed_reversal_YYYYMMDD`
