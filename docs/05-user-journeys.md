# BRD-05: User Journeys

## Operator Profile

The operator is a technically sophisticated trader who has built confidence in the agent team
over time. They start in COMMANDER mode (full approval required), graduate to TRUSTED mode as
agents build track record, and may eventually enable YOLO mode for full autonomy.

The operator checks the system 2-4 times per day in mature operation: morning briefing, midday
check, end-of-day review. In COMMANDER mode, they check more frequently to approve trades.

---

## Operating Modes

### COMMANDER Mode

All trades require explicit operator approval before execution. The operator sees every signal,
reviews the thesis, and clicks Approve or Reject.

- Max risk per trade: 2% of portfolio
- Max daily loss: 5% of portfolio
- Auto-execution: none
- Operator involvement: every trade

**When to use:** Initial deployment, new strategy introduction, volatile market conditions,
any time the operator wants maximum control.

### TRUSTED Mode

Agents auto-execute trades above the confidence threshold (75% default). Trades below threshold
surface for operator review. The operator receives a notification for every execution.

- Max risk per trade: 3% of portfolio
- Max daily loss: 7% of portfolio
- Auto-execution: signals with confidence >= 0.75
- Operator involvement: review notifications, manual override available

**When to use:** After agents have demonstrated consistent track record (typically 90+ days of
COMMANDER mode operation with positive outcomes). The operator has validated agent judgment.

### YOLO Mode

Full autonomous execution. Agents trade without any operator approval. The operator monitors
the system but does not intervene. Activating YOLO requires typing "YOLO" in a confirmation
dialog.

- Max risk per trade: 5% of portfolio
- Max daily loss: 12% of portfolio
- Auto-execution: all approved signals
- Operator involvement: monitoring only, kill switch available

**When to use:** High-conviction autonomous operation. Requires deep trust in agent track record.
Not recommended for new deployments or untested strategies.

---

## Daily Journey 1: Morning Check-In

**Mode:** COMMANDER or TRUSTED
**Duration:** 10-15 minutes
**Trigger:** Operator opens dashboard, 6:00-9:00 AM

**Steps:**

1. Operator opens dashboard. Mission Control or Market Explorer loads.

2. `HealthBadge` confirms system is ONLINE. `SystemModeChip` shows current mode.

3. Operator reviews overnight briefing from Scout agent: new trade proposals surfaced during
   overnight scan. Each proposal shows asset, direction, thesis summary, confidence score,
   backtest metrics.

4. For each proposal, operator reads the full thesis from Scout. Views supporting data from
   Marcus, Vera, Rex. Reviews backtest Sharpe and drawdown.

5. In COMMANDER mode: operator clicks Approve or Reject for each proposal. Approved proposals
   enter the signal pipeline for Diana's risk gate.

6. In TRUSTED mode: high-confidence proposals (>= 0.75) executed overnight automatically.
   Operator reviews what was auto-executed and confirms agreement.

7. Operator checks portfolio state: open positions, overnight P&L, daily loss meter.

8. Operator reviews agent health grid: any agent errors overnight? Any feeds down?

**Exit:** Operator is informed of the day's starting position and active proposals.

---

## Daily Journey 2: Approve or Override

**Mode:** COMMANDER
**Duration:** 2-5 minutes per trade
**Trigger:** New signal notification (push notification or in-app alert)

**Steps:**

1. Operator receives notification: "New signal: Vera LONG BTC/USDT @ 68,400 | Confidence: 81%"

2. Operator opens dashboard. Signal appears in the approval queue.

3. Operator reviews the trade proposal (full format defined in `06-copy-trade-scout.md`):
   - Asset, direction, timeframe
   - Plain-English thesis from each contributing agent
   - Entry, stop, target prices
   - Risk:reward ratio
   - Position size from Diana
   - Backtest metrics

4. Operator has three choices:
   - **Approve**: Signal goes to Atlas for execution
   - **Modify**: Operator adjusts stop loss or position size, then approves
   - **Reject**: Signal discarded, reason logged

5. If Approved: Atlas executes. Fill confirmation appears in execution monitor.

6. If Rejected: operator can optionally add a note. Note is logged and visible to agents
   in next signal cycle (agents learn from rejections over time).

**Override flow:**

At any time, operator can manually add a trade idea via text input in the Strategy Command view.
"I want to short SPY. Ideas?" routes to Scout for backtesting and surfaces as a proposal.

---

## Daily Journey 3: Check Team

**Mode:** Any
**Duration:** 3-5 minutes
**Trigger:** Midday check or before leaving desk

**Steps:**

1. Operator opens the Trading Floor PixiJS view.

2. All 10 agent sprites visible on isometric floor. Status rings show health at a glance:
   green ring = working, blue ring = standby, red ring = error.

3. Operator scans for any red rings. Clicks any degraded agent to inspect.

4. Inspect panel shows: current status, last signal, Elo rating, today's accuracy.

5. Operator reviews Bull vs Bear debate if agents are actively analyzing a symbol. Views
   both sides before making any directional judgment.

6. Operator checks agent message log for inter-agent disagreements or unusual activity.

