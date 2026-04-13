# The Trading Floor — Full Setup Guide

## Prerequisites

Install all dependencies before running the system.

### Python 3.11

```bash
# macOS (Homebrew)
brew install python@3.11

# Ubuntu / Debian
sudo apt update && sudo apt install python3.11 python3.11-venv python3.11-dev -y

# Windows (winget)
winget install Python.Python.3.11
```

Verify: `python3.11 --version`

### Node.js 18+

```bash
# macOS
brew install node@18

# Ubuntu
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y

# Windows
winget install OpenJS.NodeJS.LTS
```

Verify: `node --version` (must be 18.x or higher)

### Redis 7+

```bash
# macOS
brew install redis && brew services start redis

# Ubuntu
sudo apt install redis-server -y && sudo systemctl enable --now redis

# Windows (via WSL or Docker — see Docker section below)
docker run -d -p 6379:6379 --name redis redis:7-alpine
```

Verify: `redis-cli ping` should return `PONG`

### Docker (optional — for PostgreSQL + QuestDB)

```bash
# macOS / Linux
curl -fsSL https://get.docker.com | sh

# Windows
winget install Docker.DockerDesktop
```

Start the full data stack:

```bash
docker compose up -d
```

This starts PostgreSQL (port 5432) and QuestDB (port 9000 / 9009).

---

## Clone and Install

```bash
git clone https://github.com/your-org/trading-floor.git
cd trading-floor
```

### Python dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

To enable FinBERT sentiment (downloads ~440 MB model on first run):

```bash
pip install -e ".[dev,sentiment]"
```

### Frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Every variable is listed below with its purpose and where to obtain it.

### Core

| Variable | What it does | How to get it |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Defaults to local Docker compose DB |
| `REDIS_URL` | Redis connection string | Defaults to `redis://localhost:6379/0` |
| `SECRET_KEY` | JWT signing key | Run `openssl rand -hex 32` |
| `ENVIRONMENT` | `development` or `production` | Set manually |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) | Set manually |
| `ALLOWED_ORIGINS` | CORS-allowed origins (comma-separated) | e.g. `http://localhost:3000` |

### Anthropic

