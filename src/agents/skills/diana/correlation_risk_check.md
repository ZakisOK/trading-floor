---
name: correlation_risk_check
description: Reject a signal when adding it would push portfolio correlation exposure past threshold
triggers: [correlation, concentration, portfolio_risk]
requires_tools: [fetch_positions, fetch_correlation_matrix, query_memory]
cost_tokens: 1600
---
## When to use
Call on every signal post Kelly sizing and before Atlas routes. Skip for micro positions (risk < 0.25% of equity) — they cannot meaningfully concentrate risk regardless of correlation.

## Procedure
1. Pull current positions with their sizes and betas. Build the open-position weight vector `w`.
2. Fetch or compute the trailing 60-day daily-return correlation matrix `Σ` across the combined {open positions ∪ proposed symbol}. Crypto-to-crypto defaults to 60d hourly returns because daily history is thin.
3. Compute portfolio marginal contribution to variance for the proposed symbol: `mcv_i = (Σw)_i`. Reject if `mcv_i × proposed_weight > 0.35 × current_portfolio_variance` — one new position should not swing variance by more than 35%.
4. Compute pairwise correlation of the proposed symbol with each open position. If any pair exceeds 0.8 and combined exposure would exceed 15% of equity, route through concentration override (operator approval required).
5. Check cluster exposure. Group positions by sector (equities), L1 chain (crypto), and macro factor (rates, USD, risk-on/off). Reject if this signal pushes any cluster above `cluster_cap` (default 25% of equity, 15% in stagflation regime).

## Rubric / Decision rule
Hard reject: cluster cap breach, or correlation > 0.9 with an existing position 2× proposed size. Warn but allow: 0.6 < correlation < 0.8 with an existing position — reduce proposed size by the overlap ratio. Pass: all correlations < 0.6.

## Post-conditions
- Writes `correlation_check` episode to diana memory with matrix snapshot hash and decision
- Rejection publishes `signals:validated` entry with `status=rejected_correlation` and reason
- Approved signals carry a `cluster_tag` so the dashboard can render cluster exposure
