# BRD-02: Phased Low-Level Design

## Overview

The Trading Floor is built across 9 phases (Phase 0 through Phase 8), each adding a complete
vertical slice of functionality. Each phase has a publicly accessible URL at completion. No phase
begins until the previous phase's validation gates pass.

Phases are structured as:
- Entry criteria: what must be true before work begins
- Task list with T[phase].[task] numbering
- Exit criteria: what defines "done"
- Validation gate: the specific check that closes the phase

---

## Phase 0: Scaffolding and Infrastructure (Weeks 1-2)

**Goal:** Working dev environment. Backend boots. Database connected. Redis wired. CI green.

**Entry criteria:** Empty repository.

### Tasks

| Task | Description |
|------|-------------|
| T0.1 | Project scaffolding: pyproject.toml, Docker Compose, Makefile, src/ structure, Next.js frontend skeleton |
| T0.2 | Write full BRD and design documentation (this document) |
| T0.3 | Alembic migrations and SQLAlchemy models (OHLCV, Position, Trade, Signal, AgentState, AuditLog) |
| T0.4 | Redis Streams producer, BaseConsumer, bootstrap script, consumer group initialization |
| T0.5 | CI/CD pipeline (GitHub Actions), ruff config, mypy strict config, pytest fixtures |

**Exit criteria:**
- `make docker-up && make dev` starts with no errors
- `GET /health` returns `{"status": "ok", "mode": "COMMANDER"}`
- `make lint` passes (ruff + mypy)
- `make test` passes all tests

**Validation gate:** CI pipeline green on main branch.

---

## Phase 1: Market Data Ingestion (Weeks 3-5)

**Goal:** Live market data flowing from exchanges into TimescaleDB, broadcasting to frontend.

**Entry criteria:** Phase 0 complete, CI green.

### Tasks

| Task | Description |
|------|-------------|
| T1.1 | CCXT market data feed: WebSocket OHLCV streaming, REST fallback for historical |
| T1.2 | Alpaca data feed: equity bars WebSocket, historical bars REST |
| T1.3 | TimescaleDB OHLCV ingestion: write feed output to `ohlcv` hypertable, dedup on (symbol, exchange, timeframe, ts) |
| T1.4 | WebSocket broadcast consumer: reads `stream:market_data`, fans out to connected frontend clients |
| T1.5 | Frontend market explorer: exchange selector, symbol search, timeframe toggle, TradingView Lightweight Charts OHLCV render |

**Exit criteria:**
- BTC/USDT 1m candles flow from Binance into TimescaleDB continuously
- Frontend chart updates in real-time via WebSocket
- SPY daily bars ingest from Alpaca

**Validation gate:** 1000 rows in `ohlcv` table for BTC/USDT after 10 minutes of runtime.

---

## Phase 2: Backtesting Studio (Weeks 6-8)

**Goal:** Operator can define a strategy, run a backtest, and inspect results in the UI.

**Entry criteria:** Phase 1 complete, OHLCV data flowing.

### Tasks

| Task | Description |
|------|-------------|
| T2.1 | NautilusTrader integration: BacktestEngine wrapper, data adapter for TimescaleDB OHLCV |
| T2.2 | Strategy parameter grid: define strategies as Pydantic models with parameter ranges |
| T2.3 | Metrics engine: Sharpe ratio, max drawdown, win rate, profit factor, trade count |
| T2.4 | Backtest API endpoints: POST /backtest (submit), GET /backtest/{id} (poll), GET /backtest/{id}/results |
| T2.5 | Frontend backtesting studio: parameter form, equity curve chart, trade list, metrics grid |

**Exit criteria:**
- SMA crossover strategy backtests on BTC/USDT 1h with correct Sharpe calculation
- Equity curve renders on frontend
- Results persist in database

**Validation gate:** Backtest run via API returns Sharpe > -10 (valid computation, not value-gated).

---

## Phase 3: Multi-Agent Signal Pipeline (Weeks 9-11)

**Goal:** LangGraph agent graph produces validated trading signals.

**Entry criteria:** Phase 2 complete, backtesting engine working.

### Tasks

| Task | Description |
|------|-------------|
| T3.1 | LangGraph state graph: TradingFloorState schema, Sage supervisor node, conditional routing |
| T3.2 | Implement Marcus (Fundamentals): FRED macro data tools, earnings calendar, fair value model |
| T3.3 | Implement Vera (Technical): Kronos forecast integration, pattern detection tools |
| T3.4 | Implement Rex (Sentiment): Reddit/news scraper, sentiment scoring |
| T3.5 | Implement Diana (Risk gate): risk limit checks, position sizing, signal approval/rejection |
| T3.6 | Signal validation pipeline: raw signal -> Diana -> validated stream |
| T3.7 | Confidence scoring: aggregate agent agreement into 0-1 confidence score |
| T3.8 | Strategy blending: Sage combines multiple signals into a unified position directive |
| T3.9 | Frontend strategy command: multi-agent signal grid, per-agent status, consensus meter |

**Exit criteria:**
- Full agent graph runs on BTC/USDT symbol
- Signal appears in `stream:signals:validated` after Diana approval
- Confidence score reflects multi-agent agreement
- Frontend shows all agent statuses live

**Validation gate:** End-to-end signal flow from market data -> agents -> validated signal in < 30s.

---

## Phase 4: Virtual Trading Floor (Weeks 12-14)

**Goal:** PixiJS isometric visualization of agents with real-time state updates.

