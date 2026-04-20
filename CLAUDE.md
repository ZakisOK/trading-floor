# The Trading Floor — CLAUDE.md

## Project Overview
Multi-agent AI trading system. Autonomous agents research, backtest, debate, and execute trades across crypto, equities, and options. Operator acts as board member with graduated autonomy controls.

## Operating Modes
- COMMANDER: Approve everything. Max 2% risk/trade, 5% daily loss.
- TRUSTED: Auto-execute above 75% confidence threshold. 3% risk, 7% daily loss.
- YOLO: Full autonomous. 5% risk, 12% daily loss. Requires "YOLO" typed to confirm.

## Tech Stack
**Backend:** Python 3.11, FastAPI, LangGraph, SQLAlchemy async, Alembic, Redis Streams
**Databases:** TimescaleDB (PostgreSQL 16), QuestDB (tick data), Redis 7
**Forecasting:** Kronos, Chronos-2, Moirai 2.0 (via chronos-forecasting)
**Execution:** CCXT, Alpaca, NautilusTrader
**Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, PixiJS, TradingView Lightweight Charts
**Infrastructure:** Docker Compose (dev), AWS EKS (prod)

## Repository Structure
```
src/
  agents/          # LangGraph agent definitions
    base.py        # BaseAgent class
    marcus.py      # Fundamentals Analyst
    vera.py        # Technical Analyst
    rex.py         # Sentiment Analyst
    diana.py       # Risk Manager
    atlas.py       # Execution Agent
    nova.py        # Options Strategist
    bull.py        # Bull Researcher
    bear.py        # Bear Researcher
    sage.py        # Portfolio Manager (supervisor)
    scout.py       # Opportunities Agent
  api/
    main.py        # FastAPI app entry
    routers/       # Route handlers
    ws/            # WebSocket handlers
  core/
    config.py      # Pydantic BaseSettings
    database.py    # Async SQLAlchemy engine
    redis.py       # Redis client + stream helpers
    security.py    # Auth, kill switch
  data/
    feeds/         # Market data ingestion
    models/        # SQLAlchemy ORM models
    schemas/       # Pydantic schemas
  execution/
    broker.py      # Broker abstraction
    risk.py        # Risk checks
    orders.py      # Order management
  forecasting/
    kronos.py      # Kronos wrapper
    chronos.py     # Chronos-2 wrapper
  backtesting/
    engine.py      # Backtest runner
    metrics.py     # Sharpe, drawdown, win rate
  streams/
    consumer.py    # Redis Streams consumer base
    producer.py    # Redis Streams producer helpers
    topology.py    # Stream name constants
frontend/
  app/             # Next.js 14 App Router
  components/      # React components
  hooks/           # Custom React hooks
  lib/             # Utilities
  public/          # Static assets
alembic/           # DB migrations
tests/             # pytest tests
scripts/           # Utility scripts
docs/              # BRDs and design docs
```

## Redis Streams Topology
```
stream:market_data          — Raw price data
stream:signals:raw          — Unvalidated signals
stream:signals:validated    — Risk-approved signals
stream:orders               — Order instructions
stream:trades               — Executed trade confirmations
stream:agent:tasks          — Task assignments
stream:agent:results        — Task results
stream:pnl                  — Real-time P&L
stream:audit                — Immutable audit trail
stream:alerts               — Dashboard notifications
```

Consumer groups: cg:market_analysts, cg:risk_managers, cg:executors, cg:portfolio, cg:ws_broadcast, cg:audit_writer

## Conventions
- All timestamps UTC. Use `datetime.UTC` (not `datetime.utcnow()`).
- Type hints on every function. No bare except.
- Result[T] pattern for error handling — use a simple dataclass or Pydantic model.
- Pydantic `strict=True` on all data models.
- Never hardcode secrets. Always Pydantic BaseSettings + .env.
- Append-only audit log. REVOKE UPDATE, DELETE on audit_log table.
- SHA-256 hash chain on audit entries.
- ruff for linting/formatting. mypy for type checking.

## Build Commands
```
make dev        # Start Docker + backend dev server
make test       # Run test suite
make lint       # ruff + mypy
make migrate    # Run Alembic migrations
make docker-up  # Start all Docker services
```

## Agents
```
Marcus — Fundamentals Analyst
Vera   — Technical Analyst
Rex    — Sentiment Analyst
Diana  — Risk Manager
Atlas  — Execution Agent
Nova   — Options Strategist
Bull   — Bull Researcher
Bear   — Bear Researcher
Sage   — Portfolio Manager (LangGraph supervisor)
Scout  — Opportunities Agent
```

## Alpaca MCP + Memory Architecture (Phase 1)

**Alpaca MCP server** is configured in `.mcp.json` via `uvx alpaca-mcp-server` and is intended for Claude Code interactive sessions only — exploring positions, inspecting account state, fetching market data while developing. Production agents (Atlas in particular) use the `alpaca-py` SDK directly from Python. The MCP surface is intentionally narrowed via `ALPACA_TOOLSETS` to read-only toolsets: account, positions, stock_data, crypto_data, options_data, watchlists, assets, news. Order placement, cancellation, replacement, and position closing tools are additionally hard-denied in `.claude/settings.local.json` so Claude Code cannot execute a trade even if a prompt tried to coax it.

**Default paper mode.** `ALPACA_PAPER_TRADE=true` is set in `.env.example` and forced inside `.mcp.json`. To flip the MCP server to live trading, set `ALPACA_PAPER_TRADE=false` in your shell before launching Claude Code — this should almost never happen. Live trading goes through the Python execution path with full risk checks and Diana approval, never through a chat tool call.

**Graphiti + Zep CE** is the shared temporal memory layer for agents. Every agent reads and writes to the same Graphiti instance (Neo4j-backed) so beliefs, observations, and debate outcomes persist across cycles. `GRAPHITI_URL` and the Neo4j credentials are wired through `src/core/config.py`.

**Phoenix** (Arize) is observability. It receives OTLP traces for every LLM call, tool invocation, and agent step — `PHOENIX_COLLECTOR_ENDPOINT` points agents at it. Use the UI on port 6006 to debug reasoning chains.
