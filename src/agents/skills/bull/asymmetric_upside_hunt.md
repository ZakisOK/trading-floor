---
name: asymmetric_upside_hunt
description: Screen for setups with defined downside and open-ended upside (right-tail hunt)
triggers: [asymmetric, convexity, lottery_ticket, right_tail]
requires_tools: [screener, fetch_ohlcv, fetch_option_chain, query_memory]
cost_tokens: 1900
---
## When to use
Use once daily during pre-open and when Scout surfaces a new candidate with an unusual options-flow profile. Do not use during confirmed risk-off regimes (Marcus flagged stagflation or deflation) — convexity premium is too rich to pay up.

## Procedure
1. Screen for structural asymmetry. Candidates include: heavily shorted names (short interest > 15% of float) with improving fundamentals, sub-$500M market caps with a disclosed catalyst path, broken IPOs trading below expected value, and deep OTM options on names with a known date catalyst.
2. Verify the downside is actually defined. For stock, you need either a hard support (50w MA with multiple tests) or a structural floor (net cash per share ≥ 60% of market cap). For options, downside is the premium paid — confirm the premium is the total risk.
3. Size the upside. Require a plausible 3:1 to 10:1 payoff path with supporting math (target multiple expansion, target earnings revision, target options delta growth).
4. Cross-check with skew. If the market is charging > 1.5× the symbol's typical 25-delta call skew, someone smarter knows something — either pay up or pass, but note the asymmetry has been partially discounted.
5. Check time. An asymmetric trade with no deadline becomes a carry trade. Require a 30–180 day catalyst window.

## Rubric / Decision rule
Accept only when: downside is capped at ≤ 1% of portfolio, upside path is ≥ 3× the downside, and a dated catalyst exists. Reject vague "it could run" ideas without a specific reason. Size is always small — asymmetric bets are conviction-weighted but tail-focused; no single asymmetric bet above 0.5% of equity.

## Post-conditions
- Writes `asymmetric_candidate` episode with payoff ratio, downside mechanism, catalyst date
- Publishes a low-size-high-conviction signal through the normal Diana → Atlas path
- Adds the catalyst date to firm memory so Sage can schedule a thesis review
