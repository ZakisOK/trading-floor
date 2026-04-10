# BRD-01: Foundation — The Trading Floor

## Project Overview

The Trading Floor is a multi-agent AI trading system where autonomous software agents act as
specialists on a virtual trading floor. Ten agents collaborate, debate, and execute trades across
crypto, equities, and options markets. The human operator acts as a board member, receiving
briefings and approving decisions with graduated levels of autonomy.

The system is not a copy-trading bot or a simple rules engine. It is a deliberative multi-agent
system where agents with different specializations form hypotheses, challenge each other, reach
consensus, and act. The operator chooses how much to trust the agents' autonomy over time.

---

## Time Series Forecasting Models

The system integrates four foundation models for financial time series forecasting.

### Kronos

Kronos is a financial K-line (candlestick) foundation model pre-trained on large-scale OHLCV data
from multiple exchanges and asset classes. It understands the statistical structure of price action
across timeframes. Kronos is used for directional forecasting: given a window of recent candles,
it predicts the probability distribution over future price moves.

Kronos is the primary forecasting backbone for Vera (Technical Analyst) and Atlas (Execution
Agent). It is not a signal generator by itself — it produces probabilistic forecasts that agents
incorporate into their thesis.

### Chronos-2

Chronos-2 is a language model architecture adapted for time series forecasting (from the
`chronos-forecasting` library). It tokenizes time series into discrete bins and applies
transformer-based sequence modeling. It excels at multi-step-ahead forecasting and can be
conditioned on auxiliary signals (volume, spread, sentiment indices).

Chronos-2 is used for medium-term forecasting (4h-1D timeframes) and macro cycle analysis.
Marcus (Fundamentals Analyst) uses Chronos-2 to project economic time series: inflation,
yield spreads, sector flows.

### Moirai 2.0

Moirai 2.0 (Salesforce Unified Training for Time Series) is a zero-shot universal time series
forecasting model. It can be applied to arbitrary time series without fine-tuning. This makes it
useful for forecasting new assets or instruments that the system has not seen before.

Scout (Opportunities Agent) uses Moirai 2.0 when scanning for new trade candidates on assets with
limited historical data in the system's database.

### TimesFM 2.5

TimesFM 2.5 (Google Research) is a patching-based time series foundation model. It applies
patch-level positional encoding to long sequences and produces point and quantile forecasts.
TimesFM is used for volatility forecasting and regime detection, inputs to Diana (Risk Manager)
for position sizing and stop placement.

---

## Multi-Agent Architecture

The system has 11 agent roles. Each agent is implemented as a LangGraph node with typed state,
tool access, and a structured output schema.

### Agent Roster

| Agent | Role | Primary Inputs | Primary Outputs |
|-------|------|----------------|-----------------|
| Marcus | Fundamentals Analyst | Macro data, earnings, FRED | Fundamental thesis, fair value estimate |
| Vera | Technical Analyst | OHLCV, Kronos forecasts | Chart patterns, support/resistance, trend bias |
| Rex | Sentiment Analyst | Reddit, news, social feeds | Sentiment score, narrative summary |
| Diana | Risk Manager | All signals, portfolio state | Risk approval, position sizing, stop levels |
| Atlas | Execution Agent | Validated signals, broker API | Order submission, fill confirmation |
| Nova | Options Strategist | Volatility surface, Greeks | Options strategy, expiry selection |
| Bull | Bull Researcher | All available data | Bullish case thesis, supporting evidence |
| Bear | Bear Researcher | All available data | Bearish case thesis, counter-arguments |
| Sage | Portfolio Manager / Supervisor | All agent outputs | Strategy blending, capital allocation, direction |
| Scout | Opportunities Agent | Market scans, Moirai forecasts | New trade proposals, overnight briefings |

### LangGraph Topology

Sage acts as the LangGraph StateGraph supervisor. The graph topology:

