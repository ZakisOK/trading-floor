---
name: kelly_sizing
description: Size a position using the half-Kelly formula with drawdown and autonomy-mode clamps
triggers: [size_position, kelly, position_sizing]
requires_tools: [fetch_positions, fetch_equity_curve, query_memory]
cost_tokens: 1500
---
## When to use
Call on every signal that has passed sanity checks and before Atlas routes the order. Do not size on signals with confidence below 0.55 — those are below the minimum-edge floor.

## Procedure
1. Estimate edge parameters. From the emitting agent's trailing 90-day performance on this strategy/symbol pair, pull: win rate `p`, average winner `W`, average loser `L`. Require at least 30 samples; below 30, use the strategy's firm-wide prior.
2. Compute Kelly fraction: `f* = (p × W - (1 - p) × L) / W`. If `f*` is negative, reject the signal and log a `negative_edge` episode.
3. Apply the half-Kelly cap: `f = min(0.5 × f*, 0.10)`. The 10% absolute cap is non-negotiable — full Kelly blows accounts on parameter drift.
4. Apply the autonomy-mode multiplier: COMMANDER 1.0× of `max_risk_per_trade`, TRUSTED 1.5×, YOLO 2.5× up to the hard cap. Never exceed `max_risk_per_trade` from settings.
5. Apply drawdown clamp. If trailing-30d equity drawdown > 5%, halve the size. If > 10%, quarter. If > 15%, force signal rejection and page operator.
6. Convert to share/contract count using the signal's entry and stop. Position size = account_equity × f / |entry − stop|. Round down to exchange lot size.

## Rubric / Decision rule
Reject if computed position size is below one lot, below the broker's minimum, or above 3× the ADV-implied liquid size (no more than 1% of 20-day ADV). Size must round down, never up. Log every clamp that fires so the backtest can be rerun with the same constraints.

## Post-conditions
- Writes `sizing_decision` episode to diana memory with Kelly inputs and final size
- Publishes the sized order spec to `stream:signals:validated`
- Increments drawdown-clamp counter if any clamp fired — three fires in a day escalates to the operator
