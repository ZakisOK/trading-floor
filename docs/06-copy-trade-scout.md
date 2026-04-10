# BRD-06: Scout Agent and Trade Proposals

## Scout Agent Overview

Scout (Opportunities Agent) is the system's market scanner. Scout runs continuously, scanning
for trading opportunities across all monitored asset classes. Its primary output is the morning
briefing: a prioritized list of trade proposals ready for operator review.

Scout does not execute. It researches and surfaces. Every Scout proposal goes through Diana's
risk gate before any execution can happen.

---

## Scout Behavior

### Continuous Market Scanning

Scout monitors a configurable universe of symbols (default: top-50 crypto by volume + S&P 500
components + major ETFs). Every 15 minutes during market hours, Scout evaluates each symbol
against a set of opportunity filters:

- Unusual volume spike (>2x 20-day average volume)
- Price near key support/resistance level (identified by Vera's tools)
- Significant sentiment shift (Reddit mention spike, news event)
- Kronos/Moirai forecast showing elevated directional probability
- Macro catalyst alignment (earnings, Fed events, sector rotation)

Symbols that trigger at least 2 filters are queued for deep analysis.

### Overnight Deep Analysis

From 11 PM to 6 AM UTC, Scout runs deep analysis on queued symbols:

1. Retrieves full OHLCV history from TimescaleDB (up to 2 years for established assets)
2. Runs Moirai 2.0 forecast for symbols with limited history
3. Identifies applicable strategy templates from the strategy library
4. Backtests each viable strategy on the symbol using NautilusTrader
5. Filters results: Sharpe > 0.8, win rate > 45%, max drawdown < 20%
6. Selects top 3-5 proposals ranked by expected value (confidence x Sharpe)

### Morning Briefing

At 6:30 AM UTC (configurable), Scout compiles all surviving proposals into the morning briefing.
The briefing is pushed to `stream:alerts` and triggers a dashboard notification.

Proposals are ranked by: (confidence x Sharpe x win_rate) / max_drawdown.

---

## Trade Proposal Format

Every Scout proposal follows this exact structure. This is what the operator sees in the
approval queue.

```
TRADE PROPOSAL
==============

Asset:        BTC/USDT
Direction:    LONG
Timeframe:    4H
Strategy:     EMA Breakout with Volume Confirmation

Confidence:   82%
Contributing: Vera (0.85), Marcus (0.72), Rex (0.79)

THESIS
------
Bitcoin has broken above the 200-period EMA on the 4H chart with a 2.3x volume surge. The
breakout follows a 6-week consolidation range between 64,000 and 68,000. Marcus confirms
macro conditions are favorable (DXY weakening, Fed rate expectations shifting dovish). Rex
reports rising retail interest with net positive sentiment on crypto subreddits over 72h.

Entry:        68,450 (market open on next 4H candle)
Stop Loss:    66,200 (below consolidation range low)
Take Profit:  74,800 (1.618x Fibonacci extension from range)
Risk:Reward:  1:2.9

POSITION SIZING
---------------
Portfolio:    $100,000
Risk per trade: 2.0% ($2,000)
Position size:  0.884 BTC
Leverage:     1x (spot)

BACKTEST RESULTS (NautilusTrader, 18 months BTC/USDT 4H)
---------------------------------------------------------
Total trades:     147
Win rate:         54.4%
Sharpe ratio:     1.34
Max drawdown:     14.2%
Profit factor:    1.61
Avg trade P&L:    +$312

RISK CALLOUT
------------
CAUTION: BTC has CPI data release in 18 hours. Consider tighter stop or smaller size.

CONTRIBUTING AGENTS
-------------------
Vera:   "Textbook EMA breakout pattern. Volume profile confirms institutional buying."
Marcus: "Macro backdrop supports risk-on. DXY -0.8% this week, yields stabilizing."
Rex:    "Social sentiment shifted bullish 72h ago. No major FUD narratives detected."
Scout:  "Ranked #1 of 7 proposals this morning. Highest expected value by composite score."
```

---

## Proposal Workflow

### COMMANDER Mode

All proposals appear in the approval queue. Operator reviews each one sequentially or in any
order. Three actions are available:

**Approve:** Signal is forwarded to Diana for risk gate validation. If Diana approves, Atlas
executes. The proposal remains in the queue showing "EXECUTING" status until filled.

**Modify:** Operator adjusts specific parameters before approval:
- Stop loss: drag on the chart or edit the field
- Position size: override Scout's recommendation (Diana enforces max risk)
- Take profit: adjust the target price
- Note: "Reduce size, uncertain macro" (logged, visible to agents)

After modification, operator clicks Approve. Modified parameters override Scout's defaults.

**Reject:** Proposal is discarded. Optional rejection reason (logged). Operator choices:
- "Wrong timing" - try again when conditions change
- "No conviction" - Scout removes from consideration for 7 days
- "Too risky" - Diana adjusts future risk limits for this strategy
- "Bad thesis" - Logged as negative signal for contributing agent Elo

Rejected proposals are not shown again unless Scout identifies material change in conditions.

### TRUSTED Mode (Auto-Execute)

Proposals with confidence >= 0.75 (configurable) are auto-executed without operator review.
Diana still applies risk gate. Atlas executes immediately.

Auto-execution flow:
1. Scout generates proposal at 82% confidence
2. Diana validates: position size within limits, daily loss not at max
3. Atlas submits order
4. Operator notification: "Auto-executed: LONG BTC/USDT 0.884 BTC @ 68,452"

Proposals with confidence < 0.75 appear in queue for operator review (same as COMMANDER mode).

Operator can always override auto-executed positions: close position, adjust stop, add to position.

### Confidence Threshold Adjustment

Default TRUSTED threshold: 0.75. Operator can adjust in settings:
- Aggressive (0.65): more auto-executions, more trades
- Conservative (0.85): fewer auto-executions, only highest conviction trades

Lower threshold increases trade frequency but may reduce average quality. Higher threshold
reduces frequency but each auto-executed trade has higher confidence backing.

---

## User-Initiated Trade Ideas

The operator can inject a trade idea directly into Scout's analysis pipeline.

**Flow:**

1. Operator types into the trade idea input in Strategy Command view:
   "I'm thinking LONG on NVDA ahead of earnings. Scout this."

2. Scout receives the idea as a structured request: symbol=NVDA, direction=LONG, trigger=earnings.

3. Scout immediately runs deep analysis on NVDA:
   - Full backtest on earnings-straddling strategies for NVDA (last 8 earnings cycles)
   - Options premium analysis (Nova consulted if applicable)
   - Sentiment scan for NVDA-specific coverage
   - Marcus reviews forward guidance and analyst consensus

4. Analysis completes within 30 minutes (immediate if market closed, next cycle if during
   active hours).

5. Scout surfaces the result as a proposal with operator-originated flag.

6. Operator reviews their own idea with full data backing. Can proceed or discard.

**Scout response if idea is not viable:**

If Scout's backtest shows negative expected value on the operator's idea, Scout surfaces it
anyway with a clear CAUTION flag: "Backtest shows -0.3 Sharpe on this setup. Recommend caution."

The operator is always given data, not blocked. The final decision is always the operator's.

---

## Scout's Strategy Library

Scout selects strategies from a pre-defined library. Each strategy is a Pydantic model with:
- Name and description
- Applicable asset classes (crypto / equity / options)
- Applicable timeframes
- Entry condition logic
- Stop and target calculation method
- Minimum backtest Sharpe threshold to propose

Core strategies available to Scout:

| Strategy | Asset Classes | Timeframes | Description |
|----------|--------------|------------|-------------|
| EMA Breakout + Volume | Crypto, Equity | 1H, 4H | EMA cross with volume confirmation |
| Support/Resistance Bounce | Crypto, Equity | 4H, 1D | Price reaction at key level |
| Momentum Continuation | Crypto, Equity | 1H, 4H | High-momentum continuation setup |
| Mean Reversion | Equity, Crypto | 15M, 1H | Overbought/oversold Bollinger Band reversal |
| Earnings Catalyst | Equity | 1D | Pre/post earnings directional trade |
| Macro Trend Rider | Equity, Crypto | 1D, 1W | Aligned with Chronos-2 macro forecast |
| Options Premium Harvest | Options | 1W | High IV premium selling via Nova |

New strategies can be added by the operator or by Sage (in autonomous mode with operator approval).