```
START
  |
Scout (overnight scan) -> proposals
  |
Parallel: Marcus, Vera, Rex (research)
  |
Parallel: Bull, Bear (debate)
  |
Sage (synthesis) -> consensus + direction
  |
Diana (risk gate) -> validated signal or REJECT
  |
Nova (optional) -> options overlay if applicable
  |
Atlas (execution) -> order + fill
  |
END
```

Diana is a hard gate. If a signal fails risk checks, it is returned to Sage for revision or
discarded. Atlas does not execute unless Diana approves.

### Agent State Schema

Each agent receives a `TradingFloorState` dict with:

```python
{
    "symbol": str,
    "timeframe": str,
    "ohlcv_window": list[OHLCV],
    "fundamental_thesis": str | None,
    "technical_thesis": str | None,
    "sentiment_thesis": str | None,
    "bull_case": str | None,
    "bear_case": str | None,
    "consensus_direction": Literal["LONG", "SHORT", "NEUTRAL"] | None,
    "confidence": float | None,
    "risk_approved": bool,
    "signal": Signal | None,
    "operator_mode": Literal["COMMANDER", "TRUSTED", "YOLO"],
    "messages": list[AgentMessage],
}
```

---

## Execution Frameworks

### CCXT

CCXT (CryptoCurrency eXchange Trading Library) provides a unified API across 100+ crypto
exchanges. The system uses CCXT for:

- Live market data ingestion (REST polling + WebSocket streaming)
- Order submission for spot and perpetual futures
- Position management and balance queries
- Exchange-normalized OHLCV data collection

Atlas uses CCXT for crypto execution. The broker abstraction in `src/execution/broker.py` wraps
CCXT to provide a unified interface shared with the Alpaca integration.

### Alpaca

Alpaca provides commission-free equity trading with a robust REST and WebSocket API. The system
uses `alpaca-py` (the official Python SDK) for:

- Paper trading during development and backtesting validation
- US equity and ETF execution in live mode
- Real-time trade events and fill confirmations
- WebSocket streaming of equity quotes and bars

Alpaca is the primary execution venue for equity strategies. Atlas routes orders to CCXT or
Alpaca based on the asset class of the signal.

### NautilusTrader

NautilusTrader is an event-driven, high-performance backtesting and live trading framework written
in Rust/Python. The system uses NautilusTrader for:

- High-fidelity backtesting with realistic order book simulation
- Tick-level replay from QuestDB historical data
- Portfolio simulation with mark-to-market P&L
- Slippage modeling and market impact estimation

The backtesting engine (`src/backtesting/engine.py`) wraps NautilusTrader's `BacktestEngine` with
the system's signal pipeline. Every strategy that goes live must pass a NautilusTrader backtest.

---

## Dashboard Tech Stack

### Next.js 14 (App Router)

The frontend uses Next.js 14 with the App Router. Pages are React Server Components by default,
with client components for interactive elements. API routes proxy backend requests to avoid CORS
issues in production. The App Router enables streaming, partial renders, and layout caching.

### PixiJS (Isometric Agent Visualization)

PixiJS is a WebGL-accelerated 2D rendering engine. The Trading Floor phase (Phase 4) uses PixiJS
to render an isometric view of the virtual trading floor, a physical metaphor where each agent
occupies a desk, shows real-time status, and displays speech bubbles with their current thesis.

The isometric scene uses a 30-degree grid. Agent sprites have 3-tone face shading (Monument
Valley aesthetic). Clicking an agent opens a panel with their current state, recent signals, and
Elo rating history.

### TradingView Lightweight Charts

TradingView Lightweight Charts is the charting library for all price data visualization. It renders
OHLCV candlestick charts, volume bars, and overlays with hardware acceleration. Custom series
plugins add agent signal markers directly on the chart.

---

## Hybrid Infrastructure

### Development: Docker Compose

The development stack runs on Docker Compose with three services:

- **TimescaleDB** (PostgreSQL 16 + TimescaleDB extension): OHLCV historical data, portfolio
  state, agent state, audit log
- **QuestDB**: Tick-level price data with column-store optimized for time series ingestion
- **Redis 7**: Message broker (Redis Streams), real-time cache, session state

