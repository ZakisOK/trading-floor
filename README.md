# The Trading Floor

Multi-agent AI trading system. Autonomous agents research, backtest, debate, and execute paper trades.

## Quick Start

1. Copy `.env.example` to `.env` and fill in your `ANTHROPIC_API_KEY`
2. `docker compose up -d`
3. `make migrate`
4. `make paper-trade` — Start paper trading loop
5. `cd frontend && npm install && npm run dev` — Start UI at localhost:3000

## Paper Trading Modes

- **COMMANDER** — All trades require your approval
- **TRUSTED** — Auto-execute above 75% confidence
- **YOLO** — Full autonomous (paper mode only)

## Pages

| Route | Description |
|-------|-------------|
| `/` | Mission Control — portfolio overview, agent grid, live signals |
| `/market` | Market Data Explorer — OHLCV charts, exchange feeds |
| `/backtest` | Backtesting Studio — run SMA/RSI strategies on historical data |
| `/agents` | Agent Floor — 10 agents with live status, run analysis cycles |
| `/floor` | Trading Floor — isometric visualization, Bull vs Bear debate |
| `/risk` | Risk Dashboard — daily loss gauge, mode selector, positions |
| `/execution` | Execution Monitor — order history, kill switch, approvals |

## Agents

| Agent | Role | Color |
|-------|------|-------|
| Marcus | Fundamentals Analyst | Purple |
| Vera | Technical Analyst | Purple |
| Rex | Sentiment Analyst | Purple |
| Diana | Risk Manager | Rose |
| Atlas | Execution | Teal |
| Nova | Options & Volatility | Teal |
| Bull | Bullish Researcher | Amber |
| Bear | Bearish Researcher | Amber |
| Sage | Supervisor (LangGraph) | Orange |
| Scout | Opportunities | Cyan |

## Architecture

```
FastAPI + LangGraph backend
    └── Redis Streams (signals, orders, trades, audit)
    └── TimescaleDB (OHLCV history)
    └── QuestDB (tick data)

Next.js 14 frontend
    └── WebSocket live updates
    └── SVG charts (no library)
    └── CSS design tokens

Data sources: CCXT (crypto), Alpaca (equities)
AI: Claude Haiku 4.5 per agent, Claude Sonnet for briefings
```

## Make Targets

```bash
make dev          # Start docker + API with hot reload
make paper-trade  # Start 5-min paper trading loop
make backtest     # Run backtest script
make migrate      # Run Alembic migrations
make test         # Run pytest suite
make lint         # ruff + mypy
make briefing     # Print AI morning briefing
```

## Kill Switch

The kill switch is always visible on the Execution page. Type `KILL` to confirm.
It flattens all open positions and suspends all new orders until reset.
All kill switch events are written to the immutable audit stream.