| Variable | What it does | How to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Powers all AI agents (Claude models) | [platform.anthropic.com](https://platform.anthropic.com/account/keys) → API Keys |

### Exchange API Keys

These keys are used for **live trading only**. In paper mode they are optional.
Never commit real keys to version control — use Redis or `.env` (which is gitignored).

| Variable | What it does | How to get it |
|---|---|---|
| `BINANCE_API_KEY` | Binance order submission + balance | [binance.com/en/account/api](https://www.binance.com/en/account/api) |
| `BINANCE_SECRET` | Binance API secret | Same page as above |
| `COINBASE_API_KEY` | Coinbase Advanced Trade API | [coinbase.com/settings/api](https://www.coinbase.com/settings/api) |
| `COINBASE_SECRET` | Coinbase API secret | Same page |
| `ALPACA_API_KEY` | Alpaca paper/live trading | [app.alpaca.markets/paper-trading/overview](https://app.alpaca.markets) |
| `ALPACA_SECRET_KEY` | Alpaca API secret | Same page |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` for paper; `https://api.alpaca.markets` for live | — |

### Market Data

| Variable | What it does | How to get it |
|---|---|---|
| `POLYGON_API_KEY` | Real-time stock + crypto OHLCV | [polygon.io/dashboard/api-keys](https://polygon.io/dashboard/api-keys) — free tier available |
| `ALPHA_VANTAGE_KEY` | Fallback OHLCV + forex | [alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key) — free |

### Macro & Commodity Data

| Variable | What it does | How to get it |
|---|---|---|
| `FRED_API_KEY` | Yield curve, CPI, unemployment from Federal Reserve | [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html) — free |
| `EIA_API_KEY` | Weekly petroleum inventory reports | [eia.gov/opendata/register.php](https://www.eia.gov/opendata/register.php) — free |

### News & Sentiment

| Variable | What it does | How to get it |
|---|---|---|
| `NEWS_API_KEY` | News headlines for sentiment analysis | [newsapi.org/account](https://newsapi.org/account) — 100 req/day free |
| `SENTIMENT_BACKEND` | `finbert` (accurate, GPU recommended) or `vader` (fast, CPU) | Set manually |

### Options Flow

| Variable | What it does | How to get it |
|---|---|---|
| `UNUSUAL_WHALES_API_KEY` | Unusual options flow data | [unusualwhales.com](https://unusualwhales.com) — paid; leave blank for RSS fallback |

### Trading Mode & Risk

| Variable | What it does | Default |
|---|---|---|
| `TRADING_MODE` | `paper` or `live` | `paper` |
| `AUTONOMY_MODE` | `COMMANDER` (approve each trade) or `AUTONOMOUS` | `COMMANDER` |
| `MAX_RISK_PER_TRADE` | Max fraction of portfolio per trade | `0.02` (2%) |
| `MAX_DAILY_LOSS` | Halt trading when daily loss exceeds this fraction | `0.05` (5%) |

### Copy Trading

| Variable | What it does | Default |
|---|---|---|
| `BINANCE_LEADERBOARD_ENABLED` | Track Binance top trader signals | `true` |
| `XRPL_WHALE_TRACKING` | Monitor XRPL whale wallets | `true` |
| `COPY_TRADE_MIN_CONFIDENCE` | Minimum confidence to emit copy signals (0–1) | `0.65` |

---

## Running in Paper Mode (safe)

Paper mode simulates all order execution — no real funds are ever touched.

```bash
# Terminal 1 — API backend
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev

# Terminal 3 — Agent workers (optional, enables AI signals)
python scripts/run_paper_trading.py
```

Open the dashboard at **http://localhost:3000**

The API docs are at **http://localhost:8000/docs**

Verify everything is connected at **http://localhost:8000/health**

---

## Running in Live Mode

Live mode submits real orders to your configured exchange using real funds.

### Before switching to live, check all of the following:

- [ ] API keys are configured in Redis or `.env` for each exchange you plan to use
- [ ] Sandbox mode is **disabled** on your exchange credentials
- [ ] `MAX_RISK_PER_TRADE` is set to a value you are comfortable losing per trade
- [ ] `MAX_DAILY_LOSS` is set — this is your circuit breaker
- [ ] Kill switch is accessible (Settings → Risk Controls → Kill Switch toggle)
- [ ] You have tested each exchange connection via Settings → Exchange Connections → Test Connection
- [ ] You understand that commodity futures (`GC=F`, `CL=F`, etc.) always run paper-only regardless of mode
- [ ] You have reviewed the Agent Controls and disabled any agents you do not trust
- [ ] `AUTONOMY_MODE=COMMANDER` is set if you want to approve each trade before execution

### Switch to live via the dashboard:

1. Open **http://localhost:3000/settings**
2. Under System Mode, flip the toggle from Paper to Live
3. Read the warning modal carefully
4. Type the confirmation phrase exactly: `I understand this uses real money`
5. Click Enable Live Trading

To revert to paper at any time, flip the toggle back — no confirmation required.

### Emergency halt:

```bash
# Via API
curl -X POST http://localhost:8000/api/orders/kill -H "Content-Type: application/json" \
  -d '{"reason": "manual halt", "operator_id": "operator"}'
```

Or use the Kill Switch toggle in Settings → Risk Controls.

---

## Dashboard URL and Settings Screen Walkthrough

The dashboard runs at **http://localhost:3000** after starting the frontend.

### Settings screen — http://localhost:3000/settings

The settings page is divided into six sections:

**1. System Mode** — The large toggle at the top switches between Paper Trading and Live Trading.
Switching to Live requires typing a confirmation phrase in a modal. The current mode is shown
with a red warning banner when Live is active.

**2. Risk Controls** — Three sliders control Max Daily Loss % (0.5–10), Max Position Size % (1–20),
and Trailing Stop % (1–15). The Kill Switch toggle at the bottom halts all order flow immediately
when enabled.

**3. Exchange Connections** — One card per exchange (Binance, Coinbase, Kraken, Polymarket).
Each card has masked API Key and Secret fields (showing only the last 4 characters), a Passphrase
field (Coinbase only), a Sandbox/Testnet checkbox, an Enabled toggle, and a Test Connection button
that shows latency in milliseconds on success.

**4. Agent Controls** — A grid of all 21 AI agents. Each row has an Enable/Disable toggle and a
Confidence Threshold slider from 0.50 to 0.95. Higher thresholds mean fewer but higher-quality signals.

**5. Asset Universe** — Checkbox-style buttons grouped into Crypto Tier 1, Crypto Alts, and Commodity
Futures. Active symbols have a highlighted border. Deselected symbols are excluded from agent analysis.

**6. Notifications** — A webhook URL input for Discord or Slack with a Test button that sends
a sample message. Compatible with any incoming webhook endpoint.

Click **Save Settings** at the bottom to write all changes to Redis. Click **Discard Changes**
to reload from the current server state.