Services are health-checked. `make docker-up` starts all three. `make dev` starts Docker services
and the FastAPI dev server concurrently.

### Production: AWS EKS

Production runs on AWS Elastic Kubernetes Service:

- EKS cluster: Auto-scaling node groups, spot instances for non-critical workloads
- RDS Aurora (PostgreSQL 16 + TimescaleDB): Managed database with multi-AZ failover
- ElastiCache (Redis 7): Managed Redis cluster with replication
- QuestDB: Self-managed on EKS with persistent EBS volumes
- ECR: Container registry for all service images
- ALB + ACM: HTTPS load balancing with managed TLS certificates

---

## Data Pipeline

### Free Data Sources

| Source | Data | Method |
|--------|------|--------|
| FRED (Federal Reserve) | Macro economic indicators | REST API (fredapi) |
| Yahoo Finance | Equity OHLCV, fundamentals | yfinance library |
| Reddit | Social sentiment, retail thesis | PRAW |
| CoinGecko | Crypto market data | REST API |
| SEC EDGAR | Earnings, 10-K/10-Q filings | REST API |

### Paid Data Sources

| Source | Data | Method |
|--------|------|--------|
| Polygon.io | Real-time equity ticks, options chain | WebSocket + REST |
| Alpha Vantage | Forex, technical indicators | REST API |
| Alpaca Markets | US equity bars (paper/live) | alpaca-py SDK |

Data ingestion is handled by feed classes in `src/data/feeds/`. Each feed implements a base
`MarketDataFeed` interface with `connect()`, `subscribe(symbols)`, and `on_bar(callback)` methods.
Ingested data is published to `stream:market_data` and stored in TimescaleDB.

---

## Redis Streams Topology

### Streams

| Stream | Purpose | Producers | Consumer Groups |
|--------|---------|-----------|-----------------|
| `stream:market_data` | Raw OHLCV and tick data | Data feeds | cg:market_analysts, cg:ws_broadcast |
| `stream:signals:raw` | Unvalidated agent signals | Marcus, Vera, Rex, Bull, Bear, Scout | cg:risk_managers |
| `stream:signals:validated` | Risk-approved signals | Diana | cg:executors, cg:portfolio |
| `stream:orders` | Order instructions to broker | Atlas | cg:ws_broadcast |
| `stream:trades` | Executed trade confirmations | Atlas | cg:portfolio, cg:audit_writer |
| `stream:agent:tasks` | Task assignments | Sage | cg:market_analysts, cg:portfolio |
| `stream:agent:results` | Agent task completion | All agents | cg:portfolio |
| `stream:pnl` | Real-time P&L updates | Portfolio engine | cg:ws_broadcast, cg:audit_writer |
| `stream:audit` | Immutable audit trail | All write operations | cg:audit_writer |
| `stream:alerts` | Dashboard notifications | Diana, Sage | cg:ws_broadcast |

### Consumer Groups

| Group | Members | Responsibility |
|-------|---------|----------------|
| `cg:market_analysts` | Marcus, Vera, Rex | Consume market data, run analysis, emit raw signals |
| `cg:risk_managers` | Diana | Validate signals against risk limits, approve or reject |
| `cg:executors` | Atlas | Execute approved signals via broker |
| `cg:portfolio` | Sage | Track positions, calculate P&L, update portfolio state |
| `cg:ws_broadcast` | WebSocket handler | Fan-out all events to connected dashboard clients |
| `cg:audit_writer` | Audit consumer | Write immutable hash-chain audit entries to TimescaleDB |

### Message Format

All stream messages are flat key-value dicts (Redis Streams requirement). Complex values are
JSON-serialized as strings. Every message includes a `_ts` field (ISO 8601 UTC timestamp).

```python
# Example: stream:signals:raw
{
    "_ts": "2026-04-10T14:23:01.234567+00:00",
    "agent_id": "vera",
    "symbol": "BTC/USDT",
    "direction": "LONG",
    "confidence": "0.82",
    "thesis": "...",
    "entry_price": "68400.0",
    "stop_loss": "66800.0",
    "take_profit": "72000.0",
}
```