**Entry criteria:** Phase 3 complete, agents producing signals.

### Tasks

| Task | Description |
|------|-------------|
| T4.1 | PixiJS scene setup: isometric grid, camera, tile rendering, agent desk positions |
| T4.2 | Agent sprites: Monument Valley 3-tone isometric character design, status glow ring |
| T4.3 | Real-time agent state: WebSocket agent state updates -> sprite status indicator changes |
| T4.4 | Speech bubbles: agent thesis text renders as speech bubble above desk, auto-fades |
| T4.5 | Click-to-inspect: clicking agent desk opens slide-out panel with full agent state |
| T4.6 | Bull vs Bear debate system: Bull and Bear agents display opposing thesis side-by-side |
| T4.7 | Agent message log: scrolling feed of inter-agent messages below the floor |

**Exit criteria:**
- 10 agent desks render on isometric floor
- Speech bubbles update when agents produce new thesis
- Clicking any agent shows their full state panel
- Bull/Bear debate panel shows opposing arguments

**Validation gate:** All 10 agent sprites visible and updating in real-time on staging URL.

---

## Phase 5: Options and Risk Dashboard (Weeks 15-17)

**Goal:** Bloomberg-grade options analytics and risk surface visualization.

**Entry criteria:** Phase 4 complete.

### Tasks

| Task | Description |
|------|-------------|
| T5.1 | Options data ingestion: Polygon.io options chain WebSocket |
| T5.2 | Greeks calculation: Black-Scholes delta, gamma, theta, vega, rho |
| T5.3 | Volatility surface: implied volatility across strikes and expiries |
| T5.4 | Nova agent implementation: options strategy selection, expiry optimization |
| T5.5 | Options dashboard UI: Greeks table, IV surface heatmap, position P&L attribution |
| T5.6 | Risk surface visualization: 2D heatmap of portfolio Greeks across price scenarios |

**Exit criteria:**
- Live IV surface renders for SPY options
- Greeks update in real-time as underlying price changes
- Nova produces options strategy proposals

**Validation gate:** IV surface renders for at least 3 expiry dates on staging.

---

## Phase 6: Live Execution Monitor (Weeks 18-20)

**Goal:** Real-time order lifecycle tracking with kill switch.

**Entry criteria:** Phase 5 complete.

### Tasks

| Task | Description |
|------|-------------|
| T6.1 | Atlas agent implementation: CCXT + Alpaca order routing, fill confirmation |
| T6.2 | Order lifecycle tracking: NEW -> PENDING -> FILLED / CANCELLED / REJECTED state machine |
| T6.3 | Slippage analysis: expected vs actual fill price, impact attribution |
| T6.4 | Kill switch implementation: operator-triggered halt of all open orders and position closure |
| T6.5 | Execution monitor UI: live order flow, position tracker, fill history, kill switch button |
| T6.6 | Daily loss circuit breaker: auto-halt when daily_loss >= max_daily_loss threshold |

**Exit criteria:**
- Paper trade executes end-to-end via Alpaca
- Kill switch halts all activity within 2 seconds
- Daily loss breaker triggers in test

**Validation gate:** Paper trade lifecycle (NEW -> FILLED) visible in UI on staging.

---

## Phase 7: Mission Control (Weeks 21-25)

**Goal:** Full agent orchestration via Sage supervisor with automated strategy rotation.

**Entry criteria:** Phase 6 complete, all agents implemented.

### Tasks

| Task | Description |
|------|-------------|
| T7.1 | Sage supervisor: LangGraph full orchestration, agent health monitoring, task dispatching |
| T7.2 | Automated strategy rotation: Sage switches strategies based on regime detection |
| T7.3 | Performance attribution: per-agent P&L contribution, win/loss breakdown |
| T7.4 | Agent health grid: real-time uptime, last heartbeat, error rate per agent |
| T7.5 | Mission control UI: full-screen ops view, portfolio state, all agent status, strategy state |
| T7.6 | Alert system: Diana + Sage push alerts to `stream:alerts`, UI renders with urgency levels |

**Exit criteria:**
- Sage orchestrates all 10 agents in a full market day simulation
- Strategy rotation happens on detected regime change
- Mission control UI shows complete system state

**Validation gate:** 8-hour paper trading simulation runs without manual intervention.

---

## Phase 8: Cross-Asset Autonomous Command (Weeks 26-31)

**Goal:** Full autonomous operation across crypto, equities, and options with Kronos forecasting.

**Entry criteria:** Phase 7 complete.

### Tasks

| Task | Description |
|------|-------------|
| T8.1 | Kronos forecasting integration: full model inference pipeline, feature engineering |
| T8.2 | Cross-asset signal synthesis: Sage blends crypto + equity + options signals |
| T8.3 | YOLO mode: full autonomous execution, no operator approval required |
| T8.4 | Self-improvement Elo system: each agent's signals tracked, Elo rating updated on outcome |
| T8.5 | Monthly performance review: automated report, agent rankings, strategy audit |
| T8.6 | Cross-asset command center UI: multi-asset view, Kronos forecast panels, autonomous mode controls |
| T8.7 | Production deployment: AWS EKS, RDS Aurora, ElastiCache, CI/CD to prod |

**Exit criteria:**
- System runs autonomously in TRUSTED mode for 7 days without intervention
- Elo ratings update after each trade closes
- Production URL live on EKS

**Validation gate:** 7-day autonomous paper trading run with positive Sharpe on staging EKS cluster.
