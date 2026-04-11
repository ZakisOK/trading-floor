# The Trading Floor — Build Complete

**Date:** 2026-04-11
**Cloudflare URL:** pending DigitalOcean deployment

---

## Architecture

The system is organized as three desks, each with a distinct responsibility:

**Desk 1 — Alpha Research** runs the LangGraph pipeline (graph.py). Marcus reads macro regime,
Vera applies technical analysis, Rex handles risk scoring, XRP Analyst adds on-chain XRPL
fundamentals, and Polymarket Scout adjusts conviction using prediction-market probabilities.
Nova (Synthesizer) aggregates all signals via Bayesian weighting and forwards only strong/moderate
conviction packets to Desk 2.

**Desk 2 — Trade Execution** is owned by TradeDeskAgent. It reads conviction packets from
`stream:trade_desk:inbox`, runs them through Diana (final position sizing + risk gate) and Atlas
(order routing). When a trade closes, it writes outcomes to `stream:trade_outcomes` for the
Learning Layer to consume.

**Desk 3 — Portfolio Oversight** is the Portfolio Chief. Running every 5 minutes, it detects
market regime (TRENDING / RANGING / VOLATILE) and broadcasts it to Redis, checks cross-desk
concentration risk, detects consecutive-loss patterns and suppresses underperforming agents,
triggers calibration sweeps, and writes nightly performance reports.

---

## New agents

| Agent | File | Role | Triggered by |
|-------|------|------|-------------|
| Nova | src/agents/nova.py | Synthesizer — Bayesian aggregator, final Desk 1 node | graph.py after polymarket_scout |
| XRP Analyst | src/agents/xrp_analyst.py | XRP specialist — XRPL on-chain + macro | graph.py when symbol contains XRP |
| Polymarket Scout | src/agents/polymarket_scout.py | Prediction market conviction boost | graph.py after rex/xrp_analyst |

**Rename:** sage.py → graph.py (sage.py preserved as a stub for legacy compatibility).
`SageAgent` is now an alias for `GraphAgent` inside graph.py.

---

## New data feeds

| Feed | File | Source | Auth |
|------|------|--------|------|
| XRPL Feed | src/data/feeds/xrpl_feed.py | data.ripple.com + s1.ripple.com RPC | None (public) |
| Polymarket Feed | src/data/feeds/polymarket_feed.py | gamma-api.polymarket.com | None (public) |
| Feed Manager | src/data/feeds/feed_manager.py | Symbol registry — XRP-first priority | — |

---

## Infrastructure

| Component | File | Description |
|-----------|------|-------------|
| Position Monitor | src/execution/position_monitor.py | 5s sweep — trailing stop, stop-loss, take-profit exits |
| Risk Monitor | src/execution/risk_monitor.py | 30s sweep — daily loss limit, concentration alerts, kill-switch |
| Trade Desk | src/execution/trade_desk.py | Reads stream:trade_desk:inbox — Diana sizing → Atlas execute |
| Portfolio Chief | src/oversight/portfolio_chief.py | 5min — regime, concentration, mistake patterns, calibration |
| Agent Memory | src/learning/agent_memory.py | Redis-backed per-agent signal history and Bayesian weights |
| Calibration | src/learning/calibration.py | ECE calibration check — detects confidence drift per agent |

---

## New API routers

- `src/api/routers/execution.py` — registered in main.py
- `src/api/routers/market.py` — registered in main.py (updated)

---

## Dashboard pages

| Page | Route | Shows |
|------|-------|-------|
| Home | / | System status overview |
| Positions | /positions | Open positions, PnL, trailing stops |
| Polymarket | /polymarket | Live prediction-market signals affecting conviction |
| Firm | /firm | Three-desk overview — agent status per desk |

---

## How to start everything

```
# 1. Bring up infrastructure
docker compose up -d

# 2. Run DB migrations
.\run.ps1 migrate

# 3. Pre-flight health check — fix any FAILs before continuing
.\run.ps1 health

# 4. Start the API
.\run.ps1 dev

# 5. Start paper trading (Desk 1 + Nova → Desk 2 conviction packets)
.\run.ps1 paper-trade

# 6. Start monitors + Trade Desk (Desk 2 execution + exits)
.\run.ps1 monitors

# 7. Start Portfolio Chief (Desk 3 oversight)
.\run.ps1 portfolio-chief

# 8. Open the dashboard
Start-Process http://localhost:3000
```

---

## Environment variables required

| Variable | Required | Notes |
|----------|----------|-------|
| ANTHROPIC_API_KEY | Yes | Claude Haiku for agent prompts |
| DATABASE_URL | Yes | PostgreSQL connection string |
| REDIS_URL | Yes | Redis 7 connection string |
| EIA_API_KEY | Optional | Commodities feed (energy/oil) |
| FRED_API_KEY | Optional | Macro data (Fed rates, CPI) |
| XRPL_WHALE_TRACKING | Optional | Default: true |
| BINANCE_LEADERBOARD_ENABLED | Optional | Default: true |
| COPY_TRADE_MIN_CONFIDENCE | Optional | Default: 0.65 |
| POSITION_MONITOR_INTERVAL_SECONDS | Optional | Default: 5 |
| RISK_MONITOR_INTERVAL_SECONDS | Optional | Default: 30 |
| TRAILING_STOP_TRIGGER_PCT | Optional | Default: 0.05 |

---

## Validation checklist

- [ ] Health check passes all critical checks green (`.\run.ps1 health`)
- [ ] Dashboard loads at http://localhost:3000
- [ ] Positions page shows empty state (no positions yet)
- [ ] Firm page shows three desks with agent names
- [ ] Polymarket page shows live prediction-market signals
- [ ] Paper trading runs one XRP cycle without errors (check structlog output)
- [ ] Position monitor starts and logs `position_monitor_started`
- [ ] Risk monitor starts and logs `risk_monitor_started`
- [ ] Trade Desk starts and logs `trade_desk_started`
- [ ] Portfolio Chief starts and logs `portfolio_chief_started`
- [ ] After one XRP cycle: `stream:trade_desk:inbox` has at least one entry (if conf >= 0.5)
- [ ] Kill switch test: `.\run.ps1 kill-switch` — all loops should pause within 10s

---

## Known manual actions still required

1. **Set real API keys** in `.env` — `ANTHROPIC_API_KEY` is required for agents to run.
   Copy `.env.example` to `.env` and fill in keys.
2. **Install new dependencies** after pulling: `pip install -e .` (anthropic, httpx, yfinance
   are now in main deps — not just dev deps).
3. **sage.py** — the old file still exists alongside graph.py. It can be deleted after
   confirming nothing else imports from it. All scripts now point to graph.py.
