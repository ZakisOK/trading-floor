# The Trading Floor — 5-Minute Paper Trading Guide

This guide gets you from zero to a running paper trading system in under five minutes.
No real money. No exchange accounts. No risk.

---

## Step 1 — Install prerequisites (2 min)

You need Python 3.11+, Node 18+, and Redis. If you already have them, skip ahead.

```bash
# macOS — fastest path with Homebrew
brew install python@3.11 node redis
brew services start redis

# Ubuntu
sudo apt update && sudo apt install python3.11 python3.11-venv nodejs redis-server -y
sudo systemctl start redis
```

Verify Redis is running:

```bash
redis-cli ping   # should print: PONG
```

---

## Step 2 — Clone and install (1 min)

```bash
git clone https://github.com/your-org/trading-floor.git
cd trading-floor

# Python environment
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Frontend
cd frontend && npm install && cd ..
```

---

## Step 3 — Configure the minimum .env (30 sec)

```bash
cp .env.example .env
```

Open `.env` and set one key — everything else defaults to paper mode:

```env
ANTHROPIC_API_KEY=your_key_here    # get it at platform.anthropic.com/account/keys
```

All other variables have safe defaults for paper trading. You do not need exchange
API keys, a database, or any paid data subscriptions to run in paper mode.

---

## Step 4 — Start the system (30 sec)

Open three terminal windows:

```bash
# Terminal 1 — API (port 8000)
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — Dashboard (port 3000)
cd frontend
npm run dev

# Terminal 3 — Paper trading agents
source .venv/bin/activate
python scripts/run_paper_trading.py
```

---

## Step 5 — Open the dashboard

Go to **http://localhost:3000**

You will see the Mission Control page. The system starts in paper mode by default —
confirmed by the **PAPER TRADING** badge in Settings.

### What to look at first:

- **Positions** (`/positions`) — open paper trades as agents place them
- **Agents** (`/agents`) — all 21 AI agents with their current status and confidence
- **Risk** (`/risk`) — live P&L, daily loss tracking, and kill switch
- **Settings** (`/settings`) — verify paper mode is active (System Mode toggle should show Paper)

---

## Paper mode guarantees

- No orders ever leave the system. All fills are simulated with realistic slippage (0.05%) and commission (0.1%).
- Commodity futures (`GC=F`, `CL=F`, etc.) are always paper-only even if you later enable live mode.
- The kill switch in Settings → Risk Controls flattens all simulated positions instantly.
- Switching to live mode requires typing a full confirmation phrase — you cannot do it by accident.

---

## Next steps

When you are ready to go further, read **SETUP.md** for:

- Full `.env` reference with every variable explained
- Database setup (PostgreSQL + QuestDB via Docker)
- Exchange API key configuration for Binance, Coinbase, and Kraken
- The live mode pre-flight checklist
- Deployment on a server with systemd services
