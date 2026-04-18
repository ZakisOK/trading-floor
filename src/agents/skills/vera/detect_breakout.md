---
name: detect_breakout
description: Confirm a valid breakout above prior range high with volume and follow-through
triggers: [breakout, range_expansion, new_high, volume_surge]
requires_tools: [fetch_ohlcv, query_memory]
cost_tokens: 1800
---
## When to use
When a symbol prints a new N-bar high on the working timeframe (default 20 bars) and a volume condition may be met. Use intraday for equities (1-min and 5-min), 15-min for crypto, and daily for swing positions. Do not run on pre-market prints or on the first bar of a session — those are noise-dominated.

## Procedure
1. Pull the last 60 bars of OHLCV on the working timeframe. Compute the 20-bar high `prior_high`, the 20-bar ATR, and the 20-bar average volume `avg_vol`.
2. Confirm price condition: current close must exceed `prior_high` by more than 0.25 × ATR. A hairline break that fails this buffer is rejected as false.
3. Confirm volume condition: the breakout bar's volume must be ≥ 1.5 × `avg_vol`. For crypto, require 2.0× because the baseline is noisier.
4. Check follow-through: the next bar must not close back inside the prior range. Wait for that close before emitting.
5. Compute risk: stop at `prior_high - 0.5 × ATR` (logical level + a hair), target at `prior_high + 2 × (entry - stop)` for an R:R of at least 2:1. Reject if R:R < 1.5.
6. Query firm memory for the symbol's last 5 breakout attempts and their outcomes. Down-weight if the symbol has failed the last 3.

## Rubric / Decision rule
Confidence = 0.5 × price_buffer_score + 0.3 × volume_score + 0.2 × historical_breakout_success_rate, clipped to [0, 0.9]. Never emit above 0.9 on a single timeframe — multi-timeframe confluence is required for the 0.9+ tier.

## Post-conditions
- Writes `breakout_observation` episode to vera memory with symbol, ATR, volume ratio, outcome pending
- Emits a `LONG` signal with computed entry/stop/target
- Updates symbol's breakout attempt counter in firm memory for future calibration
