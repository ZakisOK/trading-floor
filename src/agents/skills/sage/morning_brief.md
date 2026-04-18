---
name: morning_brief
description: Produce the daily 07:30 ET morning brief covering macro, positions, and prioritized watchlist
triggers: [morning_brief, daily_start, board_update]
requires_tools: [query_memory, fetch_positions, fetch_calendar, fetch_ohlcv]
cost_tokens: 2400
---
## When to use
Run daily at 07:30 ET on US trading days. Also run on-demand when the operator requests a brief or when autonomy mode changes.

## Procedure
1. Pull the overnight session: Asia close, Europe open, major FX, UST yields, crude, gold, crypto majors. Summarize what moved and why in three bullets or fewer.
2. Pull the macro calendar for the next 48 hours. Tag tier-1 events with scheduled times and pre-existing market positioning (via futures curve or options positioning).
3. Pull the current portfolio and overnight fills. For each open position: mark-to-market, thesis status (on-track, drifting, broken), next scheduled checkpoint, hedge status.
4. Pull agent heartbeat and Elo snapshot. Note any agent with stale heartbeat (>5 min) or Elo decline over 7 days > 50 points.
5. Query firm memory for unresolved alerts, hazard-map entries dated today, and any flagged thesis reviews.
6. Produce the brief in this order: macro one-liner, calendar, portfolio status, agent health, top 3 watchlist ideas (from Scout's overnight pass), action items for the operator.

## Rubric / Decision rule
Brief is green if: all agent heartbeats fresh, portfolio P&L within 1σ of expected, no unresolved red alerts, no calendar item requires pre-open action. Any yellow drops autonomy mode one step (YOLO → TRUSTED, TRUSTED → COMMANDER). Any red requires explicit operator acknowledgement before market open.

## Post-conditions
- Writes `morning_brief` episode to sage memory with the full markdown brief
- Emits the brief over `stream:alerts` channel `severity=info` tagged `daily_brief`
- Sets Sage's internal `mode_floor` per the color rule above
