---
name: market_open_checklist
description: Pre-open readiness runbook executed before every US equity open and every crypto session boundary
triggers: [pre_open, session_start, premarket_handoff]
requires_tools: [fetch_calendar, fetch_positions, fetch_ohlcv, query_memory]
cost_tokens: 1600
---
## When to use
Run 15 minutes before the US cash open (09:15 ET) for equities/options, and at 00:55 and 12:55 UTC for crypto/FX rotations. Sage invokes this skill automatically and blocks new signal emission until every check returns green.

## Procedure
1. Pull the economic calendar for the next 6 hours. Flag FOMC, CPI, NFP, PPI, PCE, major earnings, OPEC — escalate to risk-off sizing if a tier-1 release lands in-session.
2. Verify broker connectivity: place and cancel a marketable-limit probe on a liquid symbol (SPY 1c through NBBO). Confirm fill rejection within 500ms.
3. Pull yesterday's EOD positions and overnight fills. Reconcile to broker report — any delta above $1 escalates to the operator.
4. Pull last 20 sessions of 1-minute OHLCV for every watchlist symbol. Cache in Redis under `md:cache:*` with 10-minute TTL.
5. Query firm memory for open alerts tagged `unresolved`. Block open until each is either closed or explicitly deferred.
6. Check VIX, MOVE, CVIX term structure. If front-month VIX > 25 or is backwardated by >1.5 pts, drop max_risk_per_trade by 50%.
7. Confirm agent heartbeat freshness (<30s since last beat) for Marcus, Vera, Rex, Diana, Atlas.

## Rubric / Decision rule
Any step that fails is a blocking red. Two consecutive yellow warnings (e.g. stale calendar + VIX backwardation) drop the firm to `COMMANDER` mode regardless of operator setting.

## Post-conditions
- Writes `pre_open_report` episode to firm memory with green/yellow/red per step
- Publishes an `alerts` event if any step is red
- Sage proceeds to first trading cycle only when all checks are green
