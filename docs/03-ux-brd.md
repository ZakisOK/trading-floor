# BRD-03: UX Design

## Design System Foundations

The Trading Floor uses a Vercel/Linear developer-luxury aesthetic: cool-neutral dark surfaces,
tight typography, opacity-based elevation hierarchy, and Astro UXDS status colors. Full token
documentation is in `docs/04-design-system.md`.

### Core Principles

**Density over decoration.** The operator is professional. Data is packed tightly. No wasted
whitespace, no decorative elements without information content.

**Status is always unambiguous.** Every status indicator pairs a color with an icon and a text
label. Color alone never conveys meaning (WCAG AA). A colorblind operator must be able to read
every status.

**Latency is visible.** Real-time data shows its age. A badge showing "2s ago" or "live" gives
the operator confidence in data freshness.

**Escalation path is obvious.** The kill switch is always reachable. Alert severity levels are
immediate and unmistakable.

---

## Component Specs by Phase

### Phase 0: Dev Terminal

The Phase 0 home page is a developer terminal view showing the system boot sequence and live
log stream. This gives immediate feedback that the system is alive.

**Components:**

`DevTerminal` — Full-viewport dark panel with scrolling log output. Monospace font (JetBrains
Mono). Log lines color-coded by level: INFO (text-secondary), WARN (status-caution), ERROR
(status-critical). Auto-scrolls to bottom. Pause-on-hover.

`HealthBadge` — Top-right corner. Shows `GET /health` result. Green dot + "ONLINE" when API
responds. Red dot + "OFFLINE" when unreachable. Polls every 5 seconds.

`SystemModeChip` — Shows current autonomy mode (COMMANDER / TRUSTED / YOLO) with appropriate
status color. COMMANDER: status-standby. TRUSTED: status-normal. YOLO: status-serious.

---

### Phase 1: Market Data Explorer

The Market Data Explorer gives the operator visibility into what data is flowing into the system.

**Components:**

`ExchangeSelector` — Multi-select dropdown. Options: Binance, Coinbase, Kraken (crypto) and
Alpaca (equity). Selected exchanges filter the symbol list.

`SymbolSearch` — Autocomplete input. Searches symbols available in TimescaleDB. Shows asset
class icon (crypto/equity) next to each result.

`TimeframeToggle` — Segmented control: 1m / 5m / 15m / 1h / 4h / 1D. Keyboard shortcuts
1-6. Selected timeframe is highlighted with accent-primary background.

`OHLCVChart` — TradingView Lightweight Charts candlestick chart. Full-width. Volume bars in
separate pane below. Agent signal markers overlay on candles when agents are active (Phase 3+).
Shows data age badge top-right: "live" (WebSocket connected) or "Xs ago".

`DataFeedStatus` — Grid of feed status rows. Each row: feed name, exchange, symbols subscribed,
messages/sec, last message age, status dot. Inline sparkline for message rate.

`OHLCVTable` — Paginated table of recent candles for selected symbol/timeframe. Columns: ts,
open, high, low, close, volume. Sortable by ts desc. Virtual scroll for performance.

---

### Phase 2: Backtesting Studio

The Backtesting Studio is where the operator defines strategies and validates them before
deploying capital.

**Components:**

`StrategyForm` — Form for strategy parameters. Each parameter has: name, type (float/int/enum),
default value, min/max range. Built from strategy Pydantic schema via JSON Schema reflection.
"Run Backtest" button submits to POST /backtest.

`BacktestProgress` — Shows backtest status: QUEUED / RUNNING / COMPLETE / FAILED. Progress bar
for RUNNING state. Auto-polls GET /backtest/{id} every 2 seconds.

`EquityCurve` — TradingView Lightweight Charts area chart of portfolio value over backtest period.
Drawdown pane below showing underwater curve. Entry/exit markers on chart.

`MetricsGrid` — 2-column grid of metric cards: Sharpe Ratio, Max Drawdown, Win Rate, Profit
Factor, Total Trades, Avg Trade Duration, Best Trade, Worst Trade. Each card shows value and
color indicator (green if good, red if concerning, yellow if marginal).