7. If all agents healthy and no active debates needing attention: done.

**Error recovery flow:**

If an agent shows ERROR status: inspect panel shows error details. Operator can trigger
agent restart from the panel. Error is logged in audit trail.

---

## Daily Journey 4: Risk Scan

**Mode:** Any
**Duration:** 2-3 minutes
**Trigger:** Before entering a new position, or any time market becomes volatile

**Steps:**

1. Operator opens Risk or Mission Control view.

2. Reviews daily loss meter. If at 50%+ of daily limit, operator shifts focus to risk reduction.

3. Reviews all open positions in PositionTracker: unrealized P&L, current stops, distance to stop.

4. Reviews agent alert feed. Any CAUTION or SERIOUS alerts from Diana?

5. Reviews DailyLossBreaker: current daily loss % of limit. Yellow zone = awareness. Red = halt.

6. If in TRUSTED or YOLO mode: operator verifies Diana's recent risk approvals. Comfortable
   with active position sizes?

7. If volatility spike detected (VIX jump, macro event): operator may manually tighten stops
   or reduce position sizes from PositionTracker.

**Outcome:** Operator has full situational awareness of portfolio risk in under 3 minutes.

---

## Daily Journey 5: Emergency Kill Switch

**Mode:** Any (most relevant in TRUSTED / YOLO)
**Duration:** Under 30 seconds
**Trigger:** Unexpected market event, system malfunction, operator wants to stop all activity

**Steps:**

1. Operator sees unusual P&L drawdown or news event. Wants to stop everything immediately.

2. Kill switch button is visible in Execution Monitor and Mission Control. Always reachable.

3. Operator clicks Kill Switch button.

4. Confirmation dialog opens: "This will cancel all open orders and flatten all positions.
   Type HALT to confirm."

5. Operator types HALT and clicks confirm.

6. Backend receives kill switch command. Sequence:
   a. All pending orders cancelled via Atlas (CCXT + Alpaca cancel_all)
   b. All open positions submitted for market close
   c. Agent task queue cleared, no new signals processed
   d. System enters HALTED state, mode indicator shows red HALTED badge

7. UI shows countdown and completion status for each action: "Cancelling orders... done.
   Closing positions... 3 of 5 closed... done. System halted."

8. Operator receives summary: orders cancelled, positions closed, total P&L impact.

9. System remains halted until operator manually resumes (click "Resume" + confirm).

**Audit trail:** Every kill switch event is logged with timestamp, operator ID, and reason
(if provided). Irreversible audit entry with hash chain verification.

---

## How Operator Involvement Decreases Over Time

**Weeks 1-4 (COMMANDER mode):** Operator approves every trade. Reviews each thesis carefully.
Builds intuition for agent quality. Learns which agents are most reliable for which asset classes.

**Months 2-3 (COMMANDER with track record):** Operator has 90+ days of signal data. Reviews
Elo ratings. Identifies which agents have >60% accuracy. Begins to trust high-confidence signals.

**Month 4 (First TRUSTED activation):** Operator enables TRUSTED mode with default 75% threshold.
Monitors closely for 2 weeks. Adjusts threshold up or down based on auto-execution quality.

**Month 6+ (TRUSTED mature operation):** Operator checks dashboard 2x/day. Reviews execution
log, adjusts strategies via Scout, monitors risk. Rarely overrides.

**Month 12+ (YOLO consideration):** Operator has 300+ days of agent performance data. Elo ratings
have stabilized. Agent accuracy is demonstrably above random. YOLO mode considered for a subset
of portfolio (e.g., 20% allocation to YOLO, remainder in TRUSTED).

The key constraint: YOLO mode requires typing "YOLO" every session. There is no persistent
YOLO state. This prevents accidental autonomous operation.

---

## Self-Improvement Loop: Elo System

Each agent maintains an Elo rating (starting at 1200, same as chess). The Elo system measures
signal quality over time.

**Elo update rules:**

A signal is evaluated when the trade closes. The outcome is compared to the agent's confidence
prediction:
- Agent predicted 80% confidence LONG and trade was profitable: Elo increases by ~15 points
- Agent predicted 80% confidence LONG and trade was a loss: Elo decreases by ~25 points
- Low-confidence signals (50-60%) have smaller Elo swings
- High-confidence signals (90%+) have larger Elo swings

**Monthly review:**

On the first Monday of each month, Sage runs the monthly performance review:
- Ranks all agents by Elo
- Identifies underperforming agents (Elo < 1100)
- Generates strategy audit: which strategies produced positive expected value?
- Adjusts agent weighting in consensus scoring based on Elo trajectory
- Surfaces recommended parameter changes to operator

**Operator action on monthly review:**

Operator reviews the automated report in Mission Control. Can:
- Increase or decrease agent weight in consensus (drag slider per agent)
- Retire a strategy (marks it inactive, Scout stops proposing it)
- Promote a strategy to higher allocation
- Reset an agent's Elo if agent implementation was updated

The Elo system creates a self-improving feedback loop where agents that produce accurate signals
gain more influence over system decisions over time.