`TradeList` — Table of all backtest trades. Columns: entry ts, exit ts, symbol, side, entry
price, exit price, P&L, P&L %. Sortable. Expandable row shows strategy thesis for that trade.

`ParameterSweep` — Optional panel: run same strategy with a grid of parameter values. Renders
heatmap of Sharpe ratios across the parameter grid. Click cell to load that parameter set.

---

### Phase 3: Strategy Command

The Strategy Command view shows the multi-agent system in action, with each agent's current
analysis and the emerging consensus.

**Components:**

`AgentSignalGrid` — Grid of 10 agent cards. Each card: agent name, current status (IDLE /
WORKING / SIGNAL / ERROR), current symbol if working, signal direction badge (LONG / SHORT /
NEUTRAL), confidence bar (0-100%). Cards pulse when agent produces a new signal.

`ConsensusMeter` — Large semicircle gauge. Bull side (green) vs Bear side (red). Needle position
reflects aggregate confidence-weighted consensus. Labels: "STRONG LONG" / "LEAN LONG" /
"NEUTRAL" / "LEAN SHORT" / "STRONG SHORT".

`SignalFeed` — Scrolling feed of recent signals from all agents. Each item: agent name, symbol,
direction, confidence, timestamp. Click item to expand full thesis text.

`RiskGate` — Shows Diana's current decision. Input signal summary on left. Output: APPROVED
(green checkmark) with position size and stops, or REJECTED (red X) with rejection reason.

`StrategyBlend` — Sage's synthesis view. Shows contributing agent signals and weights. Final
blended direction and confidence. Strategy name label.

---

### Phase 4: Trading Floor

The Trading Floor is the flagship view. An isometric PixiJS scene shows all 10 agents working
at their desks in real-time.

**Components:**

`TradingFloorCanvas` — Full-viewport PixiJS WebGL canvas. Isometric grid. Each agent has a
desk tile with a sprite. Background: dark void with subtle grid lines. Ambient particle effects.

`AgentSprite` — 32x48px isometric sprite. Monument Valley aesthetic: blocky geometric shape,
3-tone shading (highlight, base, shadow). Status ring around base: color matches Astro UXDS
status (normal/working/error/idle). Name label below sprite.

`SpeechBubble` — Rounded rectangle with pointer, renders above agent's desk. Shows truncated
thesis (first 80 chars). Appears on signal, fades after 8 seconds. Multiple bubbles queue.

`AgentInspectPanel` — Slide-out panel from right edge. Triggered by clicking agent sprite.
Shows: agent name and role, current status, Elo rating and rank, recent signals (last 5),
current task, total signals today, win rate today.

`BullBearDebate` — Split-screen panel. Bull agent thesis on left (green accent), Bear agent
thesis on right (red accent). Confidence bars for each. Shows when both are active on same symbol.

`AgentMessageLog` — Fixed-height scrolling panel below the floor. Shows inter-agent messages
in real-time. Format: "[Marcus -> Sage] Bullish thesis on BTC confirmed by macro data."

---

### Phase 5: Options and Risk Dashboard

**Components:**

`GreeksTable` — Table of open options positions. Columns: symbol, expiry, strike, type (call/put),
delta, gamma, theta, vega, rho, P&L. Color-coded deltas. Sortable by Greeks column.

`IVSurface` — 3D-style heatmap (2D projection) of implied volatility across strikes (x-axis)
and expiry dates (y-axis). Color scale: cool (low IV) to warm (high IV). Click cell shows
exact IV value and bid/ask spread.

`RiskSurface` — Portfolio-level risk visualization. X-axis: underlying price scenarios (-20%
to +20%). Y-axis: time decay scenarios. Each cell shows portfolio P&L for that scenario.
Green cells are profitable, red cells are losses.

`PositionPnL` — Attribution panel. Breaks down today's P&L by: delta contribution, gamma
contribution, theta decay, vega changes. Bar chart per position.

---

### Phase 6: Live Execution Monitor

**Components:**

`OrderFlow` — Real-time feed of order lifecycle events. Each event: order ID, symbol, side,
qty, price, status change, timestamp. Status badges use Astro UXDS colors.

`PositionTracker` — Table of all open positions. Columns: symbol, side, qty, avg entry, current
price, unrealized P&L, P&L %, strategy, agent. Auto-updates on price ticks.

`SlippagePanel` — For each filled order: expected fill price vs actual fill. Slippage in bps.
Daily aggregate slippage cost. Distribution chart.

`KillSwitch` — Red button, top-right of execution monitor. Requires click + confirm dialog.
Dialog text: "This will cancel all open orders and flatten all positions. Type HALT to confirm."
Sends to backend kill switch endpoint. Shows countdown timer while executing.

`DailyLossBreaker` — Progress bar showing daily loss vs max daily loss limit. Turns yellow at
75%. Turns red and auto-triggers halt at 100%.

---

### Phase 7: Mission Control

**Components:**

`MissionControlLayout` — Full-screen 4-pane grid layout: top-left (portfolio state), top-right
(agent health grid), bottom-left (active strategies), bottom-right (alert feed).

`AgentHealthGrid` — Grid of all 10 agents. Each cell: agent name, uptime, last heartbeat age,
signals today, error count. Cell background reflects health: green (healthy), yellow (degraded),
red (offline).

`StrategyRotation` — Shows Sage's active strategy decisions. Current regime label. Active
strategies with allocation percentages. History of strategy switches with timestamps.

`AlertFeed` — Chronological feed of all system alerts. Severity: CRITICAL (red), SERIOUS
(orange), CAUTION (yellow), INFO (blue). Each alert: timestamp, source agent, message, action
taken.

---

### Phase 8: Cross-Asset Command Center

**Components:**

`AssetClassTabs` — Tab bar: Crypto | Equities | Options | All. Filters all panels to selected
asset class.

`KronosForecastPanel` — For selected symbol: Kronos probability distribution chart. X-axis:
future time horizon (1h / 4h / 1D / 1W). Y-axis: predicted price range. Confidence bands.

`AutonomousModeControls` — Segmented control: COMMANDER / TRUSTED / YOLO. Switching to YOLO
opens confirmation dialog: "Type YOLO to confirm full autonomous mode." Risk limits displayed
for each mode. Current mode badge in header.

`EloLeaderboard` — Agent ranking table sorted by Elo rating. Columns: rank, agent, Elo, signal
accuracy, avg confidence, best trade, worst trade. Shows trend arrow (improving/declining).

---

## Mobile Layout

Mobile uses a bottom navigation bar with 4 tabs.

### Bottom Nav

4 tabs with 44px minimum touch targets:
1. Overview: portfolio value, daily P&L, system mode
2. Agents: agent status grid, simplified signal feed
3. Log: audit log stream, recent events
4. Risk: daily loss meter, open positions, kill switch button

`safe-area-inset-bottom` applied to bottom nav wrapper for iPhone notch / Dynamic Island.

### Mobile Restrictions

- Kill switch is accessible on mobile but requires biometric confirmation
- YOLO mode cannot be activated from mobile (requires desktop)
- Charts are touch-enabled with pinch-to-zoom via TradingView Lightweight Charts mobile support

---

## Accessibility

All interactive elements meet WCAG 2.1 AA.

### Color + Status Rules

Status is never conveyed by color alone. Every status indicator must have at minimum two of:
- Color (using Astro UXDS palette)
- Icon (outline icon from lucide-react or equivalent)
- Text label

**Examples:**
- Order FILLED: green badge + checkmark icon + "FILLED" text
- Agent ERROR: red badge + alert-triangle icon + "ERROR" text
- Kill switch active: red background + stop-circle icon + "HALTING" text

### Focus and Keyboard

- All interactive elements reachable by Tab
- Visible focus ring: 2px accent-primary outline with 2px offset
- Modal dialogs trap focus
- Escape key closes all modals, slide-out panels, and dropdowns

### ARIA

- All status badges have `aria-label` describing value and context
- Live regions (`aria-live="polite"`) on signal feeds and alert feeds
- `aria-live="assertive"` on kill switch confirmation and CRITICAL alerts
- Charts have `aria-label` with summary of data shown
